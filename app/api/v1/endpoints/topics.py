"""
Topic Endpoints

HTTP API for topic extraction and management.

Endpoints:
----------
- POST  /projects/{project_id}/topics/extract  - Extract topics from documents
- GET   /projects/{project_id}/topics           - List topics for a project
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.topic import TopicExtractRequest, TopicListResponse
from app.services.topic_service import (
    TopicService,
    TopicServiceError,
    ProjectNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Topics"])


def get_topic_service(db: AsyncSession = Depends(get_db)) -> TopicService:
    return TopicService(db)


@router.post(
    "/projects/{project_id}/topics/extract",
    response_model=TopicListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Extract topics from project documents",
    description="""
    Uses AI to analyze project documents and extract the main topics
    and subtopics with learning objectives.
    
    If topics already exist, returns them unless force_refresh is true.
    """,
)
async def extract_topics(
    project_id: UUID,
    request: TopicExtractRequest = TopicExtractRequest(),
    current_user: User = Depends(get_current_user),
    service: TopicService = Depends(get_topic_service),
):
    try:
        topics = await service.extract_topics(
            project_id=project_id,
            user_id=current_user.id,
            force_refresh=request.force_refresh,
        )
        return TopicListResponse(topics=topics, total=len(topics))
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    except TopicServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/projects/{project_id}/topics",
    response_model=TopicListResponse,
    summary="List topics for a project",
)
async def list_topics(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: TopicService = Depends(get_topic_service),
):
    try:
        topics = await service.list_topics(
            project_id=project_id,
            user_id=current_user.id,
        )
        return TopicListResponse(topics=topics, total=len(topics))
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
