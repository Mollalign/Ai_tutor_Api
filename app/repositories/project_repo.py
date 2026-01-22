"""
Project Repository

Data access layer for Project model.
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.repositories.base import BaseRepository
from app.models.project import Project


class ProjectRepository(BaseRepository[Project]):
    """Repository for Project model."""

    def __init__(self, db: AsyncSession):
        super().__init__(Project, db)

    async def get_all_for_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100
    ) -> List[Project]:
        """
        Get all projects for a specific user.
        
        Args:
            user_id: The owner's user ID
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return
            
        Returns:
            List of projects ordered by updated_at descending
        """
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_for_user(self, user_id: UUID) -> int:
        """
        Count projects for a specific user.
        
        Args:
            user_id: The owner's user ID
            
        Returns:
            Count of projects
        """
        stmt = select(func.count(self.model.id)).where(self.model.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar() or 0    