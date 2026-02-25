"""
Knowledge State Schemas

Pydantic models for knowledge tracking API requests and responses.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeStateResponse(BaseModel):
    id: UUID
    user_id: UUID
    project_id: Optional[UUID] = None
    topic_id: Optional[UUID] = None
    topic_name: Optional[str] = None
    subtopic_id: Optional[UUID] = None
    subtopic_name: Optional[str] = None
    mastery_score: float = Field(ge=0.0, le=1.0)
    status: str
    correct_count: int
    total_attempts: int
    misconceptions: Dict[str, Any] = {}
    last_reviewed: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectKnowledgeResponse(BaseModel):
    """Aggregated knowledge state for an entire project."""
    project_id: UUID
    overall_mastery: float = Field(ge=0.0, le=1.0)
    total_topics: int
    mastered_topics: int
    in_progress_topics: int
    not_started_topics: int
    total_correct: int
    total_attempts: int
    topic_states: List[KnowledgeStateResponse]


class KnowledgeListResponse(BaseModel):
    states: List[KnowledgeStateResponse]
    total: int
