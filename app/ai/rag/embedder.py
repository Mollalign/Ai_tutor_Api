"""
Embedding Service

Creates vector embeddings from text using Google Gemini API.

Google Gemini Embeddings:
------------------------
- Model: text-embedding-004
- Dimension: 768 (default)
- Free tier with generous limits
- No local model loading required (API-based)

This approach is ideal for free-tier cloud deployment (Render, Railway, etc.)
since it requires zero GPU/CPU-heavy model loading and minimal RAM.
"""

import logging
from typing import List, Optional

from google import genai

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Get or create the Gemini API client (singleton)."""
    global _client

    if _client is not None:
        return _client

    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is required for embeddings. "
            "Get one at: https://aistudio.google.com/apikey"
        )

    _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    logger.info("Gemini embedding client initialized")
    return _client


def get_model_info() -> dict:
    """Get information about the embedding model."""
    return {
        "name": settings.EMBEDDING_MODEL,
        "dimension": settings.EMBEDDING_DIMENSION,
        "provider": "google-gemini",
    }


# ============================================================
# EMBEDDING FUNCTIONS
# ============================================================

def create_embedding(text: str) -> List[float]:
    """
    Create embedding for a single text.

    Args:
        text: Text to embed

    Returns:
        Embedding vector as list of floats
    """
    if not text or not text.strip():
        return [0.0] * settings.EMBEDDING_DIMENSION

    client = _get_client()

    from google.genai import types

    result = client.models.embed_content(
        model=settings.EMBEDDING_MODEL,
        contents=[text],
        config=types.EmbedContentConfig(
            output_dimensionality=settings.EMBEDDING_DIMENSION,
        ),
    )

    return list(result.embeddings[0].values)


def create_embeddings(
    texts: List[str],
    batch_size: Optional[int] = None,
    show_progress: bool = False,
) -> List[List[float]]:
    """
    Create embeddings for multiple texts with automatic batching.

    The Gemini API has a limit of ~100 texts per request,
    so we batch accordingly.

    Args:
        texts: List of texts to embed
        batch_size: Texts per API call (default from config)
        show_progress: Unused, kept for interface compatibility

    Returns:
        List of embedding vectors
    """
    if not texts:
        return []

    if batch_size is None:
        batch_size = settings.EMBEDDING_BATCH_SIZE

    client = _get_client()
    all_embeddings: List[List[float]] = []

    # Replace empty texts with a placeholder
    processed_texts = []
    empty_indices = set()

    for i, text in enumerate(texts):
        if not text or not text.strip():
            empty_indices.add(i)
            processed_texts.append(" ")
        else:
            processed_texts.append(text)

    logger.info(f"Creating embeddings for {len(processed_texts)} texts (batch_size={batch_size})")

    for start in range(0, len(processed_texts), batch_size):
        batch = processed_texts[start : start + batch_size]

        from google.genai import types

        result = client.models.embed_content(
            model=settings.EMBEDDING_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(
                output_dimensionality=settings.EMBEDDING_DIMENSION,
            ),
        )

        for emb in result.embeddings:
            all_embeddings.append(list(emb.values))

    # Zero out embeddings for originally empty texts
    if empty_indices:
        zero_vector = [0.0] * settings.EMBEDDING_DIMENSION
        for idx in empty_indices:
            all_embeddings[idx] = zero_vector

    logger.info(f"Created {len(all_embeddings)} embeddings")
    return all_embeddings


def create_query_embedding(query: str) -> List[float]:
    """
    Create embedding for a search query.

    Args:
        query: Search query text

    Returns:
        Query embedding vector
    """
    return create_embedding(query)


# ============================================================
# EMBEDDING CLASS (OOP Interface)
# ============================================================

class Embedder:
    """
    Object-oriented interface for embedding operations.

    Usage:
        embedder = Embedder()
        embedding = embedder.embed("Hello world")
        embeddings = embedder.embed_batch(["Text 1", "Text 2"])
        query_embedding = embedder.embed_query("Search query")
    """

    @property
    def dimension(self) -> int:
        return settings.EMBEDDING_DIMENSION

    @property
    def model_name(self) -> str:
        return settings.EMBEDDING_MODEL

    def embed(self, text: str) -> List[float]:
        return create_embedding(text)

    def embed_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress: bool = False,
    ) -> List[List[float]]:
        return create_embeddings(texts, batch_size, show_progress)

    def embed_query(self, query: str) -> List[float]:
        return create_query_embedding(query)


# ============================================================
# CHROMADB EMBEDDING FUNCTION ADAPTER
# ============================================================

class ChromaEmbeddingFunction:
    """
    Adapter to use our embedder as a ChromaDB embedding function.

    ChromaDB expects __call__(texts) -> list[list[float]].
    """

    def __call__(self, texts: List[str]) -> List[List[float]]:
        return create_embeddings(texts)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def compute_similarity(
    embedding1: List[float],
    embedding2: List[float],
) -> float:
    """
    Compute cosine similarity between two embeddings.

    Returns:
        Cosine similarity score (-1 to 1)
    """
    import numpy as np

    v1 = np.array(embedding1)
    v2 = np.array(embedding2)

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return float(np.dot(v1, v2) / (norm1 * norm2))


def find_most_similar(
    query_embedding: List[float],
    candidate_embeddings: List[List[float]],
    top_k: int = 5,
) -> List[tuple]:
    """
    Find most similar embeddings to query (in-memory).
    For large-scale search, use VectorStore instead.

    Returns:
        List of (index, similarity_score) tuples, sorted by similarity
    """
    import numpy as np

    query = np.array(query_embedding)
    candidates = np.array(candidate_embeddings)

    similarities = np.dot(candidates, query)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    return [(int(idx), float(similarities[idx])) for idx in top_indices]


# ============================================================
# MODEL WARMUP
# ============================================================

def warmup_model() -> dict:
    """
    Verify the Gemini embedding API is reachable.
    Creates one test embedding to validate the API key.

    Returns:
        Model info dictionary
    """
    logger.info("Warming up Gemini embedding API...")

    info = get_model_info()

    _ = create_embedding("warmup test")

    logger.info(f"Gemini embedding API ready: {info['name']}")
    return info
