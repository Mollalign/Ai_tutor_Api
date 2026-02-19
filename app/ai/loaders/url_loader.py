"""
URL Content Loader

Extracts content from various URL types:
- Regular web pages (articles, documentation)
- YouTube videos (transcripts)
- PDFs (download and parse)
- GitHub (repositories, files)

Key Concepts:
- Document Loaders: LangChain's abstraction for loading content
- Each loader returns List[Document] with content and metadata
"""

import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup

# LangChain document loaders
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    WebBaseLoader,
    YoutubeLoader,
)
import tempfile
import os
from langchain_community.document_loaders import PyPDFLoader

logger = logging.getLogger(__name__)

# ============================================================
# URL TYPE DETECTION
# ============================================================

class URLType:
    """Enum-like class for URL types."""
    YOUTUBE = "youtube"
    GITHUB = "github"
    PDF = "pdf"
    WEBPAGE = "webpage"
    UNKNOWN = "unknown"

def detect_url_type(url: str) -> str:
    """
    Detect the type of URL to determine which loader to use.
    
    Args:
        url: The URL to analyze
    
    Returns:
        URLType constant
    """   
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower() 

    # YouTube detection
    if any(yt in domain for yt in ['youtube.com', 'youtu.be']):
        return URLType.YOUTUBE
    
    # GitHub detection
    if 'github.com' in domain:
        return URLType.GITHUB
    
    # PDF detection (by extension or content-type header)
    if path.endswith('.pdf'):
        return URLType.PDF
    
    # Default to webpage
    return URLType.WEBPAGE


# ============================================================
# YOUTUBE LOADER
# ============================================================
"""
YouTubeLoader extracts transcripts from YouTube videos.

How it works:
1. Extracts video ID from URL
2. Fetches transcript via YouTube's transcript API
3. Returns Document with transcript and metadata

Requirements:
- youtube-transcript-api package
- Video must have captions (auto-generated or manual)
"""

def extract_youtube_video_id(url: str) -> Optional[str]:
    """
    Extract video ID from various YouTube URL formats.
    
    Supported formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    """
    parsed = urlparse(url)
    
    if 'youtu.be' in parsed.netloc:
        # Short URL format
        return parsed.path.lstrip('/')
    
    if 'youtube.com' in parsed.netloc:
        if '/watch' in parsed.path:
            # Standard watch URL
            query = parse_qs(parsed.query)
            return query.get('v', [None])[0]
        elif '/embed/' in parsed.path:
            # Embed URL
            return parsed.path.split('/embed/')[1].split('/')[0]
    
    return None

async def load_youtube_transcript(
    url: str,
    language: str = "en"
) -> List[Document]:
    """
    Load transcript from a YouTube video.
    
    Args:
        url: YouTube video URL
        language: Preferred transcript language
    
    Returns:
        List containing single Document with transcript
    
    The Document includes metadata:
    - source: Original URL
    - title: Video title
    - author: Channel name
    - video_id: YouTube video ID
    """
    video_id = extract_youtube_video_id(url)
    
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")
    
    try:
        # YoutubeLoader handles transcript fetching
        loader = YoutubeLoader.from_youtube_url(
            url,
            add_video_info=True,  # Include title, author
            language=[language, "en"],  # Fallback to English
        )
        
        # Load returns List[Document]
        documents = loader.load()

        if not documents:
            raise ValueError("No transcript available for this video")
        
        logger.info(f"Loaded YouTube transcript: {len(documents[0].page_content)} chars")
        return documents
        
    except Exception as e:
        logger.error(f"YouTube transcript error: {e}")
        raise


# ============================================================
# WEB PAGE LOADER
# ============================================================
"""
WebBaseLoader fetches and parses HTML content.

For better article extraction, we use readability-lxml
which removes boilerplate (navigation, ads, etc.).

beautifulsoup4 is used for HTML parsing.
"""

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False
    logger.warning("readability-lxml not installed, using basic extraction")

async def load_webpage(
    url: str,
    use_readability: bool = True
) -> List[Document]:
    """
    Load content from a web page.
    
    Args:
        url: Web page URL
        use_readability: Use readability for article extraction
    
    Returns:
        List containing Document with extracted content
    
    Extraction modes:
    1. Readability: Best for articles, removes boilerplate
    2. Basic: Falls back to BeautifulSoup text extraction
    """
    try:
        # Fetch page with httpx (async HTTP client)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; InformaticsTutor/1.0)"
            }
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        # Extract content
        if use_readability and HAS_READABILITY:
            # Readability extracts main article content
            doc = ReadabilityDocument(html)
            title = doc.title()
            content = doc.summary()
            
            # Clean HTML from readability output
            soup = BeautifulSoup(content, 'html.parser')
            text = soup.get_text(separator='\n', strip=True)
        else:
            # Basic extraction
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove script, style, nav elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()
            
            title = soup.title.string if soup.title else url
            text = soup.get_text(separator='\n', strip=True)
        
        # Create Document
        document = Document(
            page_content=text,
            metadata={
                "source": url,
                "title": title,
                "type": "webpage",
            }
        )
        
        logger.info(f"Loaded webpage: {len(text)} chars from {url}")
        return [document]
        
    except Exception as e:
        logger.error(f"Webpage loading error: {e}")
        raise    


