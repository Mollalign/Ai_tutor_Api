"""
Plain Text Parser

Simple parser for plain text files (.txt).

Encoding Handling:
-----------------
Text files can have various encodings:
- UTF-8 (most common, default)
- Latin-1/ISO-8859-1 (Windows legacy)
- UTF-16 (less common)

We try UTF-8 first, then fall back to Latin-1 which
can decode any byte sequence (though possibly incorrectly).
"""

import logging
from typing import List, Optional

from app.ai.parsers.base import (
    DocumentParser,
    ParsedDocument,
    PageContent,
    ParserType,
)

logger = logging.getLogger(__name__)


class TXTParser(DocumentParser):
    """
    Parser for plain text files.
    
    Handles encoding detection and text cleanup.
    Treats the entire file as one page.
    """
    
    @property
    def supported_types(self) -> List[ParserType]:
        return [ParserType.TXT]
    
    def parse(
        self,
        content: bytes,
        filename: Optional[str] = None
    ) -> ParsedDocument:
        """
        Parse text file and extract content.
        
        Args:
            content: Raw file bytes
            filename: Original filename
        
        Returns:
            ParsedDocument with text content
        """
        filename = filename or "unknown.txt"
        logger.info(f"Parsing TXT: {filename} ({len(content)} bytes)")
        
        try:
            # Try to decode with different encodings
            text = self._decode_content(content)
            
            if text is None:
                return ParsedDocument.from_error("Could not decode text file")
            
            # Clean the text
            text = self._clean_text(text)
            
            # Extract potential headings
            headings = self._extract_headings(text)
            
            # Build metadata
            metadata = {
                "filename": filename,
                "file_type": "txt",
                "character_count": len(text),
                "line_count": text.count('\n') + 1,
            }
            
            # Create page content
            page_content = PageContent(
                page_number=1,
                text=text,
                headings=headings,
                metadata={}
            )
            
            logger.info(
                f"TXT parsed successfully: {filename}, "
                f"{len(text)} characters"
            )
            
            return ParsedDocument(
                text=text,
                pages=[page_content],
                metadata=metadata,
                success=True
            )
            
        except Exception as e:
            error_msg = f"Error parsing text file: {e}"
            logger.exception(f"TXT parse error for {filename}")
            return ParsedDocument.from_error(error_msg)
    
    def _decode_content(self, content: bytes) -> Optional[str]:
        """
        Try to decode bytes using various encodings.
        
        Args:
            content: Raw bytes
        
        Returns:
            Decoded string or None if all attempts fail
        """
        # List of encodings to try, in order of preference
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'utf-16']
        
        for encoding in encodings:
            try:
                text = content.decode(encoding)
                logger.debug(f"Successfully decoded with {encoding}")
                return text
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        logger.error("Failed to decode text with any encoding")
        return None