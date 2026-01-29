"""
Document Processing Tasks

Background tasks for processing uploaded documents.
"""

import logging
from typing import Any, Dict
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.models.document import Document
from app.schemas.document import DocumentStatus
from app.storage import get_storage
from app.ai.rag.pipeline import DocumentPipeline, get_document_pipeline

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE SESSION HELPER
# ============================================================

async def get_worker_db_session() -> AsyncSession:
    """Create a database session for worker use."""
    return AsyncSessionLocal()


# ============================================================
# DOCUMENT PROCESSING TASK
# ============================================================

async def process_document(
    ctx: Dict[str, Any],
    document_id: str
) -> Dict[str, Any]:
    """
    Process an uploaded document.
    
    This task is called by ARQ worker to:
    1. Parse the document (extract text)
    2. Chunk the text (split into segments)
    3. Create embeddings (vectors)
    4. Store in vector database
    
    Args:
        ctx: ARQ context (job_id, redis, etc.)
        document_id: UUID of the document to process
    
    Returns:
        Dict with processing result
    """
    job_id = ctx.get('job_id', 'unknown')
    job_try = ctx.get('job_try', 1)
    
    logger.info(
        f"Processing document {document_id} "
        f"(job: {job_id}, attempt: {job_try})"
    )
    
    # Validate document ID
    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        logger.error(f"Invalid document ID: {document_id}")
        return {"success": False, "error": "Invalid document ID"}
    
    # Get database session
    session = await get_worker_db_session()
    
    try:
        # ================================================
        # STEP 1: Get document and verify it exists
        # ================================================
        document = await _get_document(session, doc_uuid)
        
        if not document:
            logger.error(f"Document not found: {document_id}")
            return {"success": False, "error": "Document not found"}
        
        # Update status to PROCESSING
        await _update_status(session, document, DocumentStatus.PROCESSING)
        logger.info(f"Document {document_id}: status → PROCESSING")
        
        # ================================================
        # STEP 2: Read file from storage
        # ================================================
        storage = get_storage()
        
        try:
            file_content = await storage.get(document.file_path)
            logger.info(
                f"Document {document_id}: read {len(file_content)} bytes"
            )
        except Exception as e:
            raise ProcessingError(f"Failed to read file: {e}")
        
        # ================================================
        # STEP 3: Process through pipeline
        # ================================================
        # Get the processing pipeline
        pipeline = get_document_pipeline()
        
        # If reprocessing, delete existing chunks first
        if document.chunk_count > 0:
            logger.info(f"Deleting existing chunks for reprocessing")
            pipeline.delete_document_chunks(
                document_id=doc_uuid,
                project_id=document.project_id
            )
        
        # Run the full processing pipeline
        result = await pipeline.process_document(
            document_id=doc_uuid,
            file_content=file_content,
            file_type=document.file_type,
            filename=document.original_filename,
            project_id=document.project_id
        )
        
        # ================================================
        # STEP 4: Update document status based on result
        # ================================================
        if result.success:
            await _update_status(
                session,
                document,
                DocumentStatus.READY,
                chunk_count=result.chunk_count
            )
            
            logger.info(
                f"Document {document_id}: processing complete, "
                f"{result.chunk_count} chunks created"
            )
            
            return {
                "success": True,
                "document_id": document_id,
                "chunks_created": result.chunk_count,
                "pages_parsed": result.pages_parsed,
                "total_tokens": result.total_tokens
            }
        else:
            await _update_status(
                session,
                document,
                DocumentStatus.FAILED,
                error_message=result.error
            )
            
            logger.error(f"Document {document_id}: processing failed - {result.error}")
            
            return {
                "success": False,
                "document_id": document_id,
                "error": result.error
            }
        
    except ProcessingError as e:
        logger.error(f"Document {document_id} processing failed: {e}")
        await _mark_failed(session, doc_uuid, str(e))
        return {"success": False, "document_id": document_id, "error": str(e)}
        
    except Exception as e:
        logger.exception(f"Document {document_id} unexpected error: {e}")
        await _mark_failed(session, doc_uuid, f"Unexpected error: {str(e)}")
        return {"success": False, "document_id": document_id, "error": str(e)}
        
    finally:
        await session.close()


# ============================================================
# HELPER CLASSES AND FUNCTIONS
# ============================================================

class ProcessingError(Exception):
    """Raised when document processing fails."""
    pass


async def _get_document(session: AsyncSession, document_id: UUID) -> Document:
    """Get document from database."""
    result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    return result.scalar_one_or_none()


async def _update_status(
    session: AsyncSession,
    document: Document,
    status: DocumentStatus,
    chunk_count: int = None,
    error_message: str = None
) -> None:
    """Update document status in database."""
    document.status = status.value
    
    if status == DocumentStatus.READY:
        document.processed_at = datetime.now(timezone.utc)
        document.error_message = None
        if chunk_count is not None:
            document.chunk_count = chunk_count
            
    elif status == DocumentStatus.FAILED:
        document.processed_at = datetime.now(timezone.utc)
        document.error_message = error_message
        
    elif status == DocumentStatus.PROCESSING:
        document.error_message = None
    
    await session.commit()
    await session.refresh(document)


async def _mark_failed(
    session: AsyncSession, 
    document_id: UUID, 
    error: str
) -> None:
    """Mark document as failed."""
    try:
        document = await _get_document(session, document_id)
        if document:
            await _update_status(
                session, 
                document, 
                DocumentStatus.FAILED, 
                error_message=error
            )
    except Exception as e:
        logger.error(f"Failed to mark document as failed: {e}")