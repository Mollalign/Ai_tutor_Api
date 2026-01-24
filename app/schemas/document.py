"""
Document Schemas
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator, computed_field


# ============================================================
# ENUMS - Typed Constants
# ============================================================
class DocumentStatus(str, Enum):
    """
    Document processing status.
    """
    PENDING = "pending"       # File uploaded, waiting for processing
    PROCESSING = "processing" # Worker is currently processing
    READY = "ready"           # Processing complete, ready for AI queries
    FAILED = "failed"         # Processing failed (see error_message)


class FileType(str, Enum):
    """
    Allowed file types for document upload.
    """
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"


# ============================================================
# MIME TYPE MAPPINGS
# ============================================================
MIME_TYPE_MAPPING: dict[str, FileType] = {
    # PDF - Portable Document Format
    "application/pdf": FileType.PDF,
    
    # DOCX - Microsoft Word (Office Open XML)
    # DOCX is actually a ZIP file containing XML
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.DOCX,
    
    # PPTX - Microsoft PowerPoint (Office Open XML)
    # Also a ZIP file containing XML
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": FileType.PPTX,
    
    # Plain text
    "text/plain": FileType.TXT,
    
    # Some systems detect UTF-8 text differently
    "text/plain; charset=utf-8": FileType.TXT,
    "text/plain; charset=us-ascii": FileType.TXT,
}

# Reverse mapping: FileType → list of MIME types
FILE_TYPE_TO_MIMES: dict[FileType, list[str]] = {
    FileType.PDF: ["application/pdf"],
    FileType.DOCX: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    FileType.PPTX: ["application/vnd.openxmlformats-officedocument.presentationml.presentation"],
    FileType.TXT: ["text/plain", "text/plain; charset=utf-8", "text/plain; charset=us-ascii"],
}


def get_file_type_from_mime(mime_type: str) -> Optional[FileType]:
    """
    Get FileType from MIME type string.
    """
    return MIME_TYPE_MAPPING.get(mime_type)


def get_allowed_extensions() -> list[str]:
    """
    Get list of allowed file extensions.
    
    Used for:
    - Quick client-side validation
    - Error messages
    - API documentation
    
    Returns:
        List like ["pdf", "docx", "pptx", "txt"]
    """
    return [ft.value for ft in FileType]


# ============================================================
# INTERNAL SCHEMAS - Used by Service Layer
# ============================================================

class DocumentCreateInternal(BaseModel):
    """
    Internal schema for creating a document record.
    
    Used by DocumentService after file validation and storage.
    Not exposed in API - the API receives a file upload, not this schema.
    
    This separates:
    - What the API accepts (multipart file upload)
    - What we store in database (this schema)
    """
    project_id: UUID = Field(
        ...,  # Required
        description="ID of the project this document belongs to"
    )
    filename: str = Field(
        ...,
        max_length=255,
        description="Unique storage filename (UUID-prefixed)"
    )
    original_filename: str = Field(
        ...,
        max_length=255,
        description="Original filename from user"
    )
    file_type: FileType = Field(
        ...,
        description="Detected file type"
    )
    file_path: str = Field(
        ...,
        max_length=500,
        description="Full storage path"
    )
    file_size: int = Field(
        ...,
        gt=0,  # Greater than 0
        description="File size in bytes"
    )
    status: DocumentStatus = Field(
        default=DocumentStatus.PENDING,
        description="Initial processing status"
    )


class DocumentUpdateInternal(BaseModel):
    """
    Internal schema for updating document fields.
    
    All fields are optional - only provided fields are updated.
    Used for status updates during background processing.
    
    Why separate from Create schema?
    - Create has required fields
    - Update has all optional fields
    - Different validation rules
    """
    status: Optional[DocumentStatus] = None
    error_message: Optional[str] = Field(
        None,
        max_length=5000,
        description="Error details if processing failed"
    )
    chunk_count: Optional[int] = Field(
        None,
        ge=0,  # Greater than or equal to 0
        description="Number of text chunks created"
    )
    processed_at: Optional[datetime] = Field(
        None,
        description="When processing completed"
    )


# ============================================================
# RESPONSE SCHEMAS - What API Returns to Clients
# ============================================================

class DocumentResponse(BaseModel):
    """
    Document data returned to API clients.
    
    This is the public view of a document. It includes
    everything the client needs but nothing sensitive.
    
    Used by:
    - GET /projects/{id}/documents/{id}
    - POST /projects/{id}/documents (after upload)
    - GET /projects/{id}/documents (list, each item)
    """
    id: UUID = Field(
        ...,
        description="Unique document identifier"
    )
    project_id: UUID = Field(
        ...,
        description="ID of the parent project"
    )
    original_filename: str = Field(
        ...,
        description="Original filename uploaded by user",
        examples=["Lecture_Notes_Week_1.pdf"]
    )
    file_type: FileType = Field(
        ...,
        description="Type of document",
        examples=["pdf"]
    )
    file_size: int = Field(
        ...,
        description="File size in bytes",
        examples=[1048576]
    )
    status: DocumentStatus = Field(
        ...,
        description="Current processing status",
        examples=["ready"]
    )
    error_message: Optional[str] = Field(
        None,
        description="Error details if status is 'failed'"
    )
    chunk_count: int = Field(
        default=0,
        description="Number of text chunks (for RAG)"
    )
    created_at: datetime = Field(
        ...,
        description="When document was uploaded"
    )
    processed_at: Optional[datetime] = Field(
        None,
        description="When processing completed"
    )
    
    # Computed property: human-readable file size
    @computed_field
    @property
    def file_size_display(self) -> str:
        """
        Human-readable file size.
        
        Computed fields are calculated on the fly, not stored.
        They appear in JSON responses automatically.
        
        Example: 1048576 bytes → "1.00 MB"
        """
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"
    
    @computed_field
    @property
    def is_ready(self) -> bool:
        """
        Quick check if document is ready for AI queries.
        
        Useful for UI to know whether to enable chat features.
        """
        return self.status == DocumentStatus.READY
    
    class Config:
        """Pydantic configuration."""
        from_attributes = True  # Allows creating from SQLAlchemy model
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "project_id": "0e8f5c4a-3c41-4c3f-9af7-2c8d7db3d6d4",
                "original_filename": "Lecture_Notes_Week_1.pdf",
                "file_type": "pdf",
                "file_size": 1048576,
                "file_size_display": "1.00 MB",
                "status": "ready",
                "error_message": None,
                "chunk_count": 42,
                "is_ready": True,
                "created_at": "2024-01-15T10:30:00Z",
                "processed_at": "2024-01-15T10:31:23Z"
            }
        }


class DocumentListResponse(BaseModel):
    """
    Response for listing documents with pagination metadata.
    """
    documents: List[DocumentResponse] = Field(
        ...,
        description="List of documents"
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total count of documents (for pagination)"
    )
    
    @computed_field
    @property
    def has_more(self) -> bool:
        """Whether there are more documents beyond this page."""
        return len(self.documents) < self.total
    
    class Config:
        json_schema_extra = {
            "example": {
                "documents": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "original_filename": "lecture.pdf",
                        "file_type": "pdf",
                        "status": "ready"
                    }
                ],
                "total": 15,
                "has_more": True
            }
        }


class DocumentUploadResponse(BaseModel):
    """
    Response returned immediately after file upload.
    
    This is returned BEFORE processing completes.
    The client should poll or use WebSocket for status updates.
    
    Includes a message explaining the async processing.
    """
    document: DocumentResponse = Field(
        ...,
        description="The uploaded document (status will be 'pending')"
    )
    message: str = Field(
        default="Document uploaded successfully. Processing started.",
        description="Human-readable status message"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "document": {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "original_filename": "lecture.pdf",
                    "status": "pending"
                },
                "message": "Document uploaded successfully. Processing started."
            }
        }


# ============================================================
# VALIDATION SCHEMAS
# ============================================================
# These are used for validating file uploads before storage.
# ============================================================

class FileValidationResult(BaseModel):
    """
    Result of file validation.
    
    Used internally to pass validation results between functions.
    Contains both the validated data and any issues found.
    """
    is_valid: bool = Field(
        ...,
        description="Whether the file passed all validation"
    )
    file_type: Optional[FileType] = Field(
        None,
        description="Detected file type if valid"
    )
    mime_type: Optional[str] = Field(
        None,
        description="Detected MIME type"
    )
    file_size: int = Field(
        ...,
        description="File size in bytes"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="List of validation errors"
    )
    
    @property
    def error_message(self) -> Optional[str]:
        """Combined error message if validation failed."""
        if self.is_valid:
            return None
        return "; ".join(self.errors)


# ============================================================
# QUERY SCHEMAS - For Filtering/Sorting
# ============================================================

class DocumentQueryParams(BaseModel):
    """
    Query parameters for listing documents.
    
    Used to filter and paginate document lists.
    These come from URL query parameters:
    
    GET /projects/123/documents?status=ready&limit=10&offset=0
    """
    status: Optional[DocumentStatus] = Field(
        None,
        description="Filter by processing status"
    )
    file_type: Optional[FileType] = Field(
        None,
        description="Filter by file type"
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum documents to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of documents to skip"
    )