# ============================================================
# PDF LOADER
# ============================================================

async def load_pdf_url(url: str) -> List[Document]:
    """
    Download and parse PDF from URL.

    Flow:
    1. Download PDF to temp file
    2. Load using PyPDFLoader
    3. Return list of Documents (one per page)
    """
    try:
        logger.info(f"Downloading PDF: {url}")

        async with httpx.AsyncClient(timeout=100.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        # Load PDF
        loader = PyPDFLoader(tmp_path)
        documents = loader.load()

        # Add metadata
        for doc in documents:
            doc.metadata["source"] = url
            doc.metadata["type"] = "pdf"

        logger.info(f"Loaded PDF: {len(documents)} pages")

        # Cleanup temp file
        os.remove(tmp_path)

        return documents

    except Exception as e:
        logger.error(f"PDF loading error: {e}")
        raise


# ============================================================
# GITHUB LOADER
# ============================================================

async def load_github(url: str) -> List[Document]:
    """
    Load content from GitHub repo or file.

    Supports:
    - Repo README
    - Specific file
    """
    try:
        info = parse_github_url(url)

        owner = info["owner"]
        repo = info["repo"]

        async with httpx.AsyncClient(timeout=30.0) as client:

            # ---- FILE MODE ----
            if info["type"] == "file":
                raw_url = (
                    f"https://raw.githubusercontent.com/"
                    f"{owner}/{repo}/{info['branch']}/{info['path']}"
                )

                r = await client.get(raw_url)
                r.raise_for_status()
                content = r.text

                return [
                    Document(
                        page_content=content,
                        metadata={
                            "source": url,
                            "type": "github_file",
                            "repo": f"{owner}/{repo}",
                            "path": info["path"],
                        },
                    )
                ]

            # ---- REPO MODE (README) ----
            readme_urls = [
                f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
                f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md",
            ]

            for readme_url in readme_urls:
                r = await client.get(readme_url)
                if r.status_code == 200:
                    return [
                        Document(
                            page_content=r.text,
                            metadata={
                                "source": url,
                                "type": "github_repo",
                                "repo": f"{owner}/{repo}",
                                "file": "README.md",
                            },
                        )
                    ]

            raise ValueError("README not found in repo")

    except Exception as e:
        logger.error(f"GitHub loading error: {e}")
        raise


# ============================================================
# UNIFIED LOADER
# ============================================================

async def load_url(url: str) -> List[Document]:
    """
    Load content from any supported URL type.
    
    Automatically detects URL type and uses appropriate loader.
    
    Args:
        url: Any supported URL
    
    Returns:
        List of Documents extracted from the URL
    """
    url_type = detect_url_type(url)
    
    logger.info(f"Loading URL: {url} (type: {url_type})")
    
    if url_type == URLType.YOUTUBE:
        return await load_youtube_transcript(url)
    
    elif url_type == URLType.WEBPAGE:
        return await load_webpage(url)
    
    elif url_type == URLType.PDF:
        return await load_pdf_url(url)
    
    elif url_type == URLType.GITHUB:
        return await load_github(url)   
    else:
        raise ValueError(f"Unsupported URL type: {url_type}")


# ============================================================
# HELPER: EXTRACT URLS FROM TEXT
# ============================================================

URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+'
)


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract all URLs from a text string.
    
    Useful for automatically detecting URLs in user messages.
    
    Args:
        text: Text that may contain URLs
    
    Returns:
        List of URL strings found
    
    Example:
        >>> extract_urls_from_text("Check out https://example.com for more")
        ['https://example.com']
    """
    return URL_PATTERN.findall(text)    

def parse_github_url(url: str) -> Dict[str, Any]:
    """
    Parse GitHub URL into components.

    Supports:
    - repo root
    - file URLs
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL")

    owner, repo = parts[0], parts[1]

    result = {
        "owner": owner,
        "repo": repo,
        "branch": "main",
        "path": "",
        "type": "repo",
    }

    # File URL detection
    if "blob" in parts:
        blob_index = parts.index("blob")
        result["branch"] = parts[blob_index + 1]
        result["path"] = "/".join(parts[blob_index + 2:])
        result["type"] = "file"

    return result

