"""
Knowledge & Progress Endpoints

HTTP API for knowledge state tracking and progress analytics.

Endpoints:
----------
- GET  /projects/{project_id}/knowledge   - Get knowledge state for a project
- GET  /progress/stats                     - Get overall user progress stats
- GET  /progress/quiz-history              - Get recent quiz attempts with scores
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
)
async def get_progress_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select, func, cast, Date
    from app.models.project import Project
    from app.models.conversation import Conversation
    from app.models.quiz_attempt import QuizAttempt
    from app.models.knowledge_state import KnowledgeState

    knowledge_service = KnowledgeService(db)
    knowledge_stats = await knowledge_service.get_user_stats(current_user.id)

    result = await db.execute(
        select(func.count(Project.id)).where(Project.user_id == current_user.id)
    )
    total_projects = result.scalar() or 0

    result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.user_id == current_user.id)
    )
    total_conversations = result.scalar() or 0

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

    # Quizzes this week
    week_start = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.user_id == current_user.id,
            QuizAttempt.completed_at.isnot(None),
            QuizAttempt.completed_at >= week_start,
        )
    )
    quizzes_this_week = result.scalar() or 0

    # Study streak: consecutive days with quiz activity or conversations
    result = await db.execute(
        select(func.distinct(cast(QuizAttempt.completed_at, Date))).where(
            QuizAttempt.user_id == current_user.id,
            QuizAttempt.completed_at.isnot(None),
        )
    )
    quiz_dates = {r[0] for r in result.all()}

    result = await db.execute(
        select(func.distinct(cast(Conversation.created_at, Date))).where(
            Conversation.user_id == current_user.id,
        )
    )
    conv_dates = {r[0] for r in result.all()}

    all_dates = sorted(quiz_dates | conv_dates, reverse=True)
    study_streak = 0
    today = datetime.now(timezone.utc).date()
    check_date = today
    for d in all_dates:
        if d == check_date:
            study_streak += 1
            check_date -= timedelta(days=1)
        elif d < check_date:
            break

    # Mastery by project
    result = await db.execute(
        select(
            Project.id,
            Project.name,
            func.avg(KnowledgeState.mastery_score),
            func.count(KnowledgeState.id),
        )
        .join(KnowledgeState, KnowledgeState.project_id == Project.id)
        .where(
            KnowledgeState.user_id == current_user.id,
            KnowledgeState.topic_id.isnot(None),
        )
        .group_by(Project.id, Project.name)
        .order_by(func.avg(KnowledgeState.mastery_score).desc())
    )
    mastery_by_project = [
        {
            "project_id": str(r[0]),
            "project_name": r[1],
            "mastery": round(float(r[2] or 0), 1),
            "topics_count": r[3],
        }
        for r in result.all()
    ]

    return {
        "total_projects": total_projects,
        "total_conversations": total_conversations,
        "total_quiz_attempts": total_quiz_attempts,
        "avg_quiz_score": round(avg_quiz_score, 1),
        "knowledge": knowledge_stats,
        "study_streak": study_streak,
        "quizzes_this_week": quizzes_this_week,
        "mastery_by_project": mastery_by_project,
    }


# ============================================================
# QUIZ HISTORY
# ============================================================

@router.get(
    "/progress/quiz-history",
    summary="Get recent quiz attempts with scores",
)
async def get_quiz_history(
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.quiz_attempt import QuizAttempt
    from app.models.quiz import Quiz
    from app.models.project import Project

    result = await db.execute(
        select(
            QuizAttempt.id,
            QuizAttempt.score,
            QuizAttempt.max_score,
            QuizAttempt.percentage,
            QuizAttempt.passed,
            QuizAttempt.time_taken_seconds,
            QuizAttempt.completed_at,
            Quiz.title.label("quiz_title"),
            Quiz.difficulty.label("difficulty"),
            Project.name.label("project_name"),
        )
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .join(Project, Quiz.project_id == Project.id)
        .where(
            QuizAttempt.user_id == current_user.id,
            QuizAttempt.completed_at.isnot(None),
        )
        .order_by(QuizAttempt.completed_at.desc())
        .limit(limit)
    )

    return [
        {
            "id": str(r.id),
            "quiz_title": r.quiz_title,
            "project_name": r.project_name,
            "score": r.score,
            "max_score": r.max_score,
            "percentage": round(r.percentage, 1) if r.percentage else 0,
            "passed": r.passed,
            "difficulty": r.difficulty.value if r.difficulty else "medium",
            "time_taken_seconds": r.time_taken_seconds,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in result.all()
    ]
