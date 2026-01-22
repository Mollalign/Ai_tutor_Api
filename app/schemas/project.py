from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ============================================================
# Request Schemas (What client sends)
# ============================================================

class ProjectBase(BaseModel):
    """Shared attributes for project creation and updates."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Project name between 1 and 100 characters",
    )
    description: Optional[str] = Field(
        None,
        max_length=5000,
        description="Optional project description up to 5000 characters",
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Trim whitespace and ensure name is not empty."""
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Project name cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        """Trim description; treat empty strings as None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Physics 101",
                "description": "Organize lecture materials and problem sets",
                "is_archived": False,
            }
        }


class ProjectUpdate(BaseModel):
    """Schema for updating an existing project."""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Optional updated project name between 1 and 100 characters",
    )
    description: Optional[str] = Field(
        None,
        max_length=5000,
        description="Optional updated project description up to 5000 characters",
    )
    is_archived: Optional[bool] = Field(
        None,
        description="Mark project as archived/unarchived",
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        """Trim whitespace and ensure name is not empty when provided."""
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Project name cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        """Trim description; treat empty strings as None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Physics 101 - Updated",
                "description": "Reorganized course materials and notes",
                "is_archived": True,
            }
        }


# ============================================================
# Response Schemas (What server sends back)
# ============================================================

class ProjectResponse(ProjectBase):
    """Schema for project data returned from the API."""

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    is_archived: bool = Field(
        default=False,
        description="Whether the project has been archived",
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "0e8f5c4a-3c41-4c3f-9af7-2c8d7db3d6d4",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Physics 101",
                "description": "Organize lecture materials and problem sets",
                "is_archived": False,
                "created_at": "2024-01-01T12:00:00Z",
                "updated_at": "2024-01-02T08:30:00Z",
            }
        }

