"""
Document Processing Tasks

Background tasks for processing uploaded documents.

Processing Pipeline:
-------------------
1. STATUS UPDATE: Mark document as "processing"
2. FILE READ: Get file content from storage
3. PARSE: Extract text based on file type
4. CHUNK: Split text into manageable segments
5. EMBED: Create vector embeddings for each chunk
6. STORE: Save embeddings to vector database
7. FINALIZE: Update document status to "ready"

Error Handling:
--------------
- All errors are caught and logged
- Document status is set to "failed" with error message
- Tasks can be retried via the reprocess endpoint

Why Separate Process?
--------------------
- Long-running tasks don't block API responses
- Can scale workers independently from API servers
- Failures don't crash the main application
- Can process multiple documents in parallel
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

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE SESSION HELPER
# ============================================================
# Workers don't have FastAPI's dependency injection
# We need to create our own database sessions

async def get_worker_db_session() -> AsyncSession:
    """
    Create a database session for worker use.
    
    Unlike FastAPI endpoints, workers don't have dependency injection.
    We manually create and manage sessions.
    
    Important: Always close the session when done!
    
    Usage:
        session = await get_worker_db_session()
        try:
            # do work
            await session.commit()
        finally:
            await session.close()
    """
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
    
    This is the main background task that:
    1. Parses the document to extract text
    2. Chunks the text for vector storage
    3. Creates embeddings
    4. Stores in vector database
    
    Args:
        ctx: ARQ context containing:
            - redis: Redis connection
            - job_id: Unique job identifier
            - job_try: Retry attempt number (1, 2, 3...)
        document_id: UUID of the document to process (as string)
    
    Returns:
        Dict with processing result:
            - success: bool
            - document_id: str
            - chunks_created: int (if successful)
            - error: str (if failed)
    
    ARQ Task Contract:
    -----------------
    - Task functions are async
    - First parameter is always `ctx` (ARQ context)
    - Additional parameters come from enqueue_job() call
    - Return value is stored in Redis (for result retrieval)
    - Exceptions are caught by ARQ and can trigger retries
    """
    job_id = ctx.get('job_id', 'unknown')
    job_try = ctx.get('job_try', 1)
    
    logger.info(
        f"Processing document {document_id} "
        f"(job: {job_id}, attempt: {job_try})"
    )
    
    # Convert string to UUID
    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        logger.error(f"Invalid document ID: {document_id}")
        return {"success": False, "error": "Invalid document ID"}
    
    # Get database session
    session = await get_worker_db_session()
    
    try:
        # ================================================
        # STEP 1: Get document and update status
        # ================================================
        document = await _get_document(session, doc_uuid)
        
        if not document:
            logger.error(f"Document not found: {document_id}")
            return {"success": False, "error": "Document not found"}
        
        # Update status to PROCESSING
        await _update_status(
            session, 
            document, 
            DocumentStatus.PROCESSING
        )
        
        logger.info(f"Document {document_id}: status → PROCESSING")
        
        # ================================================
        # STEP 2: Read file from storage
        # ================================================
        storage = get_storage()
        
        try:
            file_content = await storage.get(document.file_path)
            logger.info(
                f"Document {document_id}: read {len(file_content)} bytes "
                f"from {document.file_path}"
            )
        except Exception as e:
            raise ProcessingError(f"Failed to read file: {e}")
        
        # ================================================
        # STEP 3: Parse document (extract text)
        # ================================================
        # TODO: Implement actual parsing in Phase 3
        # For now, we'll use a placeholder
        
        text_content = await _parse_document(
            file_content, 
            document.file_type,
            document.original_filename
        )
        
        logger.info(
            f"Document {document_id}: extracted {len(text_content)} characters"
        )
        
        # ================================================
        # STEP 4: Chunk text
        # ================================================
        # TODO: Implement chunking in Phase 3
        # For now, create placeholder chunks
        
        chunks = await _chunk_text(text_content)
        chunk_count = len(chunks)
        
        logger.info(f"Document {document_id}: created {chunk_count} chunks")
        
        # ================================================
        # STEP 5: Create embeddings
        # ================================================
        # TODO: Implement embedding in Phase 3
        # For now, skip this step
        
        # embeddings = await _create_embeddings(chunks)
        
        # ================================================
        # STEP 6: Store in vector database
        # ================================================
        # TODO: Implement vector storage in Phase 3
        # For now, skip this step
        
        # await _store_embeddings(document_id, chunks, embeddings)
        
        # ================================================
        # STEP 7: Update status to READY
        # ================================================
        await _update_status(
            session,
            document,
            DocumentStatus.READY,
            chunk_count=chunk_count
        )
        
        logger.info(
            f"Document {document_id}: processing complete, "
            f"{chunk_count} chunks created"
        )
        
        return {
            "success": True,
            "document_id": document_id,
            "chunks_created": chunk_count
        }
        
    except ProcessingError as e:
        # Known processing error
        logger.error(f"Document {document_id} processing failed: {e}")
        await _mark_failed(session, doc_uuid, str(e))
        return {"success": False, "document_id": document_id, "error": str(e)}
        
    except Exception as e:
        # Unexpected error
        logger.exception(f"Document {document_id} unexpected error: {e}")
        await _mark_failed(session, doc_uuid, f"Unexpected error: {str(e)}")
        return {"success": False, "document_id": document_id, "error": str(e)}
        
    finally:
        # Always close the session
        await session.close()


