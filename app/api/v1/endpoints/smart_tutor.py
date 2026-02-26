"""
Smart Tutor Endpoints

Provides intelligent, adaptive learning features:
- Adaptive quiz difficulty recommendations
- Smart topic suggestions based on knowledge gaps
- AI-generated study plans
- Exam readiness scoring
- Cross-topic connection discovery
- Learning style detection
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.smart_tutor_service import SmartTutorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/smart", tags=["Smart Tutor"])


def get_service(db: AsyncSession = Depends(get_db)) -> SmartTutorService:
    return SmartTutorService(db)


# ================================================================
# ADAPTIVE DIFFICULTY
# ================================================================

@router.get(
    "/adaptive-difficulty/{project_id}",
    summary="Get recommended quiz difficulty for a project",
)
async def adaptive_difficulty(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SmartTutorService = Depends(get_service),
):
    try:
        return await service.get_adaptive_difficulty(current_user.id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ================================================================
# SMART SUGGESTIONS
# ================================================================

@router.get(
    "/suggestions",
    summary="Get smart topic suggestions based on knowledge gaps",
)
async def smart_suggestions(
    limit: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    service: SmartTutorService = Depends(get_service),
):
    return await service.get_smart_suggestions(current_user.id, limit=limit)


# ================================================================
# STUDY PLAN
# ================================================================

@router.get(
    "/study-plan/{project_id}",
    summary="Generate an AI-powered study plan for a project",
)
async def study_plan(
    project_id: UUID,
    exam_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    daily_hours: float = Query(default=2.0, ge=0.5, le=12),
    current_user: User = Depends(get_current_user),
    service: SmartTutorService = Depends(get_service),
):
    try:
        return await service.generate_study_plan(
            user_id=current_user.id,
            project_id=project_id,
            exam_date=exam_date,
            daily_hours=daily_hours,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ================================================================
# EXAM READINESS
# ================================================================

@router.get(
    "/readiness/{project_id}",
    summary="Get exam readiness score for a project",
)
async def exam_readiness(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SmartTutorService = Depends(get_service),
):
    try:
        return await service.get_exam_readiness(current_user.id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ================================================================
# CROSS-TOPIC CONNECTIONS
# ================================================================

@router.get(
    "/connections/{project_id}",
    summary="Discover cross-topic connections with other projects",
)
async def cross_connections(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SmartTutorService = Depends(get_service),
):
    try:
        return await service.get_cross_connections(current_user.id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ================================================================
# LEARNING STYLE
# ================================================================

@router.get(
    "/learning-style",
    summary="Detect the user's learning style from interaction patterns",
)
async def learning_style(
    current_user: User = Depends(get_current_user),
    service: SmartTutorService = Depends(get_service),
):
    return await service.detect_learning_style(current_user.id)
