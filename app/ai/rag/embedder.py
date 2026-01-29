"""
Embedding Service

Creates vector embeddings from text using sentence-transformers.

What are Embeddings?
-------------------
Embeddings are dense vector representations of text that capture
semantic meaning. Similar texts have similar vectors.

Sentence Transformers:
---------------------
A Python library built on Hugging Face Transformers that provides
pre-trained models specifically optimized for creating sentence
and paragraph embeddings.

Models are downloaded automatically on first use and cached locally.

Batch Processing:
----------------
Creating embeddings one at a time is slow. We batch multiple texts
together for GPU/CPU efficiency. This is crucial for processing
hundreds of chunks from large documents.
"""

import logging
from typing import List, Optional, Union
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# LAZY LOADING
# ============================================================
# We don't load the model until first use because:
# 1. Model loading takes time (bad for app startup)
# 2. Model uses memory (only load if needed)
# 3. Tests might not need embeddings
# ============================================================

_model = None
_model_name = None


def _get_model():
    """
    Get or load the embedding model (lazy loading).
    
    The model is loaded on first call and cached globally.
    Subsequent calls return the cached model.
    """
    global _model, _model_name
    
    if _model is not None:
        return _model
    
    # Import here to avoid loading at module import time
    from sentence_transformers import SentenceTransformer
    from app.core.config import settings
    
    model_name = settings.EMBEDDING_MODEL
    device = settings.EMBEDDING_DEVICE
    
    logger.info(f"Loading embedding model: {model_name} on {device}")
    
    try:
        _model = SentenceTransformer(
            model_name,
            device=device
        )
        _model_name = model_name
        
        logger.info(
            f"Embedding model loaded: {model_name}, "
            f"dimension: {_model.get_sentence_embedding_dimension()}"
        )
        
        return _model
        
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        raise


def get_model_info() -> dict:
    """Get information about the loaded model."""
    model = _get_model()
    return {
        "name": _model_name,
        "dimension": model.get_sentence_embedding_dimension(),
        "max_seq_length": model.max_seq_length,
    }


# ============================================================
# EMBEDDING FUNCTIONS
# ============================================================

def create_embedding(text: str) -> List[float]:
    """
    Create embedding for a single text.
    
    For single texts, this is convenient but less efficient
    than batching. Use create_embeddings() for multiple texts.
    
    Args:
        text: Text to embed
    
    Returns:
        Embedding vector as list of floats
    
    Example:
        embedding = create_embedding("What is photosynthesis?")
        # embedding = [0.123, -0.456, 0.789, ...]
    """
    if not text or not text.strip():
        # Return zero vector for empty text
        from app.core.config import settings
        return [0.0] * settings.EMBEDDING_DIMENSION
    
    model = _get_model()
    
    # encode() returns numpy array
    embedding = model.encode(
        text,
        convert_to_numpy=True,
        normalize_embeddings=True  # L2 normalize for cosine similarity
    )
    
    return embedding.tolist()


def create_embeddings(
    texts: List[str],
    batch_size: Optional[int] = None,
    show_progress: bool = False
) -> List[List[float]]:
    """
    Create embeddings for multiple texts (batched for efficiency).
    
    This is the main function for embedding document chunks.
    Batching significantly improves throughput.
    
    Args:
        texts: List of texts to embed
        batch_size: Batch size (uses config default if None)
        show_progress: Show progress bar
    
    Returns:
        List of embedding vectors
    
    Example:
        chunks = ["Chapter 1: Introduction", "Cells are...", "Mitosis is..."]
        embeddings = create_embeddings(chunks)
        # embeddings[0] = [0.1, 0.2, ...] for "Chapter 1: Introduction"
    """
    if not texts:
        return []
    
    from app.core.config import settings
    
    if batch_size is None:
        batch_size = settings.EMBEDDING_BATCH_SIZE
    
    model = _get_model()
    
    logger.info(f"Creating embeddings for {len(texts)} texts (batch_size={batch_size})")
    
    # Handle empty texts
    # Replace empty strings with placeholder to avoid model errors
    processed_texts = []
    empty_indices = set()
    
    for i, text in enumerate(texts):
        if not text or not text.strip():
            empty_indices.add(i)
            processed_texts.append(" ")  # Placeholder
        else:
            processed_texts.append(text)
    
    # Create embeddings in batch
    embeddings = model.encode(
        processed_texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=show_progress
    )
    
    # Convert to list of lists
    result = embeddings.tolist()
    
    # Replace empty text embeddings with zero vectors
    if empty_indices:
        zero_vector = [0.0] * settings.EMBEDDING_DIMENSION
        for idx in empty_indices:
            result[idx] = zero_vector
    
    logger.info(f"Created {len(result)} embeddings")
    
    return result


def create_query_embedding(query: str) -> List[float]:
    """
    Create embedding for a search query.
    
    Some models have different encoding for queries vs documents.
    For now, this is the same as create_embedding(), but it's
    a separate function for future flexibility.
    
    Args:
        query: Search query text
    
    Returns:
        Query embedding vector
    
    Example:
        query_embedding = create_query_embedding("What is DNA?")
        results = vector_store.search(query_embedding, ...)
    """
    # For sentence-transformers, query encoding is same as document encoding
    # Some models (e.g., E5) need special prefixes for queries
    
    model = _get_model()
    
    # Check if model needs query prefix (E5 models)
    if "e5" in _model_name.lower():
        query = f"query: {query}"
    
    return create_embedding(query)


