"""
Cloudinary Storage Backend

Stores files on Cloudinary's cloud service using the "raw" resource type
for non-media files (PDFs, DOCX, PPTX, TXT).

Free tier includes:
- 25 credits/month (~25GB storage + bandwidth)
- 100MB max file size
- Persistent storage (files survive server restarts)

Setup:
------
1. Sign up at https://cloudinary.com (free, no credit card)
2. Get your Cloud Name, API Key, API Secret from the Dashboard
3. Set environment variables:
   STORAGE_BACKEND=cloudinary
   CLOUDINARY_CLOUD_NAME=your-cloud-name
   CLOUDINARY_API_KEY=your-api-key
   CLOUDINARY_API_SECRET=your-api-secret
"""

import logging
import io
from typing import Optional
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
import cloudinary.api
import httpx

from app.storage.base import (
    StorageBackend,
    StoredFile,
    StorageError,
    FileNotFoundError as StorageFileNotFoundError,
)

logger = logging.getLogger(__name__)


class CloudinaryStorage(StorageBackend):
    """
    Cloudinary cloud storage implementation.
    
    Uses Cloudinary's "raw" resource type to store non-media files
    (PDFs, DOCX, PPTX, TXT, etc.).
    
    File paths are used as Cloudinary public_ids for easy retrieval.
    Example: "uploads/user123/project456/document.pdf"
    becomes public_id "uploads/user123/project456/document" in Cloudinary.
    
    Attributes:
        folder_prefix: Optional prefix for all files (e.g., "ai-tutor")
    """

    def __init__(
        self,
        cloud_name: str,
        api_key: str,
        api_secret: str,
        folder_prefix: str = "ai-tutor",
    ):
        """
        Initialize Cloudinary storage.
        
        Args:
            cloud_name: Cloudinary cloud name
            api_key: Cloudinary API key
            api_secret: Cloudinary API secret
            folder_prefix: Prefix folder for all uploads
        """
        # Configure the Cloudinary SDK globally
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True  # Use HTTPS
        )
        
        self.folder_prefix = folder_prefix
        
        # HTTP client for downloading files (reusable)
        self._http_client = httpx.AsyncClient(timeout=60.0)
        
        logger.info(
            f"CloudinaryStorage initialized "
            f"(cloud: {cloud_name}, prefix: {folder_prefix})"
        )

    def _build_public_id(self, path: str) -> str:
        """
        Convert a storage path to a Cloudinary public_id.
        
        Cloudinary public_id rules:
        - No file extension (Cloudinary manages it)
        - Forward slashes for folders
        - Alphanumeric, underscores, hyphens, slashes
        
        Args:
            path: Storage path (e.g., "uploads/user123/doc.pdf")
            
        Returns:
            Cloudinary public_id (e.g., "ai-tutor/uploads/user123/doc.pdf")
        """
        # Add folder prefix
        if self.folder_prefix:
            public_id = f"{self.folder_prefix}/{path}"
        else:
            public_id = path
        
        # Clean up double slashes
        while "//" in public_id:
            public_id = public_id.replace("//", "/")
        
        return public_id

    async def save(
        self,
        file_content: bytes,
        destination_path: str,
        content_type: Optional[str] = None,
    ) -> StoredFile:
        """
        Upload file to Cloudinary.
        
        Uses resource_type="raw" for non-media files (PDFs, DOCX, etc.)
        
        Args:
            file_content: Raw file bytes
            destination_path: Storage path (used as public_id)
            content_type: MIME type (stored as metadata)
            
        Returns:
            StoredFile with upload metadata
        """
        public_id = self._build_public_id(destination_path)
        
        try:
            # Upload to Cloudinary
            # resource_type="raw" is for non-image/video files
            # overwrite=True allows re-uploading the same file
            result = cloudinary.uploader.upload(
                io.BytesIO(file_content),
                public_id=public_id,
                resource_type="raw",
                overwrite=True,
                # Store content type in context metadata
                context=f"content_type={content_type or 'application/octet-stream'}",
            )
            
            size = result.get("bytes", len(file_content))
            
            logger.info(
                f"File uploaded to Cloudinary: {public_id} "
                f"({size} bytes, url: {result.get('secure_url', 'N/A')})"
            )
            
            return StoredFile(
                path=destination_path,
                size=size,
                content_type=content_type or "application/octet-stream",
                stored_at=datetime.now(timezone.utc),
                checksum=result.get("etag", None),
            )
            
        except cloudinary.exceptions.Error as e:
            logger.error(f"Cloudinary upload failed for {destination_path}: {e}")
            raise StorageError(f"Failed to upload file to Cloudinary: {e}")
        except Exception as e:
            logger.error(f"Unexpected error uploading to Cloudinary: {e}")
            raise StorageError(f"Failed to save file: {e}")

    async def get(self, path: str) -> bytes:
        """
        Download file content from Cloudinary.

        Uses private_download_url to generate an API-key-authenticated,
        time-limited URL that works regardless of access restrictions.

        Args:
            path: Storage path (public_id)

        Returns:
            File content as bytes
        """
        public_id = self._build_public_id(path)

        try:
            # Extract the file extension for the format parameter
            ext = path.rsplit(".", 1)[-1] if "." in path else ""

            # Generate a fully authenticated download URL
            download_url = cloudinary.utils.private_download_url(
                public_id,
                ext,
                resource_type="raw",
            )

            if not download_url:
                raise StorageFileNotFoundError(f"No URL for file: {path}")

            logger.debug(f"Downloading from Cloudinary: {download_url[:120]}...")

            response = await self._http_client.get(download_url)
            response.raise_for_status()

            content = response.content
            logger.debug(f"File downloaded from Cloudinary: {path} ({len(content)} bytes)")
            return content

        except cloudinary.exceptions.NotFound:
            logger.warning(f"File not found on Cloudinary: {path}")
            raise StorageFileNotFoundError(f"File not found: {path}")
        except httpx.HTTPError as e:
            logger.error(f"Failed to download file from Cloudinary: {e}")
            raise StorageError(f"Failed to download file: {e}")
        except StorageFileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting file from Cloudinary: {e}")
            raise StorageError(f"Failed to retrieve file: {e}")

    async def delete(self, path: str) -> bool:
        """
        Delete a file from Cloudinary.
        
        Args:
            path: Storage path (public_id)
            
        Returns:
            True if deleted, False if file didn't exist
        """
        public_id = self._build_public_id(path)
        
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type="raw",
            )
            
            deleted = result.get("result") == "ok"
            
            if deleted:
                logger.info(f"File deleted from Cloudinary: {path}")
            else:
                logger.debug(f"File not found on Cloudinary for deletion: {path}")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to delete file from Cloudinary: {e}")
            raise StorageError(f"Failed to delete file: {e}")

    async def exists(self, path: str) -> bool:
        """
        Check if a file exists on Cloudinary.
        
        Args:
            path: Storage path (public_id)
            
        Returns:
            True if file exists, False otherwise
        """
        public_id = self._build_public_id(path)
        
        try:
            cloudinary.api.resource(
                public_id,
                resource_type="raw",
            )
            return True
        except cloudinary.exceptions.NotFound:
            return False
        except Exception as e:
            logger.warning(f"Error checking file existence on Cloudinary: {e}")
            return False

    async def get_size(self, path: str) -> int:
        """
        Get file size from Cloudinary metadata.
        
        Args:
            path: Storage path (public_id)
            
        Returns:
            File size in bytes
        """
        public_id = self._build_public_id(path)
        
        try:
            resource = cloudinary.api.resource(
                public_id,
                resource_type="raw",
            )
            return resource.get("bytes", 0)
            
        except cloudinary.exceptions.NotFound:
            raise StorageFileNotFoundError(f"File not found: {path}")
        except Exception as e:
            logger.error(f"Error getting file size from Cloudinary: {e}")
            raise StorageError(f"Failed to get file size: {e}")

    async def delete_directory(self, directory_path: str) -> int:
        """
        Delete all files under a directory prefix on Cloudinary.
        
        Cloudinary doesn't have real directories, but supports
        prefix-based deletion which achieves the same effect.
        
        Args:
            directory_path: Directory prefix to delete
            
        Returns:
            Number of files deleted
        """
        prefix = self._build_public_id(directory_path)
        
        try:
            # Delete all resources with this prefix
            result = cloudinary.api.delete_resources_by_prefix(
                prefix,
                resource_type="raw",
            )
            
            deleted_counts = result.get("deleted", {})
            count = len(deleted_counts)
            
            # Also try to delete the "folder" itself
            try:
                cloudinary.api.delete_folder(prefix)
            except Exception:
                pass  # Folder might not exist or might not be empty
            
            logger.info(
                f"Deleted {count} files from Cloudinary directory: {directory_path}"
            )
            return count
            
        except Exception as e:
            logger.error(f"Failed to delete directory from Cloudinary: {e}")
            raise StorageError(f"Failed to delete directory: {e}")

    async def close(self):
        """Close the HTTP client. Called during shutdown."""
        await self._http_client.aclose()
