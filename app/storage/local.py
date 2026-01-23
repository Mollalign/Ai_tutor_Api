"""
Local Filesystem Storage Backend

This implementation stores files on the local filesystem.
Perfect for:
- Development environments
- Single-server deployments
- Small-scale applications

For production with multiple servers, use S3 or GCS instead
(horizontal scaling requires shared storage).

Directory Structure:
-------------------
{base_path}/
└── uploads/
    └── {user_id}/
        └── {project_id}/
            └── {uuid}_{filename}

Security Considerations:
-----------------------
1. NEVER trust user-provided filenames directly
2. Generate unique names to prevent overwrites
3. Validate file types by content, not extension
4. Set appropriate file permissions
"""

import os
import hashlib
import logging
import aiofiles
import aiofiles.os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from app.storage.base import (
    StorageBackend,
    StoredFile,
    StorageError,
    FileNotFoundError as StorageFileNotFoundError,
)

logger = logging.getLogger(__name__)


class LocalStorage(StorageBackend):
    """
    Local filesystem storage implementation.
    
    Stores files in a directory on the local machine.
    Uses async file I/O to avoid blocking the event loop.
    
    Attributes:
        base_path: Root directory for all file storage
                   Example: "/app/storage/uploads"
    """

    def __init__(self, base_path: str):
        """
        Initialize local storage with a base directory.
        
        Args:
            base_path: Root directory for storage. Will be created if
                      it doesn't exist.
        
        Note:
            The base_path can be relative or absolute:
            - Relative: "storage/uploads" → relative to working directory
            - Absolute: "/var/data/uploads" → exactly this path
        """
        # Convert to Path object for easier manipulation
        # Path handles OS-specific separators (/ vs \)
        self.base_path = Path(base_path)

        # Create base directory if it doesn't exist
        # parents=True creates intermediate directories
        # exist_ok=True doesn't raise error if already exists
        self.base_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"LocalStorage initialized at: {self.base_path.absolute()}")

    
    def _get_full_path(self, relative_path: str) -> Path:
        """
        Convert relative path to full absolute path.
        
        Security: Prevents path traversal attacks by resolving
        the path and checking it's still under base_path.
        
        Args:
            relative_path: Path relative to base_path
        
        Returns:
            Full Path object
        
        Raises:
            StorageError: If path would escape base_path (attack attempt)
        
        Example:
            # Safe path
            _get_full_path("users/123/file.pdf")
            # Returns: /app/storage/uploads/users/123/file.pdf
            
            # Attack attempt (path traversal)
            _get_full_path("../../../etc/passwd")
            # Raises: StorageError
        """
        # Construct the full path
        full_path = self.base_path / relative_path
        
        # Resolve to absolute path (follows symlinks, resolves ..)
        resolved = full_path.resolve()

        # Security check: ensure path is still under base_path
        # This prevents "../../../etc/passwd" attacks
        try:
            resolved.relative_to(self.base_path.resolve())
        except ValueError:
            # Path would escape base directory
            logger.warning(f"Path traversal attempt detected: {relative_path}")
            raise StorageError(f"Invalid path: {relative_path}")
        
        return resolved
    
    def _calculate_checksum(self, content: bytes) -> str:
        """
        Calculate MD5 checksum of file content.
        
        Used for:
        - Integrity verification (detect corruption)
        - Deduplication (same content = same hash)
        - ETags in HTTP responses
        
        Args:
            content: File bytes
        
        Returns:
            Hexadecimal MD5 hash string (32 characters)
        
        Note:
            MD5 is NOT cryptographically secure, but it's fast
            and fine for integrity checking.
        """
        return hashlib.md5(content).hexdigest()
    
    
    async def save(
        self,
        file_content: bytes,
        destination_path: str,
        content_type: Optional[str] = None
    ) -> StoredFile:
        """
        Save file to local filesystem.
        
        Creates parent directories if they don't exist.
        Uses async I/O to avoid blocking.
        
        Args:
            file_content: Raw bytes to save
            destination_path: Where to save (relative to base_path)
            content_type: MIME type (stored in metadata)
        
        Returns:
            StoredFile with path, size, checksum, etc.
        """
        try:
            full_path = self._get_full_path(destination_path)
            
            # Create parent directories if needed
            # Example: for "users/123/docs/file.pdf", creates "users/123/docs/"
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file using async I/O
            # 'wb' = write binary mode
            async with aiofiles.open(full_path, 'wb') as f:
                await f.write(file_content)
            
            # Calculate metadata
            size = len(file_content)
            checksum = self._calculate_checksum(file_content)
            
            logger.info(
                f"File saved: {destination_path} "
                f"({size} bytes, checksum: {checksum[:8]}...)"
            )
            
            return StoredFile(
                path=destination_path,
                size=size,
                content_type=content_type or "application/octet-stream",
                stored_at=datetime.now(timezone.utc),
                checksum=checksum
            )
            
        except OSError as e:
            # OSError covers disk full, permission denied, etc.
            logger.error(f"Failed to save file {destination_path}: {e}")
            raise StorageError(f"Failed to save file: {e}")

    
    async def get(self, path: str) -> bytes:
        """
        Read file content from storage.
        
        Args:
            path: Relative path to file
        
        Returns:
            File content as bytes
        
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        full_path = self._get_full_path(path)
        
        # Check if file exists
        if not full_path.exists():
            logger.warning(f"File not found: {path}")
            raise StorageFileNotFoundError(f"File not found: {path}")
        
        # Check if it's actually a file (not a directory)
        if not full_path.is_file():
            raise StorageError(f"Path is not a file: {path}")
        
        try:
            # Read using async I/O
            async with aiofiles.open(full_path, 'rb') as f:
                content = await f.read()
            
            logger.debug(f"File read: {path} ({len(content)} bytes)")
            return content
            
        except OSError as e:
            logger.error(f"Failed to read file {path}: {e}")
            raise StorageError(f"Failed to read file: {e}")


    async def delete(self, path: str) -> bool:
        """
        Delete a file from storage.
        
        Idempotent: Returns False if file didn't exist (no error).
        
        Args:
            path: Relative path to file
        
        Returns:
            True if deleted, False if didn't exist
        """
        full_path = self._get_full_path(path)
        
        # Check if file exists
        if not full_path.exists():
            logger.debug(f"File already doesn't exist: {path}")
            return False
        
        try:
            # Use async remove
            await aiofiles.os.remove(full_path)
            logger.info(f"File deleted: {path}")
            return True
            
        except OSError as e:
            logger.error(f"Failed to delete file {path}: {e}")
            raise StorageError(f"Failed to delete file: {e}")  


    async def exists(self, path: str) -> bool:
        """
        Check if file exists.
        
        Args:
            path: Relative path to check
        
        Returns:
            True if file exists, False otherwise
        """
        try:
            full_path = self._get_full_path(path)
            return full_path.exists() and full_path.is_file()
        except StorageError:
            # Invalid path (traversal attempt) → doesn't exist
            return False      
    

    async def get_size(self, path: str) -> int:
        """
        Get file size in bytes.
        
        Args:
            path: Relative path to file
        
        Returns:
            Size in bytes
        """
        full_path = self._get_full_path(path)
        
        if not full_path.exists():
            raise StorageFileNotFoundError(f"File not found: {path}")
        
        # stat() returns file metadata including size
        stat_result = full_path.stat()
        return stat_result.st_size
    

    async def delete_directory(self, directory_path: str) -> int:
        """
        Delete a directory and all its contents.
        
        Used when:
        - A project is deleted (remove all project files)
        - A user is deleted (remove all user files)
        
        Args:
            directory_path: Relative path to directory
        
        Returns:
            Number of files deleted
        """
        full_path = self._get_full_path(directory_path)
        
        if not full_path.exists():
            return 0
        
        if not full_path.is_dir():
            # It's a file, delete it
            await self.delete(directory_path)
            return 1
        
        deleted_count = 0

        try:
            # Walk through directory recursively
            # We delete files first, then empty directories
            for root, dirs, files in os.walk(full_path, topdown=False):
                # Delete files
                for filename in files:
                    file_path = Path(root) / filename
                    await aiofiles.os.remove(file_path)
                    deleted_count += 1
                
                # Delete now-empty directories
                for dirname in dirs:
                    dir_path = Path(root) / dirname
                    await aiofiles.os.rmdir(dir_path)
            
            # Delete the root directory itself
            await aiofiles.os.rmdir(full_path)
            
            logger.info(f"Directory deleted: {directory_path} ({deleted_count} files)")
            return deleted_count
            
        except OSError as e:
            logger.error(f"Failed to delete directory {directory_path}: {e}")
            raise StorageError(f"Failed to delete directory: {e}")