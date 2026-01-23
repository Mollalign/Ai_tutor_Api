"""
Storage Backend Abstract Base Class

This module defines the interface that all storage backends must implement.
Using the Strategy Pattern, we can swap storage implementations without
changing any business logic.
"""
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class StoredFile:
    """
    Represents metadata about a stored file.
    
    Attributes:
        path: The storage path where file was saved
        size: File size in bytes
        content_type: MIME type of the file (e.g., "application/pdf")
        stored_at: When the file was stored
        checksum: Optional hash for integrity verification (MD5 or SHA256)
    """
    path: str
    size: int
    content_type: str
    stored_at: datetime
    checksum: Optional[str] = None


class StorageError(Exception):
    """
    Base exception for storage operations.
    
    All storage-related errors inherit from this, allowing
    calling code to catch storage errors generically:
    
        try:
            await storage.save(...)
        except StorageError as e:
            # Handle any storage error
    """
    pass


class FileNotFoundError(StorageError):
    """Raised when a requested file doesn't exist."""
    pass


class StorageFullError(StorageError):
    """Raised when storage capacity is exceeded."""
    pass


class StorageBackend(ABC):
    """
    Abstract base class for file storage backends.
    
    All storage implementations (local, S3, GCS) must inherit from this
    and implement all abstract methods.
    """

    @abstractmethod
    async def save(
        self,
        file_content: bytes,
        destination_path: str,
        content_type: Optional[str] = None
    ) -> StoredFile:
        """
        Save file content to storage.
        
        """
        pass

    @abstractmethod
    async def get(self, path: str) -> bytes:
        """
        Retrieve file content from storage.
        """
        pass


    @abstractmethod
    async def delete(self, path: str) -> bool:
        """
        Delete a file from storage.        
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """
        Check if a file exists in storage.
        """
        pass
    
    @abstractmethod
    async def get_size(self, path: str) -> int:
        """
        Get the size of a file in bytes.
        """
        pass

    async def delete_directory(self, directory_path: str) -> int:
        """
        Delete an entire directory and its contents.
        
        This is optional (not abstract) because not all backends support it.
        Default implementation returns 0 (no files deleted).
        """
        # Default implementation - subclasses can override
        return 0
    

        