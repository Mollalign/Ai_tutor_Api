from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl, EmailStr, Field, field_validator
import secrets


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables or .env.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra fields in .env file
    )  

    # -------------------------
    # Database
    # -------------------------
    DATABASE_URL: AnyUrl

    # -------------------------
    # Security / Auth
    # -------------------------
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # -------------------------
    # Email / SMTP
    # -------------------------
    SMTP_EMAIL: Optional[EmailStr] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_SERVER: Optional[str] = None
    SMTP_PORT: Optional[int] = None


    # -------------------------
    # Application
    # -------------------------
    PROJECT_NAME: str = "Ai Tutor API"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False 
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "UTC"

    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    FRONTEND_URL: Optional[str] = None
    ALLOWED_HOSTS: List[str] = Field(default_factory=lambda: ["localhost"])

    SQLALCHEMY_ECHO: bool = False
    DB_POOL_MIN_SIZE: Optional[int] = None
    DB_POOL_MAX_SIZE: Optional[int] = None

    SENTRY_DSN: Optional[AnyUrl] = None

    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 15

    # -------------------------
    # Redis (for ARQ task queue)
    # -------------------------
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for task queue and caching"
    )
    
    # -------------------------
    # File Storage
    # -------------------------
    STORAGE_BACKEND: str = Field(
        default="local",
        description="Storage backend: 'local', 's3', or 'gcs'"
    )
    UPLOAD_DIR: str = Field(
        default="storage/uploads",
        description="Directory for uploaded files (local storage)"
    )
    MAX_FILE_SIZE_MB: int = Field(
        default=50,
        ge=1,           # Minimum 1 MB
        le=500,         # Maximum 500 MB (sanity limit)
        description="Maximum file upload size in megabytes"
    )

    # Computed property for bytes (used in validation)
    @property
    def MAX_FILE_SIZE_BYTES(self) -> int:
        """Convert MB to bytes for file size validation."""
        return self.MAX_FILE_SIZE_MB * 1024 * 1024
    
    ALLOWED_FILE_EXTENSIONS: List[str] = Field(
        default_factory=lambda: ["pdf", "docx", "pptx", "txt"],
        description="Allowed file extensions for upload"
    )


    @field_validator("ALGORITHM")
    def validate_algorithm(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("ALGORITHM must be a non-empty string.")
        return v
    
    @field_validator("STORAGE_BACKEND")
    def validate_storage_backend(cls, v):
        """Ensure storage backend is a valid option."""
        allowed = {"local", "s3", "gcs"}
        if v not in allowed:
            raise ValueError(f"STORAGE_BACKEND must be one of: {allowed}")
        return v
    
settings = Settings()
