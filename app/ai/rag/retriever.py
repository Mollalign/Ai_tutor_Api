"""
RAG Retriever

Retrieves relevant document chunks for user queries.

This is used during chat to find context from the user's
uploaded documents.

Context Building:
----------------
The retrieved chunks are formatted into a context string
that's included in the LLM prompt. This gives the AI
access to the user's specific course materials.
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from uuid import UUID

from app.ai.rag.embedder import create_query_embedding
from app.db.vector_store import get_vector_store, VectorStore

logger = logging.getLogger(__name__)


# ============================================================
# RESULT DATACLASSES
# ============================================================

@dataclass
class RetrievedChunk:
    """
    A single retrieved chunk with its relevance score.
    
    This is what we return from retrieval, containing
    both the content and metadata for citations.
    """
    text: str
    score: float
    document_id: str
    document_name: str
    page_number: Optional[int] = None
    chunk_index: int = 0
    
    @property
    def citation(self) -> str:
        """Format a citation string for this chunk."""
        if self.page_number:
            return f"{self.document_name}, page {self.page_number}"
        return self.document_name
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "text": self.text,
            "score": self.score,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "citation": self.citation
        }


@dataclass
class RetrievalResult:
    """
    Complete result of a retrieval operation.
    
    Contains the retrieved chunks and metadata about
    the retrieval process.
    """
    query: str
    chunks: List[RetrievedChunk] = field(default_factory=list)
    total_found: int = 0
    
    @property
    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.chunks) > 0
    
    @property
    def best_score(self) -> float:
        """Get the highest relevance score."""
        if not self.chunks:
            return 0.0
        return self.chunks[0].score
    
    def get_context(
        self,
        max_chunks: Optional[int] = None,
        include_citations: bool = True
    ) -> str:
        """
        Build context string from retrieved chunks.
        
        This is what gets included in the LLM prompt.
        
        Args:
            max_chunks: Limit number of chunks (None = all)
            include_citations: Include source references
        
        Returns:
            Formatted context string
        """
        chunks_to_use = self.chunks[:max_chunks] if max_chunks else self.chunks
        
        if not chunks_to_use:
            return ""
        
        context_parts = []
        
        for i, chunk in enumerate(chunks_to_use, 1):
            if include_citations:
                context_parts.append(
                    f"[Source {i}: {chunk.citation}]\n{chunk.text}"
                )
            else:
                context_parts.append(chunk.text)
        
        return "\n\n---\n\n".join(context_parts)
    
    def get_sources(self) -> List[Dict[str, Any]]:
        """
        Get unique sources for citation display.
        
        Returns list of unique documents referenced.
        """
        seen = set()
        sources = []
        
        for chunk in self.chunks:
            key = (chunk.document_id, chunk.page_number)
            if key not in seen:
                seen.add(key)
                sources.append({
                    "document_id": chunk.document_id,
                    "document_name": chunk.document_name,
                    "page_number": chunk.page_number,
                    "citation": chunk.citation
                })
        
        return sources


# ============================================================
# RETRIEVER CLASS
# ============================================================

class Retriever:
    """
    Retrieves relevant chunks for user queries.
    
    Main class for RAG retrieval operations.
    
    Usage:
        retriever = Retriever()
        
        result = retriever.retrieve(
            query="What is photosynthesis?",
            project_id=project_id,
            top_k=5
        )
        
        if result.has_results:
            context = result.get_context()
            sources = result.get_sources()
    """
    
    def __init__(self):
        """Initialize retriever."""
        self.vector_store = get_vector_store()
    
    def retrieve(
        self,
        query: str,
        project_id: UUID,
        top_k: int = 5,
        min_score: float = 0.3,
        document_ids: Optional[List[UUID]] = None
    ) -> RetrievalResult:
        """
        Retrieve relevant chunks for a query.
        
        Args:
            query: User's question or search query
            project_id: Project to search in
            top_k: Maximum number of chunks to retrieve
            min_score: Minimum relevance score (0-1)
            document_ids: Optional filter to specific documents
        
        Returns:
            RetrievalResult with chunks and metadata
        
        Example:
            result = retriever.retrieve(
                query="Explain the process of cellular respiration",
                project_id=project_id,
                top_k=5
            )
            
            for chunk in result.chunks:
                print(f"[{chunk.score:.2f}] {chunk.text[:100]}...")
        """
        logger.info(f"Retrieving for query: '{query[:50]}...' (top_k={top_k})")
        
        # Create query embedding
        query_embedding = create_query_embedding(query)
        
        # Search vector store
        search_results = self.vector_store.search(
            query_embedding=query_embedding,
            project_id=project_id,
            top_k=top_k,
            document_ids=document_ids,
            min_score=min_score
        )
        
        # Convert to RetrievedChunk objects
        chunks = []
        for result in search_results:
            metadata = result.get("metadata", {})
            
            chunk = RetrievedChunk(
                text=result["text"],
                score=result["score"],
                document_id=metadata.get("document_id", ""),
                document_name=metadata.get("document_name", "Unknown"),
                page_number=metadata.get("page_number"),
                chunk_index=metadata.get("chunk_index", 0)
            )
            chunks.append(chunk)
        
        logger.info(
            f"Retrieved {len(chunks)} chunks "
            f"(best score: {chunks[0].score:.3f if chunks else 0})"
        )
        
        return RetrievalResult(
            query=query,
            chunks=chunks,
            total_found=len(search_results)
        )
    
    def retrieve_for_context(
        self,
        query: str,
        project_id: UUID,
        max_tokens: int = 2000,
        top_k: int = 10,
        document_ids: Optional[List[UUID]] = None
    ) -> str:
        """
        Retrieve and format context for LLM prompt.
        
        Convenience method that retrieves chunks and builds
        context string, respecting token limits.
        
        Args:
            query: User's question
            project_id: Project to search
            max_tokens: Maximum tokens for context
            top_k: Maximum chunks to consider
            document_ids: Optional document filter
        
        Returns:
            Formatted context string
        """
        from app.ai.rag.chunker import count_tokens
        
        result = self.retrieve(
            query=query,
            project_id=project_id,
            top_k=top_k,
            document_ids=document_ids
        )
        
        if not result.has_results:
            return ""
        
        # Build context within token limit
        context_parts = []
        current_tokens = 0
        
        for chunk in result.chunks:
            chunk_tokens = count_tokens(chunk.text)
            
            # Check if adding this chunk would exceed limit
            # (add some buffer for formatting)
            if current_tokens + chunk_tokens + 50 > max_tokens:
                break
            
            context_parts.append(
                f"[Source: {chunk.citation}]\n{chunk.text}"
            )
            current_tokens += chunk_tokens + 20  # Account for citation
        
        return "\n\n---\n\n".join(context_parts)
    
    def check_relevance(
        self,
        query: str,
        project_id: UUID,
        threshold: float = 0.4
    ) -> bool:
        """
        Check if there's relevant content for a query.
        
        Quick check to determine if we should use RAG
        or fall back to general knowledge.
        
        Args:
            query: User's question
            project_id: Project to check
            threshold: Minimum score to consider relevant
        
        Returns:
            True if relevant content exists
        """
        result = self.retrieve(
            query=query,
            project_id=project_id,
            top_k=1,
            min_score=threshold
        )
        
        return result.has_results


# ============================================================
# SINGLETON INSTANCE
# ============================================================

_retriever: Optional[Retriever] = None


def get_retriever() -> Retriever:
    """Get or create retriever singleton."""
    global _retriever
    
    if _retriever is None:
        _retriever = Retriever()
    
    return _retriever