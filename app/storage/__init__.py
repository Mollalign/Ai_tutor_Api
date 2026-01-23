"""
Storage Module

This module provides file storage abstraction using the Strategy Pattern.
The active backend is determined by configuration (STORAGE_BACKEND setting).

Adding New Backends:
-------------------
1. Create new file: storage/s3.py
2. Implement S3Storage(StorageBackend)
3. Add to get_storage() factory function
4. Set STORAGE_BACKEND=s3 in config

The business logic never changes - only configuration!
"""

from app.storage.base import (
    StorageBackend,
    StoredFile,
    StorageError,
    FileNotFoundError,
    StorageFullError,
)
from app.storage.local import LocalStorage
from app.core.config import settings

# Module-level storage instance (singleton)
# Created on first access, reused thereafter
_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """
    Factory function that returns the configured storage backend.
    
    This is the main entry point for getting storage access.
    Uses singleton pattern - creates instance once, reuses it.
    
    Configuration:
        Set STORAGE_BACKEND in settings/environment:
        - "local": Local filesystem storage
        - "s3": Amazon S3 (not implemented yet)
        - "gcs": Google Cloud Storage (not implemented yet)
    
    Returns:
        StorageBackend instance based on configuration
    
    Raises:
        ValueError: If STORAGE_BACKEND is not a valid option
    
    Example:
        storage = get_storage()
        await storage.save(content, "uploads/file.pdf")
    
    Why Singleton?
    -------------
    Creating new storage instances is cheap, but having one instance:
    1. Ensures consistent configuration
    2. Allows for connection pooling (for cloud backends)
    3. Makes testing easier (can replace the singleton)
    """
    global _storage_instance
    
    if _storage_instance is None:
        _storage_instance = _create_storage_backend()
    
    return _storage_instance


def _create_storage_backend() -> StorageBackend:
    """
    Internal factory that creates the appropriate storage backend.
    
    This is where the Strategy Pattern selection happens.
    
    Returns:
        Concrete StorageBackend implementation
    """
    backend = settings.STORAGE_BACKEND.lower()
    
    if backend == "local":
        return LocalStorage(base_path=settings.UPLOAD_DIR)
    
    elif backend == "s3":
        # Future implementation
        # from app.storage.s3 import S3Storage
        # return S3Storage(
        #     bucket=settings.AWS_S3_BUCKET,
        #     region=settings.AWS_REGION,
        #     access_key=settings.AWS_ACCESS_KEY,
        #     secret_key=settings.AWS_SECRET_KEY,
        # )
        raise NotImplementedError(
            "S3 storage backend not implemented yet. "
            "Set STORAGE_BACKEND=local for now."
        )
    
    elif backend == "gcs":
        # Future implementation
        # from app.storage.gcs import GCSStorage
        # return GCSStorage(bucket=settings.GCS_BUCKET)
        raise NotImplementedError(
            "GCS storage backend not implemented yet. "
            "Set STORAGE_BACKEND=local for now."
        )
    
    else:
        raise ValueError(
            f"Unknown storage backend: {backend}. "
            f"Valid options: local, s3, gcs"
        )


def reset_storage() -> None:
    """
    Reset the storage singleton.
    
    Useful for:
    - Testing (switch backends between tests)
    - Configuration changes at runtime
    
    After calling this, the next get_storage() call
    will create a new instance with current config.
    """
    global _storage_instance
    _storage_instance = None


# ============================================================
# Exports
# ============================================================
# These are what's available when you do:
# from app.storage import ...

__all__ = [
    # Main factory function
    "get_storage",
    "reset_storage",
    
    # Abstract base class (for type hints)
    "StorageBackend",
    
    # Data classes
    "StoredFile",
    
    # Exceptions
    "StorageError",
    "FileNotFoundError",
    "StorageFullError",
    
    # Concrete implementations (if needed directly)
    "LocalStorage",
]