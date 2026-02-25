"""
Topic Repository

Data access layer for Topic and Subtopic models.
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.repositories.base import BaseRepository
from app.models.topic import Topic, Subtopic


class TopicRepository(BaseRepository[Topic]):
    """Repository for Topic model."""

    def __init__(self, db: AsyncSession):
        super().__init__(Topic, db)

    async def get_by_project(
        self,
        project_id: UUID,
    ) -> List[Topic]:
        stmt = (
            select(self.model)
            .options(selectinload(self.model.subtopics))
            .where(self.model.project_id == project_id)
            .order_by(self.model.display_order)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_by_project(self, project_id: UUID) -> int:
        stmt = (
            select(func.count(self.model.id))
            .where(self.model.project_id == project_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def delete_by_project(self, project_id: UUID) -> int:
        stmt = (
            delete(self.model)
            .where(self.model.project_id == project_id)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount


class SubtopicRepository(BaseRepository[Subtopic]):
    """Repository for Subtopic model."""

    def __init__(self, db: AsyncSession):
        super().__init__(Subtopic, db)

    async def get_by_topic(self, topic_id: UUID) -> List[Subtopic]:
        stmt = (
            select(self.model)
            .where(self.model.topic_id == topic_id)
            .order_by(self.model.display_order)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
