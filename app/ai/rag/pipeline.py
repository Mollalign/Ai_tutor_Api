"""
Document Processing Pipeline

Orchestrates the complete document processing flow:
Parse → Chunk → Embed → Store

This module provides a clean interface for processing documents,
hiding the complexity of individual components.

Design Pattern: Facade
---------------------
The pipeline acts as a facade that simplifies the complex
subsystem of parsers, chunkers, embedders, and vector store.

Usage:
------
    from app.ai.rag.pipeline import DocumentPipeline
    
    pipeline = DocumentPipeline()
    result = await pipeline.process_document(
        document_id=doc.id,
        file_content=content,
        file_type="pdf",
        filename="lecture.pdf",
        project_id=project.id
    )
    
    if result.success:
        print(f"Created {result.chunk_count} chunks")
"""

import logging
from typing import Optional, List
from dataclasses import dataclass
from uuid import UUID

from app.ai.parsers import parse_document, ParsedDocument
from app.ai.rag.chunker import TextChunker, ChunkerConfig, TextChunk
from app.ai.rag.embedder import create_embeddings
from app.db.vector_store import get_vector_store, VectorStore

logger = logging.getLogger(__name__)


# ============================================================
# RESULT DATACLASS
# ============================================================

@dataclass
class ProcessingResult:
    """
    Result of document processing.
    
    Contains all information about the processing outcome,
    whether successful or failed.
    """
    success: bool
    document_id: UUID
    chunk_count: int = 0
    total_tokens: int = 0
    error: Optional[str] = None
    
    # Processing details
    pages_parsed: int = 0
    text_length: int = 0
    
    @classmethod
    def from_error(cls, document_id: UUID, error: str) -> "ProcessingResult":
        """Create a failed result."""
        return cls(
            success=False,
            document_id=document_id,
            error=error
        )


# ============================================================
# DOCUMENT PROCESSING PIPELINE
# ============================================================

