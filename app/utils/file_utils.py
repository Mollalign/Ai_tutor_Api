"""
File Utilities

Helper functions for file handling, validation, and security.
Always assume user input is malicious!
"""

import os
import re
import uuid
import logging
from typing import Optional, Tuple
from pathlib import Path

import filetype

from app.core.config import settings
from app.schemas.document import (
    FileType,
    FileValidationResult,
    get_file_type_from_mime,
    get_allowed_extensions,
)

logger = logging.getLogger(__name__)

# ============================================================
# MIME TYPE DETECTION
# ============================================================
def detect_mime_type(file_content: bytes) -> str:
    """
    Detect the actual MIME type of a file by reading its magic bytes.

    Uses the pure-Python ``filetype`` library so no system
    dependencies (libmagic) are needed on cloud platforms.
    """
    kind = filetype.guess(file_content)

    if kind is not None:
        logger.debug(f"Detected MIME type: {kind.mime}")
        return kind.mime

    # filetype doesn't detect plain text -- check manually
    try:
        file_content[:1024].decode("utf-8")
        logger.debug("Detected MIME type: text/plain (fallback)")
        return "text/plain"
    except (UnicodeDecodeError, ValueError):
        pass

    return "application/octet-stream"


def detect_mime_type_from_path(file_path: str) -> str:
    """
    Detect MIME type from a file path.

    Args:
        file_path: Path to the file

    Returns:
        MIME type string
    """
    kind = filetype.guess(file_path)
    if kind is not None:
        return kind.mime

    try:
        with open(file_path, "rb") as f:
            f.read(1024).decode("utf-8")
        return "text/plain"
    except (UnicodeDecodeError, ValueError, OSError):
        return "application/octet-stream"


# ============================================================
# FILENAME HANDLING
# ============================================================

def sanitize_filename(filename: str) -> str:
    """
    Remove dangerous characters from a filename.
    """
    # Remove path components (user might include full path)
    filename = os.path.basename(filename)
    
    # Remove null bytes (security)
    filename = filename.replace("\x00", "")

    # Replace dangerous characters with underscore
    # \\w matches letters, digits, underscore (Unicode-aware)
    # We also allow hyphen and dot
    filename = re.sub(r'[^\w\-.]', '_', filename)

    # Collapse multiple underscores
    filename = re.sub(r'_+', '_', filename)

    # Remove leading/trailing underscores and dots
    filename = filename.strip('_.')

    # Limit length (filesystem limits vary, 200 is safe)
    if len(filename) > 200:
        # Keep extension, truncate name
        name, ext = os.path.splitext(filename)
        max_name_len = 200 - len(ext)
        filename = name[:max_name_len] + ext

    # If filename is empty after sanitization, use a default
    if not filename:
        filename = "unnamed_file"
    
    return filename    


def generate_storage_filename(original_filename: str) -> Tuple[str, str]:
    """
    Generate a unique storage filename.
    """
    # Sanitize first
    sanitized = sanitize_filename(original_filename)
    
    # Generate UUID prefix (12 chars is enough for uniqueness)
    # Full UUID is 32 hex chars, 12 gives us 16^12 = 281 trillion combinations
    unique_prefix = uuid.uuid4().hex[:12]
    
    # Combine: prefix_filename
    storage_name = f"{unique_prefix}_{sanitized}"
    
    return storage_name, sanitized


def build_document_path(
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    storage_filename: str
) -> str:
    """
    Build the full storage path for a document.

    Example:
        path = build_document_path(
            user_id=UUID("550e8400-..."),
            project_id=UUID("0e8f5c4a-..."),
            storage_filename="abc123_notes.pdf"
        )
        # Returns: "uploads/550e8400-.../0e8f5c4a-.../abc123_notes.pdf"
    """
    return f"uploads/{user_id}/{project_id}/{storage_filename}"


