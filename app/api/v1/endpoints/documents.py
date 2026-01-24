"""
Document Endpoints

HTTP API for document management (file upload, listing, deletion).
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query,
    UploadFile,
    File,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.document import (
    DocumentResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    DocumentQueryParams,
    DocumentStatus,
    FileType,
    get_allowed_extensions,
)
from app.services.document_service import (
    DocumentService,
    DocumentNotFoundError,
    DocumentValidationError,
    ProjectNotFoundError,
    DocumentServiceError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# ============================================================
# Router Setup
# ============================================================

router = APIRouter(tags=["Documents"])

# ============================================================
# Helper Functions
# ============================================================

def get_document_service(db: AsyncSession = Depends(get_db)) -> DocumentService:
    """
    Dependency that provides DocumentService instance.
    
    This is a factory function that creates a new service
    for each request with the request's database session.
    """
    return DocumentService(db)

# ============================================================
# UPLOAD ENDPOINT
# ============================================================

@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
    description="""
    Upload a document file to a project.
    
    **Supported file types:** PDF, DOCX, PPTX, TXT
    
    **Maximum file size:** 50 MB
    """,
    responses={
        201: {
            "description": "Document uploaded successfully",
            "model": DocumentUploadResponse,
        },
        400: {
            "description": "Invalid file (wrong type, too large, etc.)",
            "content": {
                "application/json": {
                    "example": {"detail": "File type '.exe' not allowed"}
                }
            },
        },
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
        413: {
            "description": "File too large",
            "content": {
                "application/json": {
                    "example": {"detail": "File size (75.5 MB) exceeds maximum (50 MB)"}
                }
            },
        },
    },
)
async def upload_document(
    project_id: UUID,
    file: UploadFile = File(
        ...,
        description="Document file to upload (PDF, DOCX, PPTX, or TXT)"
    ),
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Upload a document to a project.
    
    The file will be validated, stored, and queued for background processing.
    Processing extracts text and creates embeddings for AI search.
    """
    try:
        result = await service.upload_document(
            file=file,
            project_id=project_id,
            user_id=current_user.id
        )
        return result
        
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    except DocumentValidationError as e:
        # Determine appropriate status code
        error_msg = str(e)
        if "exceeds maximum" in error_msg:
            status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(status_code=status_code, detail=error_msg)
        
    except DocumentServiceError as e:
        logger.error(f"Document upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload document"
        )
    

# ============================================================
# LIST ENDPOINT
# ============================================================

@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List project documents",
    description="""
    Get all documents in a project with optional filtering.
    """,
    responses={
        200: {"description": "List of documents", "model": DocumentListResponse},
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    },
)   
async def list_documents(
    project_id: UUID,
    status_filter: Optional[DocumentStatus] = Query(
        None,
        alias="status",
        description="Filter by processing status"
    ),
    file_type: Optional[FileType] = Query(
        None,
        description="Filter by file type"
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum documents to return"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of documents to skip"
    ),
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
): 
    """
    List all documents in a project.
    """
    try:
        params = DocumentQueryParams(
            status=status_filter,
            file_type=file_type,
            limit=limit,
            offset=offset
        )
        
        return await service.list_documents(
            project_id=project_id,
            user_id=current_user.id,
            params=params
        )
        
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    

# ============================================================
# STATISTICS ENDPOINT
# ============================================================

@router.get(
    "/stats",
    summary="Get document statistics",
    description="""
    Get statistics about documents in a project.
    
    Returns:
    - Total document count
    - Count by processing status
    - Count by file type
    - Total storage used
    """,
    responses={
        200: {
            "description": "Document statistics",
            "content": {
                "application/json": {
                    "example": {
                        "total": 10,
                        "by_status": {"ready": 5, "pending": 3, "failed": 2},
                        "by_type": {"pdf": 6, "docx": 4},
                        "total_size": 52428800
                    }
                }
            }
        },
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    },
)
async def get_document_stats(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Get document statistics for a project.
    
    Useful for dashboard displays showing:
    - How many documents are uploaded
    - Processing status distribution
    - Storage usage
    """
    try:
        return await service.get_project_document_stats(
            project_id=project_id,
            user_id=current_user.id
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
# ============================================================
# GET SINGLE DOCUMENT
# ============================================================

@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document details",
    description="Get details of a specific document including processing status.",
    responses={
        200: {"description": "Document details", "model": DocumentResponse},
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found"},
    },
)
async def get_document(
    project_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Get a single document by ID.
    """  
    try:
        return await service.get_document(
            document_id=document_id,
            user_id=current_user.id
        )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )  


