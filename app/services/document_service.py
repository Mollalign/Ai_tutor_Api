"""
Document Service

Business logic for document operations.
"""

import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import UploadFile

from app.models.document import Document
from app.models.project import Project
from app.repositories.document_repo import DocumentRepository
from app.repositories.project_repo import ProjectRepository
from app.schemas.document import (
    DocumentStatus,
    FileType,
    DocumentResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    DocumentCreateInternal,
    DocumentQueryParams,
)
from app.storage import get_storage, StorageBackend, StorageError
from app.utils.file_utils import (
    validate_file,
    generate_storage_filename,
    build_document_path,
    sanitize_filename,
)
from app.db.redis import get_arq_pool
from app.core.config import settings

logger = logging.getLogger(__name__)

class DocumentServiceError(Exception):
    """Base exception for document service errors."""
    pass

class DocumentNotFoundError(DocumentServiceError):
    """Raised when document is not found."""
    pass

class DocumentValidationError(DocumentServiceError):
    """Raised when file validation fails."""
    pass

class ProjectNotFoundError(DocumentServiceError):
    """Raised when project is not found or not accessible."""
    pass


class DocumentService:
    """
    Service class for document operations.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize service with database session.
        
        Dependencies are injected via the session.
        Storage and Redis connections are obtained from singletons.
        
        Args:
            db: Async database session
        """
        self.db = db
        self.document_repo = DocumentRepository(db)
        self.project_repo = ProjectRepository(db)
        self.storage: StorageBackend = get_storage()

    # ============================================================
    # HELPER METHODS - Validation and Authorization
    # ============================================================

    async def _verify_project_access(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> Project:
        """
        Verify user has access to the project.
        """
        project = await self.project_repo.get_by_id(project_id)
    
        if not project:
            logger.warning(f"Project not found: {project_id}")
            raise ProjectNotFoundError("Project not found")
        
        if project.user_id != user_id:
            # Log as security event
            logger.warning(
                f"Unauthorized access attempt: user {user_id} "
                f"tried to access project {project_id} owned by {project.user_id}"
            )
            raise ProjectNotFoundError("Project not found")  # Don't reveal existence
        
        return project
    
    async def _verify_document_access(
        self,
        document_id: UUID,
        user_id: UUID
    ) -> Document:
        """
        Verify user has access to the document.
        """
        document = await self.document_repo.get_by_id(document_id)
        
        if not document:
            raise DocumentNotFoundError("Document not found")
        
        # Verify ownership through project
        await self._verify_project_access(document.project_id, user_id)
        
        return document
    

    async def _enqueue_processing(self, document_id: UUID) -> None:
        """
        Add document to processing queue.

        Tries ARQ (Redis worker) first. If Redis is unavailable,
        falls back to in-process background task via asyncio so
        documents still get processed on free-tier hosts without
        a separate worker service.
        """
        try:
            pool = await get_arq_pool()
            await pool.enqueue_job(
                'process_document',
                document_id=str(document_id)
            )
            logger.info(f"Document {document_id} queued for processing (ARQ)")

        except Exception as e:
            logger.warning(
                f"ARQ queue unavailable ({e}), "
                f"falling back to in-process processing for {document_id}"
            )
            self._process_inline(document_id)

    def _process_inline(self, document_id: UUID) -> None:
        """Run document processing as a background asyncio task."""
        import asyncio
        from app.tasks.document_tasks import process_document

        async def _run():
            ctx = {"job_id": f"inline-{document_id}", "job_try": 1}
            try:
                await process_document(ctx, str(document_id))
            except Exception as exc:
                logger.error(f"Inline processing failed for {document_id}: {exc}")

        asyncio.create_task(_run())

    # ============================================================
    # UPLOAD - The Main Entry Point
    # ============================================================
    
    async def upload_document(
        self,
        file: UploadFile,
        project_id: UUID,
        user_id: UUID
    ) -> DocumentUploadResponse:
        """
        Upload and process a document.
        """
        # Step 1: Verify project access
        project = await self._verify_project_access(project_id, user_id)
        
        # Step 2: Read file content
        # This loads the entire file into memory
        # For very large files, streaming would be better
        try:
            file_content = await file.read()
        except Exception as e:
            logger.error(f"Failed to read uploaded file: {e}")
            raise DocumentServiceError("Failed to read uploaded file")
        

        # Get original filename (with fallback)
        original_filename = file.filename or "unnamed_file"
        
        # Step 3: Validate file
        validation_result = validate_file(file_content, original_filename)

        if not validation_result.is_valid:
            logger.warning(
                f"File validation failed for '{original_filename}': "
                f"{validation_result.error_message}"
            )
            raise DocumentValidationError(validation_result.error_message)
        
        # Step 4: Generate storage path
        storage_filename, sanitized_name = generate_storage_filename(original_filename)
        storage_path = build_document_path(user_id, project_id, storage_filename)

        # Step 5: Save to storage
        try:
            stored_file = await self.storage.save(
                file_content=file_content,
                destination_path=storage_path,
                content_type=validation_result.mime_type
            )
            logger.info(f"File saved to storage: {storage_path}")
        except StorageError as e:
            logger.error(f"Storage failed: {e}")
            raise DocumentServiceError(f"Failed to save file: {e}")
        
        # Step 6: Create database record
        try:
            document = await self.document_repo.create(
                project_id=project_id,
                filename=storage_filename,
                original_filename=sanitized_name,
                file_type=validation_result.file_type.value,
                file_path=storage_path,
                file_size=validation_result.file_size,
                status=DocumentStatus.PENDING.value
            )
            logger.info(f"Document record created: {document.id}")
            
        except Exception as e:
            # Rollback: delete file from storage
            logger.error(f"Database insert failed, rolling back storage: {e}")
            try:
                await self.storage.delete(storage_path)
            except Exception as cleanup_error:
                logger.error(f"Cleanup failed: {cleanup_error}")
            raise DocumentServiceError("Failed to save document record")
        
        # Step 7: Queue for processing (async, don't wait)
        await self._enqueue_processing(document.id)
        
        # Step 8: Return response
        return DocumentUploadResponse(
            document=DocumentResponse.model_validate(document),
            message="Document uploaded successfully. Processing started."
        )
    
    # ============================================================
    # READ OPERATIONS
    # ============================================================
    
    async def get_document(
        self,
        document_id: UUID,
        user_id: UUID
    ) -> DocumentResponse:
        """
        Get a single document by ID.
        
        Args:
            document_id: ID of the document
            user_id: ID of the requesting user
        
        Returns:
            DocumentResponse with document data
        
        Raises:
            DocumentNotFoundError: If document doesn't exist or access denied
        """
        document = await self._verify_document_access(document_id, user_id)
        return DocumentResponse.model_validate(document)
    

    async def list_documents(
        self,
        project_id: UUID,
        user_id: UUID,
        params: Optional[DocumentQueryParams] = None
    ) -> DocumentListResponse:
        """
        List documents in a project with optional filtering.
        """
        # Verify access
        await self._verify_project_access(project_id, user_id)
        
        # Use default params if not provided
        if params is None:
            params = DocumentQueryParams()
        
        # Get documents with filtering
        documents = await self.document_repo.get_by_project(
            project_id=project_id,
            status=params.status,
            file_type=params.file_type,
            skip=params.offset,
            limit=params.limit
        )

        # Get total count for pagination
        total = await self.document_repo.count_by_project(
            project_id=project_id,
            status=params.status
        )
        
        return DocumentListResponse(
            documents=[DocumentResponse.model_validate(doc) for doc in documents],
            total=total
        )
    

    async def get_project_document_stats(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Get document statistics for a project.
        
        Returns counts by status and file type.
        
        Args:
            project_id: ID of the project
            user_id: ID of the requesting user
        
        Returns:
            Statistics dictionary
        """
        await self._verify_project_access(project_id, user_id)
        return await self.document_repo.get_project_stats(project_id)

    # ============================================================
    # DELETE OPERATIONS
    # ============================================================
    
    async def delete_document(
        self,
        document_id: UUID,
        user_id: UUID
    ) -> bool:
        """
        Delete a document.
        
        Deletes from:
        1. Database (record)
        2. Storage (file)
        3. Vector DB (embeddings) - TODO when implemented
        
        Args:
            document_id: ID of the document
            user_id: ID of the requesting user
        
        Returns:
            True if deleted successfully
        
        Raises:
            DocumentNotFoundError: If document doesn't exist or access denied
        """   
        # Verify access and get document
        document = await self._verify_document_access(document_id, user_id)
        
        # Get file path before deletion
        file_path = document.file_path
        
        # Delete from database first
        deleted = await self.document_repo.delete(document_id)
        
        if deleted:
            # Delete from storage
            try:
                await self.storage.delete(file_path)
                logger.info(f"Document deleted: {document_id}, file: {file_path}")
            except Exception as e:
                # Log but don't fail - file might not exist
                logger.warning(f"Failed to delete file {file_path}: {e}")
            
            # TODO: Delete from vector database
            # await self.vector_store.delete_by_document(document_id)
        
        return deleted   

    async def delete_project_documents(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> int:
        """
        Delete all documents in a project.
        
        Called when a project is deleted.
        
        Args:
            project_id: ID of the project
            user_id: ID of the requesting user
        
        Returns:
            Number of documents deleted
        """  
        # Verify access
        await self._verify_project_access(project_id, user_id)
        
        # Get all documents to delete files
        documents = await self.document_repo.get_by_project(
            project_id=project_id,
            limit=10000  # Get all
        )
        
        # Delete files from storage
        for doc in documents:
            try:
                await self.storage.delete(doc.file_path)
            except Exception as e:
                logger.warning(f"Failed to delete file {doc.file_path}: {e}")
        
        # Delete directory (cleanup empty folders)
        directory_path = f"uploads/{user_id}/{project_id}"
        try:
            await self.storage.delete_directory(directory_path)
        except Exception as e:
            logger.warning(f"Failed to delete directory {directory_path}: {e}")
        
        # Delete from database
        count = await self.document_repo.delete_by_project(project_id)
        
        logger.info(f"Deleted {count} documents from project {project_id}")
        return count
    

    # ============================================================
    # STATUS OPERATIONS
    # ============================================================
    
    async def reprocess_document(
        self,
        document_id: UUID,
        user_id: UUID
    ) -> DocumentResponse:
        """
        Reprocess a document (retry failed or update processing).
        
        Use cases:
        - Retry failed processing
        - Reprocess after parser improvements
        - Reprocess after embedding model changes
        
        Args:
            document_id: ID of the document
            user_id: ID of the requesting user
        
        Returns:
            Updated DocumentResponse
        
        Raises:
            DocumentNotFoundError: If document doesn't exist or access denied
        """
        # Verify access
        document = await self._verify_document_access(document_id, user_id)
        
        # Reset to pending
        updated_doc = await self.document_repo.mark_for_reprocessing(document_id)
        
        # Queue for processing
        await self._enqueue_processing(document_id)
        
        logger.info(f"Document {document_id} queued for reprocessing")
        
        return DocumentResponse.model_validate(updated_doc)
    
    # ============================================================
    # FILE ACCESS
    # ============================================================
    
    async def get_document_content(
        self,
        document_id: UUID,
        user_id: UUID
    ) -> Tuple[bytes, str, str]:
        """
        Get document file content for download.
        """
        # Verify access
        document = await self._verify_document_access(document_id, user_id)
        
        # Get content from storage
        try:
            content = await self.storage.get(document.file_path)
        except Exception as e:
            logger.error(f"Failed to read file {document.file_path}: {e}")
            raise DocumentServiceError("Failed to retrieve document file")
        
        # Determine content type
        content_type_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "txt": "text/plain",
        }
        content_type = content_type_map.get(document.file_type, "application/octet-stream")
        
        return content, document.original_filename, content_type
    