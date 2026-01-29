"""
PDF Document Parser

Extracts text from PDF files using pypdf.

PDF Challenges:
--------------
PDFs are notoriously difficult to parse because:
1. Text may be stored as vectors, not characters
2. Text order may not match visual layout
3. Tables and columns can scramble text order
4. Scanned PDFs have no text (need OCR)
5. Embedded fonts may use custom encodings

Our Approach:
------------
- Use pypdf for text extraction (fast, pure Python)
- Fall back to page-by-page extraction on errors
- Preserve page numbers for citations
- Extract basic metadata (title, author, etc.)

Limitations:
-----------
- Scanned PDFs return empty text (OCR not implemented)
- Complex layouts may have scrambled text order
- Tables may not be properly structured

For better results on complex PDFs, consider:
- pdfplumber (better table extraction)
- PyMuPDF/fitz (faster, more accurate)
- OCR integration for scanned documents
"""

import io
import logging
from typing import List, Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ai.parsers.base import (
    DocumentParser,
    ParsedDocument,
    PageContent,
    ParserType,
)

logger = logging.getLogger(__name__)


class PDFParser(DocumentParser):
    """
    Parser for PDF documents.
    
    Extracts text content, metadata, and page structure from PDFs.
    
    Usage:
        parser = PDFParser()
        result = parser.parse(pdf_bytes, filename="document.pdf")
        
        for page in result.pages:
            print(f"Page {page.page_number}: {page.text[:100]}...")
    """
    
    @property
    def supported_types(self) -> List[ParserType]:
        return [ParserType.PDF]
    
    def parse(
        self,
        content: bytes,
        filename: Optional[str] = None
    ) -> ParsedDocument:
        """
        Parse PDF and extract text.
        
        Args:
            content: Raw PDF file bytes
            filename: Original filename for logging
        
        Returns:
            ParsedDocument with extracted content
        """
        filename = filename or "unknown.pdf"
        logger.info(f"Parsing PDF: {filename} ({len(content)} bytes)")
        
        try:
            # Create a file-like object from bytes
            # pypdf can read from file objects
            pdf_file = io.BytesIO(content)
            
            # Create PDF reader
            reader = PdfReader(pdf_file)
            
            # Extract metadata
            metadata = self._extract_metadata(reader, filename)
            
            # Extract text from each page
            pages = []
            all_text_parts = []
            
            for page_num, page in enumerate(reader.pages, start=1):
                try:
                    # Extract text from page
                    page_text = page.extract_text() or ""
                    page_text = self._clean_text(page_text)
                    
                    # Extract headings (simple heuristic)
                    headings = self._extract_headings(page_text) if page_text else []
                    
                    # Create page content
                    page_content = PageContent(
                        page_number=page_num,
                        text=page_text,
                        headings=headings,
                        metadata={
                            "has_images": len(page.images) > 0 if hasattr(page, 'images') else False,
                        }
                    )
                    pages.append(page_content)
                    
                    if page_text:
                        all_text_parts.append(f"--- Page {page_num} ---\n{page_text}")
                        
                except Exception as e:
                    logger.warning(f"Error extracting page {page_num}: {e}")
                    # Add empty page to maintain page count
                    pages.append(PageContent(
                        page_number=page_num,
                        text="",
                        metadata={"error": str(e)}
                    ))
            
            # Combine all text
            full_text = "\n\n".join(all_text_parts)
            
            # Check if we got any text
            if not full_text.strip():
                logger.warning(f"No text extracted from PDF: {filename}")
                return ParsedDocument(
                    text="",
                    pages=pages,
                    metadata=metadata,
                    success=True,  # Parsing succeeded, just no text
                    error="PDF appears to be scanned or image-based (no extractable text)"
                )
            
            logger.info(
                f"PDF parsed successfully: {filename}, "
                f"{len(pages)} pages, {len(full_text)} characters"
            )
            
            return ParsedDocument(
                text=full_text,
                pages=pages,
                metadata=metadata,
                success=True
            )
            
        except PdfReadError as e:
            error_msg = f"Invalid or corrupted PDF: {e}"
            logger.error(f"PDF parse error for {filename}: {error_msg}")
            return ParsedDocument.from_error(error_msg)
            
        except Exception as e:
            error_msg = f"Unexpected error parsing PDF: {e}"
            logger.exception(f"PDF parse error for {filename}")
            return ParsedDocument.from_error(error_msg)
    
    def _extract_metadata(
        self,
        reader: PdfReader,
        filename: str
    ) -> dict:
        """
        Extract metadata from PDF.
        
        PDF metadata can include:
        - Title, Author, Subject
        - Creation/modification dates
        - Producer (software used to create)
        - Keywords
        
        Args:
            reader: PdfReader instance
            filename: Filename for fallback title
        
        Returns:
            Dictionary of metadata
        """
        metadata = {
            "filename": filename,
            "page_count": len(reader.pages),
            "file_type": "pdf",
        }
        
        # Try to get PDF metadata
        try:
            if reader.metadata:
                pdf_meta = reader.metadata
                
                # Extract common fields
                if pdf_meta.title:
                    metadata["title"] = pdf_meta.title
                if pdf_meta.author:
                    metadata["author"] = pdf_meta.author
                if pdf_meta.subject:
                    metadata["subject"] = pdf_meta.subject
                if pdf_meta.creator:
                    metadata["creator"] = pdf_meta.creator
                if pdf_meta.producer:
                    metadata["producer"] = pdf_meta.producer
                    
        except Exception as e:
            logger.debug(f"Could not extract PDF metadata: {e}")
        
        # Use filename as title if not found
        if "title" not in metadata:
            # Remove extension and clean up
            title = filename.rsplit('.', 1)[0]
            title = title.replace('_', ' ').replace('-', ' ')
            metadata["title"] = title
        
        return metadata