"""
Storage Backend Abstract Base Class

This module defines the interface that all storage backends must implement.
Using the Strategy Pattern, we can swap storage implementations without
changing any business logic.

Why Abstract Base Classes?
--------------------------
1. ENFORCES CONTRACT: Python will raise TypeError if a subclass doesn't
   implement all abstract methods
2. DOCUMENTATION: Clearly shows what methods any storage backend must have
3. TYPE HINTS: IDEs and type checkers understand the interface
4. DEPENDENCY INVERSION: High-level code depends on abstraction, not details

Pattern: Strategy Pattern
-------------------------
- Define a family of algorithms (storage backends)
- Encapsulate each one (LocalStorage, S3Storage, etc.)
- Make them interchangeable (same interface)

Real-world analogy: Different delivery services (FedEx, UPS, DHL)
all implement "ship_package()" but each does it differently.
"""
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class StoredFile:
    """
    Represents metadata about a stored file.
    
    This is returned after saving a file, containing information
    the caller needs to track the file.
    
    Using @dataclass automatically generates:
    - __init__() with all fields as parameters
    - __repr__() for debugging
    - __eq__() for comparisons
    
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
    
    Usage:
    ------
    This class cannot be instantiated directly:
    
        storage = StorageBackend()  # TypeError!
    
    Instead, use a concrete implementation:
    
        storage = LocalStorage(base_path="/uploads")
        await storage.save(file_content, "path/to/file.pdf")
    
    The beauty of this pattern is that business logic doesn't care
    which implementation is used:
    
        async def upload_document(storage: StorageBackend, file: bytes):
            # Works with LocalStorage, S3Storage, or any future backend
            return await storage.save(file, "documents/doc.pdf")
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
        
        This is the primary method for storing files. Implementations should:
        1. Create any necessary directories
        2. Write the file content
        3. Return metadata about the stored file
        
        Args:
            file_content: Raw bytes of the file to store
            destination_path: Where to store the file (relative path)
                Example: "uploads/user123/project456/abc123_document.pdf"
            content_type: MIME type of the file
                Example: "application/pdf"
        
        Returns:
            StoredFile with metadata about the saved file
        
        Raises:
            StorageError: If the file cannot be saved
            StorageFullError: If storage capacity is exceeded
        
        Example:
            file_info = await storage.save(
                file_content=pdf_bytes,
                destination_path="uploads/123/456/file.pdf",
                content_type="application/pdf"
            )
            print(f"Saved to: {file_info.path}")
            print(f"Size: {file_info.size} bytes")
        """
        pass

    @abstractmethod
    async def get(self, path: str) -> bytes:
        """
        Retrieve file content from storage.
        
        Args:
            path: Path to the file (same as destination_path used in save())
        
        Returns:
            Raw bytes of the file content
        
        Raises:
            FileNotFoundError: If the file doesn't exist
            StorageError: If the file cannot be retrieved
        
        Example:
            content = await storage.get("uploads/123/456/file.pdf")
        """
        pass


    @abstractmethod
    async def delete(self, path: str) -> bool:
        """
        Delete a file from storage.
        
        Args:
            path: Path to the file to delete
        
        Returns:
            True if file was deleted, False if it didn't exist
        
        Raises:
            StorageError: If deletion fails (permission error, etc.)
        
        Note:
            This method should NOT raise an error if the file doesn't exist.
            This makes it idempotent (safe to call multiple times).
        
        Example:
            deleted = await storage.delete("uploads/123/456/file.pdf")
            if deleted:
                print("File removed")
            else:
                print("File didn't exist")
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """
        Check if a file exists in storage.
        
        Args:
            path: Path to check
        
        Returns:
            True if file exists, False otherwise
        
        Example:
            if await storage.exists("uploads/123/456/file.pdf"):
                content = await storage.get("uploads/123/456/file.pdf")
        """
        pass
    
    @abstractmethod
    async def get_size(self, path: str) -> int:
        """
        Get the size of a file in bytes.
        
        Args:
            path: Path to the file
        
        Returns:
            File size in bytes
        
        Raises:
            FileNotFoundError: If the file doesn't exist
        
        Example:
            size = await storage.get_size("uploads/123/456/file.pdf")
            print(f"File is {size / 1024 / 1024:.2f} MB")
        """
        pass

    async def delete_directory(self, directory_path: str) -> int:
        """
        Delete an entire directory and its contents.
        
        This is optional (not abstract) because not all backends support it.
        Default implementation returns 0 (no files deleted).
        
        Args:
            directory_path: Path to directory to delete
        
        Returns:
            Number of files deleted
        
        This is useful for cleanup operations like:
        - Deleting all files when a project is deleted
        - Deleting a user's uploads when account is deleted
        
        Example:
            count = await storage.delete_directory("uploads/user123/project456")
            print(f"Deleted {count} files")
        """
        # Default implementation - subclasses can override
        return 0
    

        