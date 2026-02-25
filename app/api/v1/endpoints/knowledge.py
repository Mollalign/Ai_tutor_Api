"""
Knowledge & Progress Endpoints

HTTP API for knowledge state tracking and progress analytics.

Endpoints:
----------
- GET  /projects/{project_id}/knowledge   - Get knowledge state for a project
- GET  /progress/stats                     - Get overall user progress stats
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.knowledge import ProjectKnowledgeResponse
from app.services.knowledge_service import (
    KnowledgeService,
    KnowledgeServiceError,
    ProjectNotFoundError,
)
from app.repositories.project_repo import ProjectRepository
from app.repositories.quiz_repo import QuizAttemptRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Knowledge & Progress"])


def get_knowledge_service(db: AsyncSession = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)


# ============================================================
# PROJECT KNOWLEDGE STATE
# ============================================================

@router.get(
    "/projects/{project_id}/knowledge",
    response_model=ProjectKnowledgeResponse,
    summary="Get knowledge state for a project",
    description="""
    Returns the user's mastery level for each topic in the project,
    along with aggregate statistics.
    """,
)
async def get_project_knowledge(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    try:
        return await service.get_project_knowledge(
            project_id=project_id,
            user_id=current_user.id,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


# ============================================================
# OVERALL PROGRESS STATS
# ============================================================

@router.get(
    "/progress/stats",
    summary="Get overall user progress",
    description="""
    Returns aggregated progress statistics across all projects:
    - Total topics studied
    - Average mastery score
    - Total quiz questions answered
    - Total projects
    - Total conversations
    """,
)
async def get_progress_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select, func
    from app.models.project import Project
    from app.models.conversation import Conversation
    from app.models.quiz_attempt import QuizAttempt

    knowledge_service = KnowledgeService(db)
    knowledge_stats = await knowledge_service.get_user_stats(current_user.id)

    # Project count
    result = await db.execute(
        select(func.count(Project.id)).where(Project.user_id == current_user.id)
    )
    total_projects = result.scalar() or 0

    # Conversation count
    result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.user_id == current_user.id)
    )
    total_conversations = result.scalar() or 0

    # Quiz attempt count and avg score
    result = await db.execute(
        select(
            func.count(QuizAttempt.id),
            func.avg(QuizAttempt.percentage),
        ).where(
            QuizAttempt.user_id == current_user.id,
            QuizAttempt.completed_at.isnot(None),
        )
    )
    row = result.one()
    total_quiz_attempts = row[0] or 0
    avg_quiz_score = float(row[1] or 0)

    return {
        "total_projects": total_projects,
        "total_conversations": total_conversations,
        "total_quiz_attempts": total_quiz_attempts,
        "avg_quiz_score": round(avg_quiz_score, 1),
        "knowledge": knowledge_stats,
    }
