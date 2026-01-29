"""
Vector Store Module

Manages vector embeddings using ChromaDB.

ChromaDB Concepts:
-----------------
- COLLECTION: Like a database table, holds related documents
- DOCUMENT: Text content with metadata
- EMBEDDING: Vector representation of the document
- ID: Unique identifier for each document

Storage Modes:
-------------
1. EPHEMERAL: In-memory, fast but data lost on restart
2. PERSISTENT: Saved to disk, survives restarts
3. CLIENT: Connect to remote ChromaDB server

Our Approach:
------------
- Use persistent mode for development
- Client mode for production (separate ChromaDB server)
- One collection per "project" for isolation
- Store chunk metadata for citations

IMPORTANT: ChromaDB stores embeddings, not creates them!
We need an embedding function/model to create vectors.
ChromaDB can use its default or we provide our own.
"""

import logging
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from uuid import UUID
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.models.Collection import Collection

from app.core.config import settings

# Import for type checking only to avoid circular import
# vector_store.py <- rag/__init__.py <- rag/pipeline.py <- vector_store.py
if TYPE_CHECKING:
    from app.ai.rag.chunker import TextChunk, ChunkMetadata

logger = logging.getLogger(__name__)


# ============================================================
# CHROMADB CLIENT SINGLETON
# ============================================================

_chroma_client: Optional[chromadb.ClientAPI] = None


def get_chroma_client() -> chromadb.ClientAPI:
    """
    Get or create ChromaDB client (singleton).
    
    Creates appropriate client based on configuration:
    - If CHROMA_HOST is set: Connect to remote server
    - Otherwise: Use persistent local storage
    
    Returns:
        ChromaDB client instance
    """
    global _chroma_client
    
    if _chroma_client is not None:
        return _chroma_client
    
    if settings.CHROMA_HOST:
        # Client mode - connect to remote server
        logger.info(
            f"Connecting to ChromaDB server at "
            f"{settings.CHROMA_HOST}:{settings.CHROMA_PORT}"
        )
        _chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
    else:
        # Persistent mode - local storage
        persist_path = Path(settings.CHROMA_PERSIST_DIRECTORY)
        persist_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Using persistent ChromaDB at {persist_path}")
        
        _chroma_client = chromadb.PersistentClient(
            path=str(persist_path),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            )
        )
    
    logger.info("ChromaDB client initialized")
    return _chroma_client


def reset_chroma_client() -> None:
    """Reset the ChromaDB client singleton."""
    global _chroma_client
    _chroma_client = None


# ============================================================
# VECTOR STORE CLASS
# ============================================================

