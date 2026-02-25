"""
Quiz Endpoints

HTTP API for quiz generation, taking, and review.

Endpoints:
----------
- POST   /projects/{project_id}/quizzes/generate  - Generate a quiz from documents
- GET    /projects/{project_id}/quizzes            - List quizzes for a project
- GET    /quizzes/{quiz_id}                        - Get quiz (for taking)
- POST   /quizzes/{quiz_id}/submit                 - Submit quiz answers
- GET    /quizzes/{quiz_id}/attempts               - List user's attempts
- GET    /quizzes/attempts/{attempt_id}            - Get attempt result detail
- DELETE /quizzes/{quiz_id}                        - Delete a quiz
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.quiz import (
    QuizGenerateRequest,
    QuizSubmitRequest,
    QuizDetailResponse,
    QuizListResponse,
    QuizResultDetailResponse,
    AttemptListResponse,
)
from app.services.quiz_service import (
    QuizService,
    QuizServiceError,
    QuizNotFoundError,
    ProjectNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Quizzes"])


def get_quiz_service(db: AsyncSession = Depends(get_db)) -> QuizService:
    return QuizService(db)


# ============================================================
# GENERATE QUIZ
# ============================================================

@router.post(
    "/projects/{project_id}/quizzes/generate",
    response_model=QuizDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a quiz from project documents",
    description="""
    Uses AI to generate a quiz based on uploaded project documents.
    
    The AI reads the document content and creates questions at the
    specified difficulty level. Requires at least one processed document.
    """,
)
async def generate_quiz(
    project_id: UUID,
    request: QuizGenerateRequest,
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
):
    try:
        return await service.generate_quiz(
            project_id=project_id,
            user_id=current_user.id,
            request=request,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    except QuizServiceError as e:
        logger.error(f"Quiz generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ============================================================
# LIST QUIZZES
# ============================================================

@router.get(
    "/projects/{project_id}/quizzes",
    response_model=QuizListResponse,
    summary="List quizzes for a project",
)
async def list_quizzes(
    project_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
):
    try:
        quizzes, total = await service.list_quizzes(
            project_id=project_id,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )
        return QuizListResponse(quizzes=quizzes, total=total)
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


# ============================================================
# GET QUIZ (for taking)
# ============================================================

@router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizDetailResponse,
    summary="Get quiz with questions",
    description="Returns the quiz with all questions (without correct answers) for taking.",
)
async def get_quiz(
    quiz_id: UUID,
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
):
    try:
        return await service.get_quiz(
            quiz_id=quiz_id,
            user_id=current_user.id,
        )
    except QuizNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz not found",
        )


# ============================================================
# SUBMIT QUIZ
# ============================================================

@router.post(
    "/quizzes/{quiz_id}/submit",
    response_model=QuizResultDetailResponse,
    summary="Submit quiz answers",
    description="""
    Submit answers for a quiz. Creates a new attempt, grades all
    answers, and returns detailed results with correct answers
    and explanations.
    """,
)
async def submit_quiz(
    quiz_id: UUID,
    submission: QuizSubmitRequest,
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.submit_quiz(
            quiz_id=quiz_id,
            user_id=current_user.id,
            submission=submission,
        )

        # Send push notification if user has FCM token and quiz_results enabled
        try:
            from sqlalchemy import select as sa_select
            from app.models.notification_preference import NotificationPreference
            from app.models.quiz import Quiz
            from app.services.notification_service import send_quiz_result_notification

            pref_result = await db.execute(
                sa_select(NotificationPreference).where(
                    NotificationPreference.user_id == current_user.id
                )
            )
            pref = pref_result.scalar_one_or_none()
            should_notify = pref is None or pref.quiz_results_enabled

            if should_notify:
                quiz_result = await db.execute(
                    sa_select(Quiz.title).where(Quiz.id == quiz_id)
                )
                quiz_title = quiz_result.scalar_one_or_none() or "Quiz"

                await send_quiz_result_notification(
                    fcm_token=current_user.fcm_token,
                    quiz_title=quiz_title,
                    score_pct=result.percentage,
                    passed=result.passed,
                    db=db,
                    user_id=current_user.id,
                )
        except Exception as notify_err:
            logger.warning("Quiz notification failed: %s", notify_err)

        return result
    except QuizNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz not found",
        )
    except QuizServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ============================================================
# LIST ATTEMPTS
# ============================================================

@router.get(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptListResponse,
    summary="List quiz attempts",
)
async def list_attempts(
    quiz_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
):
    try:
        attempts, total = await service.list_attempts(
            quiz_id=quiz_id,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )
        return AttemptListResponse(attempts=attempts, total=total)
    except QuizNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz not found",
        )


# ============================================================
# GET ATTEMPT RESULT
# ============================================================

@router.get(
    "/quizzes/attempts/{attempt_id}",
    response_model=QuizResultDetailResponse,
    summary="Get detailed attempt results",
    description="Returns the full quiz result with per-question breakdown, correct answers, and explanations.",
)
async def get_attempt_result(
    attempt_id: UUID,
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
):
    try:
        return await service.get_attempt_result(
            attempt_id=attempt_id,
            user_id=current_user.id,
        )
    except QuizNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attempt not found",
        )


# ============================================================
# DELETE QUIZ
# ============================================================

@router.delete(
    "/quizzes/{quiz_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a quiz",
)
async def delete_quiz(
    quiz_id: UUID,
    current_user: User = Depends(get_current_user),
    service: QuizService = Depends(get_quiz_service),
):
    try:
        await service.delete_quiz(
            quiz_id=quiz_id,
            user_id=current_user.id,
        )
    except QuizNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz not found",
        )