# ============================================================
# EMBEDDING CLASS (Alternative OOP Interface)
# ============================================================

class Embedder:
    """
    Object-oriented interface for embedding operations.
    
    Provides the same functionality as module functions
    but with an object-oriented interface.
    
    Usage:
        embedder = Embedder()
        
        # Single text
        embedding = embedder.embed("Hello world")
        
        # Multiple texts
        embeddings = embedder.embed_batch(["Text 1", "Text 2"])
        
        # Query
        query_embedding = embedder.embed_query("Search query")
    """
    
    def __init__(self):
        """Initialize embedder (loads model on first use)."""
        self._model = None
    
    @property
    def model(self):
        """Lazy load model."""
        if self._model is None:
            self._model = _get_model()
        return self._model
    
    @property
    def dimension(self) -> int:
        """Get embedding dimension."""
        return self.model.get_sentence_embedding_dimension()
    
    @property
    def model_name(self) -> str:
        """Get model name."""
        return _model_name or "not loaded"
    
    def embed(self, text: str) -> List[float]:
        """Create embedding for single text."""
        return create_embedding(text)
    
    def embed_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress: bool = False
    ) -> List[List[float]]:
        """Create embeddings for multiple texts."""
        return create_embeddings(texts, batch_size, show_progress)
    
    def embed_query(self, query: str) -> List[float]:
        """Create embedding for search query."""
        return create_query_embedding(query)


# ============================================================
# CHROMADB EMBEDDING FUNCTION ADAPTER
# ============================================================
# ChromaDB can use a custom embedding function
# This adapter makes our embedder compatible with ChromaDB

class ChromaEmbeddingFunction:
    """
    Adapter to use our embedder as ChromaDB embedding function.
    
    ChromaDB expects an embedding function with __call__ method
    that takes a list of texts and returns a list of embeddings.
    
    Usage:
        from app.ai.rag.embedder import ChromaEmbeddingFunction
        
        collection = client.get_or_create_collection(
            name="my_collection",
            embedding_function=ChromaEmbeddingFunction()
        )
        
        # Now ChromaDB will auto-embed when you add texts
        collection.add(
            ids=["1", "2"],
            documents=["Text 1", "Text 2"]
            # embeddings auto-generated!
        )
    """
    
    def __init__(self):
        """Initialize (model loaded on first use)."""
        pass
    
    def __call__(self, texts: List[str]) -> List[List[float]]:
        """
        Create embeddings for texts.
        
        This is called by ChromaDB when embeddings are needed.
        """
        return create_embeddings(texts)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def compute_similarity(
    embedding1: List[float],
    embedding2: List[float]
) -> float:
    """
    Compute cosine similarity between two embeddings.
    
    Cosine similarity measures the angle between vectors.
    - 1.0 = identical direction (most similar)
    - 0.0 = orthogonal (unrelated)
    - -1.0 = opposite direction (most different)
    
    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector
    
    Returns:
        Cosine similarity score (-1 to 1)
    
    Example:
        sim = compute_similarity(
            embed("The cat sat"),
            embed("A feline rested")
        )
        # sim ≈ 0.85 (high similarity)
    """
    v1 = np.array(embedding1)
    v2 = np.array(embedding2)
    
    # Cosine similarity = dot product of normalized vectors
    # Our embeddings are already normalized, so just dot product
    return float(np.dot(v1, v2))


def find_most_similar(
    query_embedding: List[float],
    candidate_embeddings: List[List[float]],
    top_k: int = 5
) -> List[tuple]:
    """
    Find most similar embeddings to query.
    
    Simple in-memory similarity search.
    For large-scale search, use VectorStore.
    
    Args:
        query_embedding: Query vector
        candidate_embeddings: List of candidate vectors
        top_k: Number of results to return
    
    Returns:
        List of (index, similarity_score) tuples, sorted by similarity
    
    Example:
        results = find_most_similar(query_emb, chunk_embs, top_k=3)
        for idx, score in results:
            print(f"Chunk {idx}: {score:.3f}")
    """
    query = np.array(query_embedding)
    candidates = np.array(candidate_embeddings)
    
    # Compute all similarities at once
    similarities = np.dot(candidates, query)
    
    # Get top-k indices
    top_indices = np.argsort(similarities)[::-1][:top_k]
    
    return [(int(idx), float(similarities[idx])) for idx in top_indices]


# ============================================================
# MODEL WARMUP (Optional)
# ============================================================

def warmup_model() -> dict:
    """
    Pre-load the embedding model.
    
    Call this during app startup to avoid cold-start latency
    on first embedding request.
    
    Returns:
        Model info dictionary
    """
    logger.info("Warming up embedding model...")
    
    # This loads the model
    info = get_model_info()
    
    # Create a test embedding to fully initialize
    _ = create_embedding("warmup test")
    
    logger.info(f"Embedding model ready: {info['name']}")
    return info