def get_file_extension(filename: str) -> str:
    """
    Extract file extension from filename.
    
    Returns lowercase extension without dot.
    
    Args:
        filename: Filename to extract extension from
    
    Returns:
        Lowercase extension or empty string
    
    Example:
        get_file_extension("document.PDF")  # "pdf"
        get_file_extension("noextension")   # ""
    """
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip('.')  # Remove dot, lowercase


# ============================================================
# FILE VALIDATION
# ============================================================

def validate_file_extension(filename: str) -> Tuple[bool, Optional[str]]:
    """
    Quick validation of file extension.
    
    This is a fast first check before reading file content.
    Even if extension is valid, we still validate MIME type later.
    
    Args:
        filename: Original filename
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Example:
        valid, error = validate_file_extension("doc.pdf")   # (True, None)
        valid, error = validate_file_extension("virus.exe") # (False, "...")
    """
    extension = get_file_extension(filename)
    allowed = get_allowed_extensions()
    
    if extension not in allowed:
        return False, f"File type '.{extension}' not allowed. Allowed: {', '.join(allowed)}"
    
    return True, None


def validate_file_size(file_size: int) -> Tuple[bool, Optional[str]]:
    """
    Validate file size against configured maximum.
    
    Args:
        file_size: Size in bytes
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Example:
        # If MAX_FILE_SIZE_MB = 50
        validate_file_size(1024)          # (True, None) - 1KB
        validate_file_size(100_000_000)   # (False, "...") - 100MB
    """
    max_size = settings.MAX_FILE_SIZE_BYTES
    
    if file_size <= 0:
        return False, "File is empty"
    
    if file_size > max_size:
        size_mb = file_size / (1024 * 1024)
        max_mb = settings.MAX_FILE_SIZE_MB
        return False, f"File size ({size_mb:.1f} MB) exceeds maximum ({max_mb} MB)"
    
    return True, None


def validate_file(
    file_content: bytes,
    original_filename: str
) -> FileValidationResult:
    """
    Comprehensive file validation.
    
    Validates:
    1. File size (within limits)
    2. File extension (quick check)
    3. MIME type (actual content check)
    4. Extension matches content
    """
    errors = []
    file_size = len(file_content)

    # 1. Validate file size
    size_valid, size_error = validate_file_size(file_size)
    if not size_valid:
        errors.append(size_error)
    
    # 2. Validate extension (quick check)
    ext_valid, ext_error = validate_file_extension(original_filename)
    if not ext_valid:
        errors.append(ext_error)
    
    # 3. Detect actual MIME type
    try:
        mime_type = detect_mime_type(file_content)
    except Exception as e:
        logger.error(f"MIME detection failed: {e}")
        errors.append("Could not determine file type")
        return FileValidationResult(
            is_valid=False,
            file_type=None,
            mime_type=None,
            file_size=file_size,
            errors=errors
        )
    
    # 4. Check if MIME type is allowed
    file_type = get_file_type_from_mime(mime_type)
    if file_type is None:
        errors.append(f"File content type '{mime_type}' is not allowed")
    
    # 5. Check extension matches content
    # (e.g., .pdf file should have PDF content)
    if file_type is not None and ext_valid:
        expected_extension = get_file_extension(original_filename)
        if expected_extension != file_type.value:
            # This is a warning, not an error
            # File with wrong extension but valid content is still acceptable
            logger.warning(
                f"Extension mismatch: file has '.{expected_extension}' "
                f"but content is '{file_type.value}'"
            )
    
    return FileValidationResult(
        is_valid=len(errors) == 0,
        file_type=file_type,
        mime_type=mime_type,
        file_size=file_size,
        errors=errors
    )

# ============================================================
# SIZE FORMATTING
# ============================================================

def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
    
    Returns:
        Formatted string like "1.5 MB"
    
    Example:
        format_file_size(1536)      # "1.50 KB"
        format_file_size(1048576)   # "1.00 MB"
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"
    