class DocumentPipeline:
    """
    Orchestrates document processing: Parse → Chunk → Embed → Store.
    
    This is the main class for processing uploaded documents.
    It coordinates all the components and handles errors gracefully.
    
    Attributes:
        chunker: TextChunker instance
        vector_store: VectorStore instance
    """
    
    def __init__(
        self,
        chunk_size: int = 400,
        chunk_overlap: int = 50
    ):
        """
        Initialize the pipeline.
        
        Args:
            chunk_size: Target tokens per chunk
            chunk_overlap: Overlap between chunks
        """
        self.chunker = TextChunker(
            ChunkerConfig(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
        )
        self.vector_store = get_vector_store()
        
        logger.info(
            f"DocumentPipeline initialized: "
            f"chunk_size={chunk_size}, overlap={chunk_overlap}"
        )
    
    async def process_document(
        self,
        document_id: UUID,
        file_content: bytes,
        file_type: str,
        filename: str,
        project_id: UUID,
    ) -> ProcessingResult:
        """
        Process a document through the complete pipeline.
        
        Steps:
        1. Parse document (extract text)
        2. Chunk text (split into segments)
        3. Create embeddings
        4. Store in vector database
        
        Args:
            document_id: UUID of the document being processed
            file_content: Raw file bytes
            file_type: File type (pdf, docx, pptx, txt)
            filename: Original filename
            project_id: Project the document belongs to
        
        Returns:
            ProcessingResult with success/failure and statistics
        """
        logger.info(
            f"Processing document {document_id}: "
            f"{filename} ({file_type}, {len(file_content)} bytes)"
        )
        
        try:
            # ================================================
            # STEP 1: Parse Document
            # ================================================
            parsed = self._parse_document(file_content, file_type, filename)
            
            if not parsed.success:
                return ProcessingResult.from_error(
                    document_id,
                    f"Parsing failed: {parsed.error}"
                )
            
            if not parsed.text.strip():
                return ProcessingResult.from_error(
                    document_id,
                    "No text content extracted from document"
                )
            
            logger.info(
                f"Document {document_id}: parsed {parsed.page_count} pages, "
                f"{len(parsed.text)} characters"
            )
            
            # ================================================
            # STEP 2: Chunk Text
            # ================================================
            chunks = self._chunk_document(parsed, document_id, filename)
            
            if not chunks:
                return ProcessingResult.from_error(
                    document_id,
                    "No chunks created from document"
                )
            
            logger.info(f"Document {document_id}: created {len(chunks)} chunks")
            
            # ================================================
            # STEP 3: Create Embeddings
            # ================================================
            embeddings = self._create_embeddings(chunks)
            
            logger.info(f"Document {document_id}: created {len(embeddings)} embeddings")
            
            # ================================================
            # STEP 4: Store in Vector Database
            # ================================================
            stored_count = self._store_chunks(chunks, embeddings, project_id)
            
            logger.info(
                f"Document {document_id}: stored {stored_count} chunks in vector DB"
            )
            
            # ================================================
            # Return Success Result
            # ================================================
            total_tokens = sum(chunk.tokens for chunk in chunks)
            
            return ProcessingResult(
                success=True,
                document_id=document_id,
                chunk_count=stored_count,
                total_tokens=total_tokens,
                pages_parsed=parsed.page_count,
                text_length=len(parsed.text)
            )
            
        except Exception as e:
            logger.exception(f"Document {document_id} processing failed: {e}")
            return ProcessingResult.from_error(document_id, str(e))
    
    def _parse_document(
        self,
        content: bytes,
        file_type: str,
        filename: str
    ) -> ParsedDocument:
        """Parse document using appropriate parser."""
        return parse_document(content, filename, file_type)
    
    def _chunk_document(
        self,
        parsed: ParsedDocument,
        document_id: UUID,
        filename: str
    ) -> List[TextChunk]:
        """
        Chunk parsed document.
        
        Uses page-aware chunking if pages are available,
        otherwise chunks the full text.
        """
        if parsed.pages and len(parsed.pages) > 1:
            # Use page-aware chunking
            pages_data = [
                {
                    "page_number": page.page_number,
                    "text": page.text
                }
                for page in parsed.pages
                if page.text.strip()
            ]
            
            return self.chunker.chunk_pages(
                pages=pages_data,
                document_id=document_id,
                document_name=filename
            )
        else:
            # Chunk full text
            return self.chunker.chunk_text(
                text=parsed.text,
                document_id=document_id,
                document_name=filename
            )
    
    def _create_embeddings(self, chunks: List[TextChunk]) -> List[List[float]]:
        """Create embeddings for all chunks."""
        texts = [chunk.text for chunk in chunks]
        return create_embeddings(texts, show_progress=len(texts) > 50)
    
    def _store_chunks(
        self,
        chunks: List[TextChunk],
        embeddings: List[List[float]],
        project_id: UUID
    ) -> int:
        """Store chunks with embeddings in vector database."""
        return self.vector_store.add_chunks(
            chunks=chunks,
            embeddings=embeddings,
            project_id=project_id
        )
    
    # ============================================================
    # CLEANUP METHODS
    # ============================================================
    
    def delete_document_chunks(
        self,
        document_id: UUID,
        project_id: UUID
    ) -> int:
        """
        Delete all chunks for a document.
        
        Called when a document is deleted or reprocessed.
        
        Args:
            document_id: Document UUID
            project_id: Project UUID
        
        Returns:
            Number of chunks deleted
        """
        return self.vector_store.delete_by_document(document_id, project_id)
    
    def delete_project_chunks(self, project_id: UUID) -> bool:
        """
        Delete all chunks for a project.
        
        Called when a project is deleted.
        
        Args:
            project_id: Project UUID
        
        Returns:
            True if collection deleted
        """
        return self.vector_store.delete_collection(project_id)


# ============================================================
# SINGLETON INSTANCE
# ============================================================

_pipeline: Optional[DocumentPipeline] = None


def get_document_pipeline() -> DocumentPipeline:
    """Get or create document pipeline singleton."""
    global _pipeline
    
    if _pipeline is None:
        _pipeline = DocumentPipeline()
    
    return _pipeline