class VectorStore:
    """
    High-level interface for vector storage operations.
    
    Manages document chunks in ChromaDB with:
    - Collection management (create, delete)
    - Document operations (add, update, delete)
    - Similarity search
    - Metadata filtering
    
    Usage:
        store = VectorStore()
        
        # Add chunks
        await store.add_chunks(chunks, project_id)
        
        # Search
        results = await store.search(
            query_embedding=[0.1, 0.2, ...],
            project_id=project_id,
            top_k=5
        )
        
        # Delete document's chunks
        await store.delete_by_document(document_id)
    
    Collection Naming:
    -----------------
    We use one collection per project for isolation:
    - Collection name: "project_{project_id}"
    - Allows efficient queries within a project
    - Easy cleanup when project is deleted
    """
    
    def __init__(self):
        """Initialize vector store with ChromaDB client."""
        self.client = get_chroma_client()
    
    # ============================================================
    # COLLECTION MANAGEMENT
    # ============================================================
    
    def _get_collection_name(self, project_id: UUID) -> str:
        """
        Generate collection name for a project.
        
        Format: project_{uuid}
        
        ChromaDB collection names must:
        - Be 3-63 characters
        - Start and end with alphanumeric
        - Contain only alphanumeric, underscore, hyphen
        """
        # Remove hyphens from UUID for cleaner name
        clean_id = str(project_id).replace("-", "")
        return f"project_{clean_id}"
    
    def get_or_create_collection(
        self,
        project_id: UUID,
        embedding_function: Optional[Any] = None
    ) -> Collection:
        """
        Get or create a collection for a project.
        
        Args:
            project_id: Project UUID
            embedding_function: Optional embedding function
                If not provided, you must provide embeddings when adding
        
        Returns:
            ChromaDB Collection object
        """
        collection_name = self._get_collection_name(project_id)
        
        # Get or create collection
        # If embedding_function is None, ChromaDB won't auto-embed
        collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"project_id": str(project_id)},
            embedding_function=embedding_function
        )
        
        logger.debug(f"Got collection '{collection_name}'")
        return collection
    
    def delete_collection(self, project_id: UUID) -> bool:
        """
        Delete a project's collection.
        
        Called when a project is deleted.
        
        Args:
            project_id: Project UUID
        
        Returns:
            True if deleted, False if didn't exist
        """
        collection_name = self._get_collection_name(project_id)
        
        try:
            self.client.delete_collection(collection_name)
            logger.info(f"Deleted collection '{collection_name}'")
            return True
        except Exception as e:
            logger.debug(f"Collection '{collection_name}' not found: {e}")
            return False
    
    def collection_exists(self, project_id: UUID) -> bool:
        """Check if a collection exists for a project."""
        collection_name = self._get_collection_name(project_id)
        
        try:
            collections = self.client.list_collections()
            return any(c.name == collection_name for c in collections)
        except Exception:
            return False
    
    # ============================================================
    # DOCUMENT OPERATIONS
    # ============================================================
    
    def add_chunks(
        self,
        chunks: List["TextChunk"],
        embeddings: List[List[float]],
        project_id: UUID,
    ) -> int:
        """
        Add text chunks with their embeddings to the store.
        
        Args:
            chunks: List of TextChunk objects
            embeddings: List of embedding vectors (same length as chunks)
            project_id: Project UUID for collection selection
        
        Returns:
            Number of chunks added
        
        Raises:
            ValueError: If chunks and embeddings length mismatch
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) "
                "must have same length"
            )
        
        if not chunks:
            logger.warning("No chunks to add")
            return 0
        
        collection = self.get_or_create_collection(project_id)
        
        # Prepare data for ChromaDB
        ids = [str(chunk.id) for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [self._prepare_metadata(chunk) for chunk in chunks]
        
        # Add to collection
        # ChromaDB handles batching internally
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        logger.info(
            f"Added {len(chunks)} chunks to collection "
            f"'{collection.name}'"
        )
        return len(chunks)
    
    def _prepare_metadata(self, chunk: "TextChunk") -> Dict[str, Any]:
        """
        Prepare chunk metadata for ChromaDB.
        
        ChromaDB metadata values must be:
        - str, int, float, or bool
        - No nested dicts or lists
        
        We flatten our metadata structure.
        """
        meta = chunk.metadata
        return {
            "document_id": str(meta.document_id) if meta.document_id else "",
            "document_name": meta.document_name or "",
            "page_number": meta.page_number or 0,
            "chunk_index": meta.chunk_index,
            "total_chunks": meta.total_chunks,
            "tokens": chunk.tokens,
        }
    
    def delete_by_document(
        self,
        document_id: UUID,
        project_id: UUID
    ) -> int:
        """
        Delete all chunks for a document.
        
        Called when a document is deleted.
        
        Args:
            document_id: Document UUID
            project_id: Project UUID
        
        Returns:
            Number of chunks deleted
        """
        collection = self.get_or_create_collection(project_id)
        
        # Find chunks belonging to this document
        # ChromaDB where filter syntax
        try:
            # Get IDs of chunks to delete
            results = collection.get(
                where={"document_id": str(document_id)},
                include=[]  # Don't need content, just IDs
            )
            
            if not results['ids']:
                logger.debug(f"No chunks found for document {document_id}")
                return 0
            
            # Delete by IDs
            collection.delete(ids=results['ids'])
            
            count = len(results['ids'])
            logger.info(f"Deleted {count} chunks for document {document_id}")
            return count
            
        except Exception as e:
            logger.error(f"Error deleting chunks: {e}")
            return 0
    
    def get_document_chunks(
        self,
        document_id: UUID,
        project_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        Get all chunks for a document.
        
        Useful for:
        - Viewing document content
        - Debugging
        - Reprocessing
        
        Args:
            document_id: Document UUID
            project_id: Project UUID
        
        Returns:
            List of chunk data with text and metadata
        """
        collection = self.get_or_create_collection(project_id)
        
        results = collection.get(
            where={"document_id": str(document_id)},
            include=["documents", "metadatas", "embeddings"]
        )
        
        chunks = []
        for i, doc_id in enumerate(results['ids']):
            chunks.append({
                "id": doc_id,
                "text": results['documents'][i] if results['documents'] else None,
                "metadata": results['metadatas'][i] if results['metadatas'] else None,
                "embedding": results['embeddings'][i] if results.get('embeddings') else None,
            })
        
        return chunks
    
    # ============================================================
    # SEARCH OPERATIONS
    # ============================================================
    
    def search(
        self,
        query_embedding: List[float],
        project_id: UUID,
        top_k: int = 5,
        document_ids: Optional[List[UUID]] = None,
        min_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using vector similarity.
        
        This is the main search method for RAG.
        
        Args:
            query_embedding: Vector embedding of the search query
            project_id: Project to search in
            top_k: Maximum number of results
            document_ids: Optional filter to specific documents
            min_score: Minimum similarity score (0-1)
        
        Returns:
            List of results with text, metadata, and score
        
        Example:
            # Get query embedding (from embedder)
            query_embedding = embedder.embed("What is mitosis?")
            
            # Search
            results = store.search(
                query_embedding=query_embedding,
                project_id=project_id,
                top_k=5
            )
            
            for r in results:
                print(f"Score: {r['score']:.3f}")
                print(f"Text: {r['text'][:100]}...")
                print(f"Source: {r['metadata']['document_name']}, page {r['metadata']['page_number']}")
        """
        collection = self.get_or_create_collection(project_id)
        
        # Build where filter
        where_filter = None
        if document_ids:
            # Filter to specific documents
            doc_id_strs = [str(did) for did in document_ids]
            if len(doc_id_strs) == 1:
                where_filter = {"document_id": doc_id_strs[0]}
            else:
                where_filter = {"document_id": {"$in": doc_id_strs}}
        
        # Query collection
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        # Process results
        # ChromaDB returns distances; we convert to similarity scores
        search_results = []
        
        if not results['ids'] or not results['ids'][0]:
            return []
        
        for i, chunk_id in enumerate(results['ids'][0]):
            # ChromaDB uses L2 distance by default
            # Convert to similarity score (closer = higher score)
            distance = results['distances'][0][i]
            # Simple conversion: similarity = 1 / (1 + distance)
            # Higher is better
            similarity = 1 / (1 + distance)
            
            if similarity < min_score:
                continue
            
            search_results.append({
                "id": chunk_id,
                "text": results['documents'][0][i],
                "metadata": results['metadatas'][0][i],
                "score": similarity,
                "distance": distance,
            })
        
        logger.debug(
            f"Search returned {len(search_results)} results "
            f"(top score: {search_results[0]['score']:.3f if search_results else 0})"
        )
        
        return search_results
    
    def search_with_text(
        self,
        query_text: str,
        project_id: UUID,
        embedding_function: Any,
        top_k: int = 5,
        document_ids: Optional[List[UUID]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search using text query (embedding generated automatically).
        
        Convenience method that handles embedding the query.
        
        Args:
            query_text: Text query
            project_id: Project to search in
            embedding_function: Function to create embeddings
            top_k: Maximum results
            document_ids: Optional document filter
        
        Returns:
            List of search results
        """
        # Create query embedding
        query_embedding = embedding_function([query_text])[0]
        
        return self.search(
            query_embedding=query_embedding,
            project_id=project_id,
            top_k=top_k,
            document_ids=document_ids
        )
    
    # ============================================================
    # STATISTICS
    # ============================================================
    
    def get_collection_stats(self, project_id: UUID) -> Dict[str, Any]:
        """
        Get statistics for a project's collection.
        
        Returns:
            Dictionary with count, metadata, etc.
        """
        collection = self.get_or_create_collection(project_id)
        
        return {
            "name": collection.name,
            "count": collection.count(),
            "metadata": collection.metadata,
        }
    
    def count_chunks(self, project_id: UUID) -> int:
        """Count total chunks in a project's collection."""
        collection = self.get_or_create_collection(project_id)
        return collection.count()
    
    def count_document_chunks(
        self,
        document_id: UUID,
        project_id: UUID
    ) -> int:
        """Count chunks for a specific document."""
        collection = self.get_or_create_collection(project_id)
        
        results = collection.get(
            where={"document_id": str(document_id)},
            include=[]
        )
        
        return len(results['ids'])


# ============================================================
# SINGLETON INSTANCE
# ============================================================

_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get or create VectorStore singleton."""
    global _vector_store
    
    if _vector_store is None:
        _vector_store = VectorStore()
    
    return _vector_store


def reset_vector_store() -> None:
    """Reset VectorStore singleton."""
    global _vector_store
    _vector_store = None
    reset_chroma_client()


# ============================================================
# HEALTH CHECK
# ============================================================

def check_vector_store_health() -> bool:
    """
    Check if vector store is accessible.
    
    Used for health checks.
    
    Returns:
        True if healthy, False otherwise
    """
    try:
        client = get_chroma_client()
        # Try to list collections as a health check
        client.list_collections()
        return True
    except Exception as e:
        logger.error(f"Vector store health check failed: {e}")
        return False