# ============================================================
# DELETE DOCUMENT
# ============================================================

@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description="""
    Delete a document and its associated files.
    """,
    responses={
        204: {"description": "Document deleted successfully"},
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found"},
    },
) 
async def delete_document(
    project_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Delete a document.
    """
    try:
        await service.delete_document(
            document_id=document_id,
            user_id=current_user.id
        )
        return None  # 204 No Content
        
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    except DocumentServiceError as e:
        logger.error(f"Document deletion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )

# ============================================================
# REPROCESS DOCUMENT
# ============================================================

@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentResponse,
    summary="Reprocess a document",
    description="""
    Queue a document for reprocessing.
    
    **Use cases:**
    - Retry after processing failure
    - Reprocess after parser improvements
    - Regenerate embeddings after model updates
    
    The document status will be reset to `pending` and 
    it will be added to the processing queue.
    """,
    responses={
        200: {"description": "Document queued for reprocessing"},
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found"},
    },
)
async def reprocess_document(
    project_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):   
    """
    Reprocess a document.
    
    **Why POST instead of PUT/PATCH?**
    
    This is an ACTION (reprocess), not an UPDATE to document fields.
    POST is appropriate for actions that cause side effects.
    
    The `/reprocess` suffix makes it a sub-resource action pattern:
    - POST /documents/{id}/reprocess (action)
    - PATCH /documents/{id} (update fields)
    """
    try:
        return await service.reprocess_document(
            document_id=document_id,
            user_id=current_user.id
        )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

# ============================================================
# DOWNLOAD DOCUMENT
# ============================================================

@router.get(
    "/{document_id}/download",
    summary="Download document file",
    description="""
    Download the original document file.
    
    Returns the file with appropriate Content-Type header
    and Content-Disposition for browser download.
    """,
    responses={
        200: {
            "description": "Document file",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {},
                "text/plain": {},
            }
        },
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found"},
    },
)
async def download_document(
    project_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):   
    """
    Download the original document file.
    
    **StreamingResponse:**
    
    For file downloads, we use StreamingResponse to:
    1. Set correct Content-Type (application/pdf, etc.)
    2. Set Content-Disposition header (triggers browser download)
    3. Stream large files without loading entirely into memory
    
    **Content-Disposition header:**
    - `attachment`: Browser should download, not display
    - `filename`: Suggested filename for saving
    
    Example header:
    Content-Disposition: attachment; filename="lecture_notes.pdf"
    """
    try:
        content, filename, content_type = await service.get_document_content(
            document_id=document_id,
            user_id=current_user.id
        )
        
        # Create streaming response
        # For small files, we can yield the entire content at once
        # For large files, we could yield chunks
        def iterate_content():
            yield content
        
        return StreamingResponse(
            iterate_content(),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(content)),
            }
        ) 
    
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    except DocumentServiceError as e:
        logger.error(f"Document download failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download document"
        )


# ============================================================
# API INFO ENDPOINT
# ============================================================

@router.get(
    "/info/allowed-types",
    summary="Get allowed file types",
    description="Get list of allowed file types and size limits for upload.",
    responses={
        200: {
            "description": "Upload configuration",
            "content": {
                "application/json": {
                    "example": {
                        "allowed_extensions": ["pdf", "docx", "pptx", "txt"],
                        "max_file_size_mb": 50,
                        "max_file_size_bytes": 52428800
                    }
                }
            }
        }
    }
)
async def get_allowed_file_types():
    """
    Get allowed file types and upload limits.
    
    This is a public endpoint (no auth required) that clients
    can use to:
    - Show allowed types in file picker
    - Validate before upload
    - Display size limits to users
    
    **Note:** This endpoint is under /documents/info to avoid
    conflict with /{document_id} path.
    """
    return {
        "allowed_extensions": get_allowed_extensions(),
        "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        "max_file_size_bytes": settings.MAX_FILE_SIZE_BYTES,
    }    
