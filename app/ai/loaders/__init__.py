"""
URL and Content Loaders

This package provides loaders for extracting content from various sources:
- Web pages
- YouTube videos
- PDFs
- GitHub repositories
"""

from app.ai.loaders.url_loader import (
    load_url,
    load_webpage,
    load_youtube_transcript,
    load_pdf_url,
    load_github,
    extract_urls_from_text,
    detect_url_type,
    URLType,
)

__all__ = [
    "load_url",
    "load_webpage",
    "load_youtube_transcript",
    "load_pdf_url",
    "load_github",
    "extract_urls_from_text",
    "detect_url_type",
    "URLType",
]
