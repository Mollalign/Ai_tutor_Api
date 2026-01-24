"""
Document Repository

Data access layer for Document model.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.document import Document
from app.schemas.document import DocumentStatus, FileType


class DocumentRepository(BaseRepository[Document]):
    """
    Repository for Document model.
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize with database session.
        
        Args:
            db: Async SQLAlchemy session from dependency injection
        """
        super().__init__(Document, db)
    
    # ============================================================
    # QUERY METHODS - Reading Data
    # ============================================================
    
    async def get_by_project(
        self,
        project_id: UUID,
        status: Optional[DocumentStatus] = None,
        file_type: Optional[FileType] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Document]:
        """
        Get all documents for a project with optional filtering.
        
        This is the main query method for listing documents.
        Supports filtering by status and file type.
        """
        # Build the query step by step
        # This is more readable than one giant statement
        
        # Start with base query
        stmt = select(self.model).where(
            self.model.project_id == project_id
        )
        
        # Add optional filters
        if status is not None:
            # Compare with enum value for database compatibility
            stmt = stmt.where(self.model.status == status.value)
        
        if file_type is not None:
            stmt = stmt.where(self.model.file_type == file_type.value)
        
        # Order by newest first (most useful for users)
        stmt = stmt.order_by(self.model.created_at.desc())
        
        # Apply pagination
        stmt = stmt.offset(skip).limit(limit)
        
        # Execute and return results
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_by_path(self, file_path: str) -> Optional[Document]:
        """
        Get document by its storage path.
        
        Useful for:
        - Checking if a file path is already in use
        - Finding document record from storage path
        
        Args:
            file_path: Storage path of the file
        
        Returns:
            Document if found, None otherwise
        """
        stmt = select(self.model).where(self.model.file_path == file_path)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_pending_documents(self, limit: int = 10) -> List[Document]:
        """
        Get documents waiting to be processed.
        
        Used by background workers to find work.
        Returns oldest pending documents first (FIFO - First In First Out).
        
        Args:
            limit: Maximum documents to return
        
        Returns:
            List of pending documents, oldest first
        """
        stmt = (
            select(self.model)
            .where(self.model.status == DocumentStatus.PENDING.value)
            .order_by(self.model.created_at.asc())  # Oldest first
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_failed_documents(
        self,
        project_id: Optional[UUID] = None,
        limit: int = 100
    ) -> List[Document]:
        """
        Get documents that failed processing.
        
        Useful for:
        - Admin dashboard showing failed documents
        - Retry logic
        - Error monitoring
        
        Args:
            project_id: Optional filter by project
            limit: Maximum results
        
        Returns:
            List of failed documents
        """
        stmt = select(self.model).where(
            self.model.status == DocumentStatus.FAILED.value
        )
        
        if project_id is not None:
            stmt = stmt.where(self.model.project_id == project_id)
        
        stmt = stmt.order_by(self.model.created_at.desc()).limit(limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    # ============================================================
    # COUNT METHODS - For Pagination and Statistics
    # ============================================================
    
    async def count_by_project(
        self,
        project_id: UUID,
        status: Optional[DocumentStatus] = None
    ) -> int:
        """
        Count documents in a project.
        
        Used for:
        - Pagination (total count)
        - Project statistics
        - Dashboard displays
        
        Args:
            project_id: ID of the project
            status: Optional filter by status
        
        Returns:
            Count of documents
        
        Example:
            total = await repo.count_by_project(project_id)
            ready = await repo.count_by_project(project_id, DocumentStatus.READY)
        """
        stmt = select(func.count(self.model.id)).where(
            self.model.project_id == project_id
        )
        
        if status is not None:
            stmt = stmt.where(self.model.status == status.value)
        
        result = await self.db.execute(stmt)
        return result.scalar() or 0
    
    async def get_project_stats(self, project_id: UUID) -> dict:
        """
        Get document statistics for a project.
        
        Returns counts grouped by status and file type.
        Useful for project dashboard displays.
        
        Args:
            project_id: ID of the project
        
        Returns:
            Dictionary with statistics:
            {
                "total": 10,
                "by_status": {"ready": 5, "pending": 3, "failed": 2},
                "by_type": {"pdf": 6, "docx": 4},
                "total_size": 52428800  # bytes
            }
        """
        # Get counts by status
        status_stmt = (
            select(
                self.model.status,
                func.count(self.model.id)
            )
            .where(self.model.project_id == project_id)
            .group_by(self.model.status)
        )
        status_result = await self.db.execute(status_stmt)
        by_status = {row[0]: row[1] for row in status_result.all()}
        
        # Get counts by file type
        type_stmt = (
            select(
                self.model.file_type,
                func.count(self.model.id)
            )
            .where(self.model.project_id == project_id)
            .group_by(self.model.file_type)
        )
        type_result = await self.db.execute(type_stmt)
        by_type = {row[0]: row[1] for row in type_result.all()}
        
        # Get total size
        size_stmt = (
            select(func.sum(self.model.file_size))
            .where(self.model.project_id == project_id)
        )
        size_result = await self.db.execute(size_stmt)
        total_size = size_result.scalar() or 0
        
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "by_type": by_type,
            "total_size": total_size
        }
    
    # ============================================================
    # STATUS UPDATE METHODS - For Background Processing
    # ============================================================
    
    async def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        error_message: Optional[str] = None,
        chunk_count: Optional[int] = None
    ) -> Optional[Document]:
        """
        Update document processing status.
        
        This is the primary method used by background workers
        to update document status as processing progresses.
        
        Args:
            document_id: ID of the document
            status: New status
            error_message: Error details if status is FAILED
            chunk_count: Number of chunks if status is READY
        
        Returns:
            Updated document or None if not found
        
        Example:
            # Mark as processing
            await repo.update_status(doc_id, DocumentStatus.PROCESSING)
            
            # Mark as ready with chunk count
            await repo.update_status(
                doc_id, 
                DocumentStatus.READY,
                chunk_count=42
            )
            
            # Mark as failed with error
            await repo.update_status(
                doc_id,
                DocumentStatus.FAILED,
                error_message="PDF parsing failed: corrupted file"
            )
        """
        document = await self.get_by_id(document_id)
        if not document:
            return None
        
        # Update status
        document.status = status.value
        
        # Handle status-specific updates
        if status == DocumentStatus.READY:
            document.processed_at = datetime.now(timezone.utc)
            document.error_message = None  # Clear any previous error
            if chunk_count is not None:
                document.chunk_count = chunk_count
                
        elif status == DocumentStatus.FAILED:
            document.processed_at = datetime.now(timezone.utc)
            document.error_message = error_message
            
        elif status == DocumentStatus.PROCESSING:
            document.error_message = None  # Clear previous error on retry
        
        await self.db.commit()
        await self.db.refresh(document)
        return document
    
    async def mark_for_reprocessing(self, document_id: UUID) -> Optional[Document]:
        """
        Reset a document for reprocessing.
        
        Used when:
        - User requests retry of failed document
        - Parser is updated and documents need re-parsing
        - Embedding model changes
        
        Resets:
        - Status to PENDING
        - Error message to None
        - Chunk count to 0
        - Processed_at to None
        
        Args:
            document_id: ID of the document
        
        Returns:
            Updated document or None if not found
        """
        document = await self.get_by_id(document_id)
        if not document:
            return None
        
        document.status = DocumentStatus.PENDING.value
        document.error_message = None
        document.chunk_count = 0
        document.processed_at = None
        
        await self.db.commit()
        await self.db.refresh(document)
        return document
    
    # ============================================================
    # DELETE METHODS
    # ============================================================
    
    async def delete_by_project(self, project_id: UUID) -> int:
        """
        Delete all documents for a project.
        
        Called when a project is deleted.
        Returns count of deleted documents for logging.
        
        Note: This only deletes database records.
        The service layer must also delete files from storage!
        
        Args:
            project_id: ID of the project
        
        Returns:
            Number of documents deleted
        """
        # First count for return value
        count = await self.count_by_project(project_id)
        
        if count == 0:
            return 0
        
        # Get all documents (need file paths for storage cleanup)
        # This is handled by the service layer, but we return count
        documents = await self.get_by_project(project_id, limit=count)
        
        for doc in documents:
            await self.db.delete(doc)
        
        await self.db.commit()
        return count
    
    # ============================================================
    # VALIDATION METHODS
    # ============================================================
    
    async def exists_in_project(
        self,
        project_id: UUID,
        original_filename: str
    ) -> bool:
        """
        Check if a file with the same name exists in project.
        
        Used to warn users about duplicate uploads.
        We don't prevent duplicates, but we can inform users.
        
        Args:
            project_id: ID of the project
            original_filename: Original filename to check
        
        Returns:
            True if a document with this name exists
        """
        stmt = select(func.count(self.model.id)).where(
            and_(
                self.model.project_id == project_id,
                self.model.original_filename == original_filename
            )
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0
        return count > 0