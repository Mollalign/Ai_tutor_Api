"""
Text Chunker

Splits documents into chunks suitable for vector embeddings.

Token Counting:
--------------
We use tiktoken (OpenAI's tokenizer) because:
- Embedding models use tokens, not characters
- 1 token ≈ 4 characters (English), varies by language
- Accurate counting ensures chunks fit in model limits
"""

import re
import logging
from typing import List, Optional, Generator
from dataclasses import dataclass, field
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================
# Try to import tiktoken for accurate token counting
# Fall back to character-based estimation if not available
# ============================================================

try:
    import tiktoken
    # Use cl100k_base encoding (GPT-4, text-embedding-ada-002)
    _tokenizer = tiktoken.get_encoding("cl100k_base")
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning(
        "tiktoken not installed. Using character-based token estimation. "
        "Install tiktoken for accurate counting: pip install tiktoken"
    )


def count_tokens(text: str) -> int:
    """
    Count tokens in text.
    
    Uses tiktoken if available, otherwise estimates based on characters.
    
    Args:
        text: Text to count tokens for
    
    Returns:
        Token count (exact with tiktoken, estimated otherwise)
    """
    if not text:
        return 0
    
    if TIKTOKEN_AVAILABLE:
        return len(_tokenizer.encode(text))
    else:
        # Rough estimation: 1 token ≈ 4 characters for English
        # This is less accurate for other languages
        return len(text) // 4


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class ChunkMetadata:
    """
    Metadata about a chunk's origin and context.
    
    This metadata is crucial for:
    1. CITATIONS: Tell users "This info is from page 5 of document X"
    2. FILTERING: Only search chunks from specific documents
    3. DEBUGGING: Trace issues back to source
    
    Attributes:
        document_id: UUID of source document
        document_name: Original filename for display
        page_number: Page/slide number in source (if applicable)
        chunk_index: Position of this chunk in the document
        total_chunks: Total chunks from this document
        start_char: Character offset where chunk starts in original
        end_char: Character offset where chunk ends
    """
    document_id: Optional[UUID] = None
    document_name: Optional[str] = None
    page_number: Optional[int] = None
    chunk_index: int = 0
    total_chunks: int = 0
    start_char: int = 0
    end_char: int = 0
    section_title: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "document_id": str(self.document_id) if self.document_id else None,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "section_title": self.section_title,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChunkMetadata":
        """Create from dictionary."""
        return cls(
            document_id=UUID(data["document_id"]) if data.get("document_id") else None,
            document_name=data.get("document_name"),
            page_number=data.get("page_number"),
            chunk_index=data.get("chunk_index", 0),
            total_chunks=data.get("total_chunks", 0),
            start_char=data.get("start_char", 0),
            end_char=data.get("end_char", 0),
            section_title=data.get("section_title"),
        )


@dataclass
class TextChunk:
    """
    A single chunk of text with metadata.
    
    This is what gets embedded and stored in the vector database.
    
    Attributes:
        id: Unique identifier for this chunk
        text: The actual text content
        tokens: Number of tokens in this chunk
        metadata: Source information
    """
    id: UUID = field(default_factory=uuid4)
    text: str = ""
    tokens: int = 0
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)
    
    def __post_init__(self):
        """Calculate tokens if not provided."""
        if self.text and self.tokens == 0:
            self.tokens = count_tokens(self.text)
    
    @property
    def is_empty(self) -> bool:
        """Check if chunk has no meaningful content."""
        return len(self.text.strip()) == 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": str(self.id),
            "text": self.text,
            "tokens": self.tokens,
            "metadata": self.metadata.to_dict(),
        }


# ============================================================
# CHUNKER CONFIGURATION
# ============================================================

@dataclass
class ChunkerConfig:
    """
    Configuration for the text chunker.
    
    Tune these parameters based on your use case:
    
    chunk_size: Target size in tokens
    - Smaller (100-300): More precise retrieval, more chunks
    - Larger (500-1000): More context per chunk, fewer chunks
    - Typical: 300-500 tokens
    
    chunk_overlap: Overlap between consecutive chunks
    - Prevents losing context at chunk boundaries
    - Usually 10-20% of chunk_size
    - Too much overlap = redundant storage
    
    min_chunk_size: Minimum chunk size
    - Prevents tiny chunks that lack context
    - Typically 50-100 tokens
    """
    chunk_size: int = 400          # Target tokens per chunk
    chunk_overlap: int = 50        # Overlap tokens between chunks
    min_chunk_size: int = 50       # Minimum tokens per chunk
    
    # Separators to try, in order of preference
    # We try to break at these boundaries before hard-splitting
    separators: List[str] = field(default_factory=lambda: [
        "\n\n",      # Paragraph breaks (strongest)
        "\n",        # Line breaks
        ". ",        # Sentence ends (period + space)
        "? ",        # Question marks
        "! ",        # Exclamation marks
        "; ",        # Semicolons
        ", ",        # Commas (weaker)
        " ",         # Words (last resort)
    ])
    
    def __post_init__(self):
        """Validate configuration."""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        if self.min_chunk_size > self.chunk_size:
            raise ValueError("min_chunk_size must be less than chunk_size")


