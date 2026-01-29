"""
RAG (Retrieval-Augmented Generation) Module

Complete pipeline for document processing and retrieval.

DOCUMENT PROCESSING:
    from app.ai.rag import DocumentPipeline
    
    pipeline = DocumentPipeline()
    result = await pipeline.process_document(...)

RETRIEVAL:
    from app.ai.rag import Retriever
    
    retriever = Retriever()
    result = retriever.retrieve(query, project_id)
    context = result.get_context()
"""

# Chunker
from app.ai.rag.chunker import (
    TextChunker,
    ChunkerConfig,
    TextChunk,
    ChunkMetadata,
    chunk_document,
    count_tokens,
)

# Embedder
from app.ai.rag.embedder import (
    Embedder,
    create_embedding,
    create_embeddings,
    create_query_embedding,
    compute_similarity,
    find_most_similar,
    warmup_model,
    get_model_info,
    ChromaEmbeddingFunction,
)

# Pipeline
from app.ai.rag.pipeline import (
    DocumentPipeline,
    ProcessingResult,
    get_document_pipeline,
)

# Retriever
from app.ai.rag.retriever import (
    Retriever,
    RetrievedChunk,
    RetrievalResult,
    get_retriever,
)

__all__ = [
    # Chunker
    "TextChunker",
    "ChunkerConfig",
    "TextChunk",
    "ChunkMetadata",
    "chunk_document",
    "count_tokens",
    
    # Embedder
    "Embedder",
    "create_embedding",
    "create_embeddings",
    "create_query_embedding",
    "compute_similarity",
    "find_most_similar",
    "warmup_model",
    "get_model_info",
    "ChromaEmbeddingFunction",
    
    # Pipeline
    "DocumentPipeline",
    "ProcessingResult",
    "get_document_pipeline",
    
    # Retriever
    "Retriever",
    "RetrievedChunk",
    "RetrievalResult",
    "get_retriever",
]