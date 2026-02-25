"""
Topic Schemas

Pydantic models for topic extraction API requests and responses.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# Request Schemas
# ============================================================

class TopicExtractRequest(BaseModel):
    """Request to extract topics from project documents."""
    force_refresh: bool = Field(
        default=False,
        description="If true, re-extract topics even if they already exist"
    )


# ============================================================
# Response Schemas
# ============================================================

class SubtopicResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    learning_objectives: Optional[List[str]] = None
    is_auto_generated: bool = True
    display_order: int = 0

    class Config:
        from_attributes = True


class TopicResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: Optional[str] = None
    is_auto_generated: bool = True
    display_order: int = 0
    subtopics: List[SubtopicResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True


class TopicListResponse(BaseModel):
    topics: List[TopicResponse]
    total: int
