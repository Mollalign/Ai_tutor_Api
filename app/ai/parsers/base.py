"""
Document Parser Base Class

Abstract base class for all document parsers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ParserType(str, Enum):
    """Supported parser types."""
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"


@dataclass
class PageContent:
    """
    Content from a single page or slide.
    
    Keeping content per-page allows us to:
    - Cite specific pages in AI responses
    - Navigate large documents
    - Create page-level embeddings
    
    Attributes:
        page_number: 1-indexed page number
        text: Text content of this page
        headings: List of headings found on this page
        metadata: Page-specific metadata (images, tables, etc.)
    """
    page_number: int
    text: str
    headings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def word_count(self) -> int:
        """Approximate word count for this page."""
        return len(self.text.split())
    
    @property
    def is_empty(self) -> bool:
        """Check if page has no meaningful content."""
        return len(self.text.strip()) == 0    


@dataclass
class ParsedDocument:
    """
    Result of parsing a document.
    
    This is the standardized output format for all parsers.
    Regardless of input format, output is consistent.
    
    Attributes:
        text: Full document text (all pages combined)
        pages: List of per-page content
        metadata: Document-level metadata
        success: Whether parsing succeeded
        error: Error message if parsing failed
    """
    text: str
    pages: List[PageContent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None

    @property
    def page_count(self) -> int:
        """Number of pages in the document."""
        return len(self.pages)
    
    @property
    def total_words(self) -> int:
        """Total word count across all pages."""
        return sum(page.word_count for page in self.pages)
    
    @property
    def all_headings(self) -> List[str]:
        """All headings from all pages."""
        headings = []
        for page in self.pages:
            headings.extend(page.headings)
        return headings
    
    @classmethod
    def from_error(cls, error_message: str) -> "ParsedDocument":
        """Create a ParsedDocument representing a parsing failure."""
        return cls(
            text="",
            pages=[],
            metadata={},
            success=False,
            error=error_message
        )


class DocumentParser(ABC):
    """
    Abstract base class for document parsers.
    
    All document parsers must inherit from this class and
    implement the parse() method.
    
    Usage:
        parser = PDFParser()
        result = parser.parse(pdf_bytes, filename="doc.pdf")
        
        if result.success:
            print(f"Extracted {result.total_words} words")
            for page in result.pages:
                print(f"Page {page.page_number}: {page.word_count} words")
        else:
            print(f"Error: {result.error}")
    """    
    @property
    @abstractmethod
    def supported_types(self) -> List[ParserType]:
        """
        List of file types this parser can handle.
        
        Most parsers handle one type, but some might handle multiple
        (e.g., a text parser might handle .txt, .md, .csv).
        """
        pass

    @abstractmethod
    def parse(
        self,
        content: bytes,
        filename: Optional[str] = None
    ) -> ParsedDocument:
        """
        Parse document content and extract text.
        
        Args:
            content: Raw file bytes
            filename: Original filename (for logging/metadata)
        
        Returns:
            ParsedDocument with extracted content
        
        Note:
            This method should NEVER raise exceptions.
            All errors should be returned in ParsedDocument.
        """
        pass

    def can_parse(self, file_type: str) -> bool:
        """Check if this parser can handle the given file type."""
        try:
            parser_type = ParserType(file_type.lower())
            return parser_type in self.supported_types
        except ValueError:
            return False


    def _clean_text(self, text: str) -> str:
        """
        Clean extracted text.
        
        Common cleaning operations:
        - Normalize whitespace
        - Remove null characters
        - Fix encoding issues
        
        Args:
            text: Raw extracted text
        
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Remove null characters
        text = text.replace('\x00', '')
        
        # Normalize whitespace (but preserve paragraph breaks)
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Collapse multiple spaces into one
            cleaned = ' '.join(line.split())
            cleaned_lines.append(cleaned)
        
        # Rejoin with single newlines, collapse multiple blank lines
        text = '\n'.join(cleaned_lines)
        
        # Collapse more than 2 consecutive newlines into 2
        while '\n\n\n' in text:
            text = text.replace('\n\n\n', '\n\n')
        
        return text.strip()    
    
    
    def _extract_headings(self, text: str) -> List[str]:
        """
        Extract potential headings from text.
        
        Simple heuristic: Lines that are short, don't end with
        punctuation, and are followed by longer text.
        
        This is a fallback for formats that don't have
        explicit heading markup.
        """
        headings = []
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Heading heuristics
            is_short = len(line) < 100
            no_end_punctuation = not line[-1] in '.,:;'
            not_starts_with_bullet = not line[0] in '-*•–'
            
            # Check if followed by content
            has_following_content = (
                i + 1 < len(lines) and 
                len(lines[i + 1].strip()) > len(line)
            )
            
            if is_short and no_end_punctuation and not_starts_with_bullet:
                # Could be a heading
                if has_following_content or line.isupper():
                    headings.append(line)
        
        return headings[:20]