# ============================================================
# HELPER FUNCTIONS
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


# ============================================================
# PROCESSING FUNCTIONS (PLACEHOLDERS)
# ============================================================
# These will be replaced with real implementations in Phase 3

async def _parse_document(
    content: bytes, 
    file_type: str,
    filename: str
) -> str:
    """
    Parse document and extract text.
    
    PLACEHOLDER: Will be replaced with actual parsers:
    - PDF: pypdf or pdfplumber
    - DOCX: python-docx
    - PPTX: python-pptx
    - TXT: direct decode
    
    Args:
        content: Raw file bytes
        file_type: Type of file (pdf, docx, pptx, txt)
        filename: Original filename for logging
    
    Returns:
        Extracted text content
    """
    logger.info(f"Parsing {file_type} file: {filename}")
    
    if file_type == "txt":
        # Text files can be decoded directly
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return content.decode('latin-1')
            except UnicodeDecodeError:
                raise ProcessingError("Could not decode text file")
    
    # For other types, return placeholder text
    # TODO: Implement real parsers
    return f"""
    [PLACEHOLDER: Document parsing not yet implemented]
    
    File: {filename}
    Type: {file_type}
    Size: {len(content)} bytes
    
    This is placeholder text that will be replaced when 
    document parsers are implemented in Phase 3.
    
    The actual implementation will:
    - Extract all text from the document
    - Preserve structure (headings, paragraphs)
    - Extract metadata (title, author, etc.)
    """


async def _chunk_text(text: str, chunk_size: int = 1000) -> list[str]:
    """
    Split text into chunks for vector storage.
    
    PLACEHOLDER: Will be replaced with intelligent chunking:
    - Respect sentence boundaries
    - Overlap between chunks
    - Semantic chunking
    
    Args:
        text: Full text to chunk
        chunk_size: Approximate size of each chunk
    
    Returns:
        List of text chunks
    """
    # Simple placeholder chunking
    # Real implementation will be smarter
    
    if not text:
        return []
    
    chunks = []
    current_pos = 0
    
    while current_pos < len(text):
        # Get chunk of approximate size
        end_pos = min(current_pos + chunk_size, len(text))
        
        # Try to break at sentence boundary
        if end_pos < len(text):
            # Look for sentence end (.!?) near chunk boundary
            for char in '.!?\n':
                last_sentence = text.rfind(char, current_pos, end_pos)
                if last_sentence > current_pos:
                    end_pos = last_sentence + 1
                    break
        
        chunk = text[current_pos:end_pos].strip()
        if chunk:
            chunks.append(chunk)
        
        current_pos = end_pos
    
    return chunks