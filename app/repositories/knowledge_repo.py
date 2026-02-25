"""
Knowledge State Repository

Data access layer for KnowledgeState model.
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.repositories.base import BaseRepository
from app.models.knowledge_state import KnowledgeState


class KnowledgeStateRepository(BaseRepository[KnowledgeState]):
    """Repository for KnowledgeState model."""

    def __init__(self, db: AsyncSession):
        super().__init__(KnowledgeState, db)

    async def get_by_user_project(
        self,
        user_id: UUID,
        project_id: UUID,
    ) -> List[KnowledgeState]:
        stmt = (
            select(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.project_id == project_id,
            )
            .order_by(self.model.updated_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create(
        self,
        user_id: UUID,
        project_id: UUID,
        topic_id: Optional[UUID] = None,
        subtopic_id: Optional[UUID] = None,
    ) -> KnowledgeState:
        stmt = select(self.model).where(
            self.model.user_id == user_id,
            self.model.project_id == project_id,
            self.model.topic_id == topic_id if topic_id else self.model.topic_id.is_(None),
            self.model.subtopic_id == subtopic_id if subtopic_id else self.model.subtopic_id.is_(None),
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return existing

        return await self.create(
            user_id=user_id,
            project_id=project_id,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            mastery_score=0.0,
            status="not_started",
            correct_count=0,
            total_attempts=0,
            misconceptions={},
        )

    async def get_user_overall_stats(
        self,
        user_id: UUID,
    ) -> dict:
        """Get aggregated stats across all projects."""
        stmt = select(
            func.count(self.model.id),
            func.avg(self.model.mastery_score),
            func.sum(self.model.correct_count),
            func.sum(self.model.total_attempts),
        ).where(
            self.model.user_id == user_id,
            self.model.topic_id.isnot(None),
        )
        result = await self.db.execute(stmt)
        row = result.one_or_none()

        if not row:
            return {
                "total_topics": 0,
                "avg_mastery": 0.0,
                "total_correct": 0,
                "total_attempts": 0,
            }

        return {
            "total_topics": row[0] or 0,
            "avg_mastery": float(row[1] or 0),
            "total_correct": int(row[2] or 0),
            "total_attempts": int(row[3] or 0),
        }
