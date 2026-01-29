"""
Document Parsers Module

Factory for creating document parsers based on file type.

Usage:
------
    from app.ai.parsers import get_parser, parse_document
    
    # Get specific parser
    parser = get_parser("pdf")
    result = parser.parse(pdf_bytes, "document.pdf")
    
    # Or use convenience function
    result = parse_document(file_bytes, "document.pdf", "pdf")
"""

from typing import Optional

from app.ai.parsers.base import (
    DocumentParser,
    ParsedDocument,
    PageContent,
    ParserType,
)
from app.ai.parsers.pdf_parser import PDFParser
from app.ai.parsers.docx_parser import DOCXParser
from app.ai.parsers.pptx_parser import PPTXParser
from app.ai.parsers.txt_parser import TXTParser


# Parser instances (singleton pattern)
_parsers: dict[ParserType, DocumentParser] = {}


def get_parser(file_type: str) -> Optional[DocumentParser]:
    """
    Get a parser for the specified file type.
    
    Uses singleton pattern - parsers are created once and reused.
    
    Args:
        file_type: File type string (pdf, docx, pptx, txt)
    
    Returns:
        DocumentParser instance or None if unsupported
    
    Example:
        parser = get_parser("pdf")
        if parser:
            result = parser.parse(content)
    """
    try:
        parser_type = ParserType(file_type.lower())
    except ValueError:
        return None
    
    # Check if parser already created
    if parser_type in _parsers:
        return _parsers[parser_type]
    
    # Create appropriate parser
    parser: Optional[DocumentParser] = None
    
    if parser_type == ParserType.PDF:
        parser = PDFParser()
    elif parser_type == ParserType.DOCX:
        parser = DOCXParser()
    elif parser_type == ParserType.PPTX:
        parser = PPTXParser()
    elif parser_type == ParserType.TXT:
        parser = TXTParser()
    
    if parser:
        _parsers[parser_type] = parser
    
    return parser


def parse_document(
    content: bytes,
    filename: str,
    file_type: str
) -> ParsedDocument:
    """
    Convenience function to parse a document.
    
    Gets the appropriate parser and parses the content.
    
    Args:
        content: Raw file bytes
        filename: Original filename
        file_type: File type (pdf, docx, pptx, txt)
    
    Returns:
        ParsedDocument with results
    
    Example:
        result = parse_document(pdf_bytes, "doc.pdf", "pdf")
        if result.success:
            print(result.text)
    """
    parser = get_parser(file_type)
    
    if not parser:
        return ParsedDocument.from_error(
            f"No parser available for file type: {file_type}"
        )
    
    return parser.parse(content, filename)


# Export all public classes and functions
__all__ = [
    # Factory functions
    "get_parser",
    "parse_document",
    
    # Base classes
    "DocumentParser",
    "ParsedDocument",
    "PageContent",
    "ParserType",
    
    # Concrete parsers
    "PDFParser",
    "DOCXParser",
    "PPTXParser",
    "TXTParser",
]