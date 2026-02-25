"""
Knowledge State Service

Tracks and updates student mastery based on quiz results.
Uses a simple Bayesian-like update: new_mastery blends prior mastery
with quiz performance using exponential smoothing.
"""

import logging
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_state import KnowledgeState
from app.repositories.knowledge_repo import KnowledgeStateRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.topic_repo import TopicRepository
from app.schemas.knowledge import (
    KnowledgeStateResponse,
    ProjectKnowledgeResponse,
)

logger = logging.getLogger(__name__)

LEARNING_RATE = 0.3


class KnowledgeServiceError(Exception):
    pass


class ProjectNotFoundError(KnowledgeServiceError):
    pass


def _mastery_status(score: float) -> str:
    if score >= 0.8:
        return "mastered"
    if score >= 0.4:
        return "learning"
    if score > 0.0:
        return "struggling"
    return "not_started"


class KnowledgeService:
    """Service for knowledge state tracking."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.knowledge_repo = KnowledgeStateRepository(db)
        self.project_repo = ProjectRepository(db)
        self.topic_repo = TopicRepository(db)

    # ============================================================
    # UPDATE FROM QUIZ RESULT
    # ============================================================

    async def update_from_quiz(
        self,
        user_id: UUID,
        project_id: UUID,
        question_results: List[dict],
    ) -> None:
        """
        Update knowledge states based on quiz question results.
        
        Each entry in question_results should have:
          - subtopic_id (optional UUID)
          - is_correct (bool)
        """
        for qr in question_results:
            subtopic_id = qr.get("subtopic_id")
            is_correct = qr.get("is_correct", False)

            state = await self.knowledge_repo.get_or_create(
                user_id=user_id,
                project_id=project_id,
                subtopic_id=subtopic_id,
            )

            state.total_attempts += 1
            if is_correct:
                state.correct_count += 1

            performance = state.correct_count / state.total_attempts if state.total_attempts > 0 else 0
            state.mastery_score = (
                (1 - LEARNING_RATE) * state.mastery_score
                + LEARNING_RATE * performance
            )
            state.mastery_score = max(0.0, min(1.0, state.mastery_score))
            state.status = _mastery_status(state.mastery_score)
            state.last_reviewed = datetime.now(timezone.utc)

        await self.db.commit()

    # ============================================================
    # GET PROJECT KNOWLEDGE
    # ============================================================

    async def get_project_knowledge(
        self,
        project_id: UUID,
        user_id: UUID,
    ) -> ProjectKnowledgeResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundError("Project not found")

        states = await self.knowledge_repo.get_by_user_project(user_id, project_id)

        topics = await self.topic_repo.get_by_project(project_id)
        topic_map = {str(t.id): t for t in topics}
        subtopic_map = {}
        for t in topics:
            for st in (t.subtopics or []):
                subtopic_map[str(st.id)] = (st, t)

        state_responses = []
        for s in states:
            topic_name = None
            subtopic_name = None
            if s.topic_id and str(s.topic_id) in topic_map:
                topic_name = topic_map[str(s.topic_id)].name
            if s.subtopic_id and str(s.subtopic_id) in subtopic_map:
                st_obj, t_obj = subtopic_map[str(s.subtopic_id)]
                subtopic_name = st_obj.name
                if not topic_name:
                    topic_name = t_obj.name

            state_responses.append(
                KnowledgeStateResponse(
                    id=s.id,
                    user_id=s.user_id,
                    project_id=s.project_id,
                    topic_id=s.topic_id,
                    topic_name=topic_name,
                    subtopic_id=s.subtopic_id,
                    subtopic_name=subtopic_name,
                    mastery_score=s.mastery_score,
                    status=s.status,
                    correct_count=s.correct_count,
                    total_attempts=s.total_attempts,
                    misconceptions=s.misconceptions or {},
                    last_reviewed=s.last_reviewed,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
            )

        total_topics = len(topics)
        mastered = sum(1 for s in state_responses if s.mastery_score >= 0.8)
        in_progress = sum(1 for s in state_responses if 0.0 < s.mastery_score < 0.8)
        not_started = total_topics - mastered - in_progress

        overall = 0.0
        if state_responses:
            overall = sum(s.mastery_score for s in state_responses) / len(state_responses)

        total_correct = sum(s.correct_count for s in state_responses)
        total_attempts = sum(s.total_attempts for s in state_responses)

        return ProjectKnowledgeResponse(
            project_id=project_id,
            overall_mastery=overall,
            total_topics=total_topics,
            mastered_topics=mastered,
            in_progress_topics=in_progress,
            not_started_topics=max(0, not_started),
            total_correct=total_correct,
            total_attempts=total_attempts,
            topic_states=state_responses,
        )

    # ============================================================
    # GET USER OVERALL STATS
    # ============================================================

    async def get_user_stats(self, user_id: UUID) -> dict:
        return await self.knowledge_repo.get_user_overall_stats(user_id)