# ============================================================
# TEXT CHUNKER
# ============================================================

class TextChunker:
    """
    Splits text into chunks suitable for vector embeddings.
    
    Uses a recursive approach:
    1. Try to split at paragraph boundaries
    2. If paragraphs too long, split at sentences
    3. If sentences too long, split at smaller units
    4. Ensure overlap between chunks
    
    Usage:
        chunker = TextChunker()
        chunks = chunker.chunk_text(
            text="Long document text...",
            document_id=doc.id,
            document_name="lecture.pdf"
        )
        
        for chunk in chunks:
            print(f"Chunk {chunk.metadata.chunk_index}: {chunk.tokens} tokens")
    """
    
    def __init__(self, config: Optional[ChunkerConfig] = None):
        """
        Initialize chunker with configuration.
        
        Args:
            config: ChunkerConfig instance (uses defaults if not provided)
        """
        self.config = config or ChunkerConfig()
        logger.info(
            f"TextChunker initialized: "
            f"chunk_size={self.config.chunk_size}, "
            f"overlap={self.config.chunk_overlap}"
        )
    
    def chunk_text(
        self,
        text: str,
        document_id: Optional[UUID] = None,
        document_name: Optional[str] = None,
    ) -> List[TextChunk]:
        """
        Split text into chunks.
        
        Main entry point for chunking a document.
        
        Args:
            text: Full text to chunk
            document_id: UUID of source document (for metadata)
            document_name: Original filename (for metadata)
        
        Returns:
            List of TextChunk objects with metadata
        
        Example:
            chunks = chunker.chunk_text(
                text=parsed_doc.text,
                document_id=doc.id,
                document_name="biochemistry.pdf"
            )
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to chunker")
            return []
        
        logger.info(
            f"Chunking text: {len(text)} characters, "
            f"~{count_tokens(text)} tokens"
        )
        
        # Split text into initial segments
        segments = self._split_text(text)
        
        # Create chunks with overlap
        chunks = self._create_chunks_with_overlap(segments)
        
        # Add metadata
        total_chunks = len(chunks)
        result_chunks = []
        
        for i, chunk_text in enumerate(chunks):
            chunk = TextChunk(
                text=chunk_text,
                metadata=ChunkMetadata(
                    document_id=document_id,
                    document_name=document_name,
                    chunk_index=i,
                    total_chunks=total_chunks,
                )
            )
            result_chunks.append(chunk)
        
        logger.info(f"Created {len(result_chunks)} chunks from text")
        return result_chunks
    
    def chunk_pages(
        self,
        pages: List[dict],
        document_id: Optional[UUID] = None,
        document_name: Optional[str] = None,
    ) -> List[TextChunk]:
        """
        Chunk text with page-level awareness.
        
        Use this when you have page-structured content (PDF, PPTX).
        Preserves page numbers in metadata for citations.
        
        Args:
            pages: List of dicts with 'page_number' and 'text' keys
            document_id: UUID of source document
            document_name: Original filename
        
        Returns:
            List of TextChunk objects with page metadata
        
        Example:
            pages = [
                {"page_number": 1, "text": "Chapter 1..."},
                {"page_number": 2, "text": "More content..."},
            ]
            chunks = chunker.chunk_pages(pages, doc.id, "book.pdf")
        """
        all_chunks = []
        chunk_index = 0
        
        for page_data in pages:
            page_num = page_data.get("page_number", 0)
            page_text = page_data.get("text", "")
            
            if not page_text.strip():
                continue
            
            # Chunk this page's text
            page_segments = self._split_text(page_text)
            page_chunks = self._create_chunks_with_overlap(page_segments)
            
            for chunk_text in page_chunks:
                chunk = TextChunk(
                    text=chunk_text,
                    metadata=ChunkMetadata(
                        document_id=document_id,
                        document_name=document_name,
                        page_number=page_num,
                        chunk_index=chunk_index,
                    )
                )
                all_chunks.append(chunk)
                chunk_index += 1
        
        # Update total_chunks in all metadata
        total = len(all_chunks)
        for chunk in all_chunks:
            chunk.metadata.total_chunks = total
        
        logger.info(
            f"Created {len(all_chunks)} chunks from {len(pages)} pages"
        )
        return all_chunks
    
    def _split_text(self, text: str) -> List[str]:
        """
        Split text into segments using recursive separator approach.
        
        Tries each separator in order, recursively splitting
        segments that are still too large.
        
        Args:
            text: Text to split
        
        Returns:
            List of text segments
        """
        return self._recursive_split(text, separators=self.config.separators)
    
    def _recursive_split(
        self,
        text: str,
        separators: List[str]
    ) -> List[str]:
        """
        Recursively split text using separators.
        
        Algorithm:
        1. Try first separator in list
        2. For each resulting segment:
           - If small enough, keep it
           - If too large, recursively split with next separator
        3. If no separators left, hard-split by characters
        
        Args:
            text: Text to split
            separators: List of separators to try
        
        Returns:
            List of text segments
        """
        if not text.strip():
            return []
        
        # Check if text is already small enough
        if count_tokens(text) <= self.config.chunk_size:
            return [text]
        
        # No separators left - hard split
        if not separators:
            return self._hard_split(text)
        
        # Try current separator
        separator = separators[0]
        remaining_separators = separators[1:]
        
        # Split on this separator
        parts = text.split(separator)
        
        # If separator didn't split anything, try next
        if len(parts) == 1:
            return self._recursive_split(text, remaining_separators)
        
        # Process each part
        result = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            part_tokens = count_tokens(part)
            
            if part_tokens <= self.config.chunk_size:
                # Part is small enough
                result.append(part)
            else:
                # Part is still too large, split further
                sub_parts = self._recursive_split(part, remaining_separators)
                result.extend(sub_parts)
        
        return result
    
    def _hard_split(self, text: str) -> List[str]:
        """
        Split text at exact positions when no separators work.
        
        This is a last resort for very long strings without
        natural break points (e.g., URLs, code).
        
        Args:
            text: Text to split
        
        Returns:
            List of text segments
        """
        target_chars = self.config.chunk_size * 4  # Approximate chars per chunk
        
        result = []
        current_pos = 0
        
        while current_pos < len(text):
            end_pos = min(current_pos + target_chars, len(text))
            
            # Try to find a space near the boundary
            if end_pos < len(text):
                # Look for space within last 20% of chunk
                search_start = end_pos - (target_chars // 5)
                space_pos = text.rfind(' ', search_start, end_pos)
                
                if space_pos > current_pos:
                    end_pos = space_pos
            
            segment = text[current_pos:end_pos].strip()
            if segment:
                result.append(segment)
            
            current_pos = end_pos
        
        return result
    
    def _create_chunks_with_overlap(
        self,
        segments: List[str]
    ) -> List[str]:
        """
        Combine segments into chunks with overlap.
        
        Algorithm:
        1. Accumulate segments until chunk_size reached
        2. When chunk complete, start next chunk with overlap
        3. Overlap is taken from end of previous chunk
        
        Args:
            segments: List of text segments
        
        Returns:
            List of chunk texts with overlap
        """
        if not segments:
            return []
        
        chunks = []
        current_chunk_parts = []
        current_tokens = 0
        
        for segment in segments:
            segment_tokens = count_tokens(segment)
            
            # If adding this segment exceeds limit, finalize current chunk
            if current_tokens + segment_tokens > self.config.chunk_size:
                if current_chunk_parts:
                    chunk_text = self._join_segments(current_chunk_parts)
                    chunks.append(chunk_text)
                    
                    # Start new chunk with overlap from previous
                    overlap_parts = self._get_overlap_parts(
                        current_chunk_parts,
                        self.config.chunk_overlap
                    )
                    current_chunk_parts = overlap_parts
                    current_tokens = sum(count_tokens(p) for p in overlap_parts)
            
            current_chunk_parts.append(segment)
            current_tokens += segment_tokens
        
        # Don't forget the last chunk
        if current_chunk_parts:
            chunk_text = self._join_segments(current_chunk_parts)
            
            # Only add if it meets minimum size
            if count_tokens(chunk_text) >= self.config.min_chunk_size:
                chunks.append(chunk_text)
            elif chunks:
                # Append to previous chunk if too small
                chunks[-1] = chunks[-1] + " " + chunk_text
        
        return chunks
    
    def _join_segments(self, segments: List[str]) -> str:
        """Join segments with appropriate spacing."""
        return " ".join(segments)
    
    def _get_overlap_parts(
        self,
        parts: List[str],
        target_tokens: int
    ) -> List[str]:
        """
        Get segments from end of list for overlap.
        
        Works backwards from end of parts list, accumulating
        until we have approximately target_tokens.
        
        Args:
            parts: List of text segments
            target_tokens: Target token count for overlap
        
        Returns:
            List of segments for overlap
        """
        if not parts or target_tokens <= 0:
            return []
        
        overlap_parts = []
        current_tokens = 0
        
        # Work backwards
        for part in reversed(parts):
            part_tokens = count_tokens(part)
            
            if current_tokens + part_tokens > target_tokens:
                break
            
            overlap_parts.insert(0, part)
            current_tokens += part_tokens
        
        return overlap_parts


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def chunk_document(
    text: str,
    document_id: Optional[UUID] = None,
    document_name: Optional[str] = None,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
) -> List[TextChunk]:
    """
    Convenience function for chunking a document.
    
    Creates a TextChunker with specified config and chunks the text.
    
    Args:
        text: Full document text
        document_id: Source document ID
        document_name: Source document name
        chunk_size: Target tokens per chunk
        chunk_overlap: Overlap between chunks
    
    Returns:
        List of TextChunk objects
    
    Example:
        chunks = chunk_document(
            text="Long text...",
            document_id=doc.id,
            chunk_size=500
        )
    """
    config = ChunkerConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    chunker = TextChunker(config)
    return chunker.chunk_text(text, document_id, document_name)