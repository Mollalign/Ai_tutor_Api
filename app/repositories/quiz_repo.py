"""
Quiz Repository

Data access layer for Quiz, QuizQuestion, QuizAttempt, and QuizResponse models.
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.repositories.base import BaseRepository
from app.models.quiz import Quiz
from app.models.quiz_question import QuizQuestion
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse


class QuizRepository(BaseRepository[Quiz]):
    """Repository for Quiz model."""

    def __init__(self, db: AsyncSession):
        super().__init__(Quiz, db)

    async def get_by_project(
        self,
        project_id: UUID,
        skip: int = 0,
        limit: int = 20
    ) -> List[Quiz]:
        stmt = (
            select(self.model)
            .where(self.model.project_id == project_id)
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        stmt = (
            select(func.count(self.model.id))
            .where(self.model.project_id == project_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_with_questions(self, quiz_id: UUID) -> Optional[Quiz]:
        stmt = (
            select(self.model)
            .options(selectinload(self.model.questions))
            .where(self.model.id == quiz_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class QuizQuestionRepository(BaseRepository[QuizQuestion]):
    """Repository for QuizQuestion model."""

    def __init__(self, db: AsyncSession):
        super().__init__(QuizQuestion, db)

    async def create_bulk(self, questions: List[dict]) -> List[QuizQuestion]:
        instances = []
        for q_data in questions:
            instance = QuizQuestion(**q_data)
            self.db.add(instance)
            instances.append(instance)
        await self.db.flush()
        for inst in instances:
            await self.db.refresh(inst)
        return instances

    async def get_by_quiz(self, quiz_id: UUID) -> List[QuizQuestion]:
        stmt = (
            select(self.model)
            .where(self.model.quiz_id == quiz_id)
            .order_by(self.model.display_order)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class QuizAttemptRepository(BaseRepository[QuizAttempt]):
    """Repository for QuizAttempt model."""

    def __init__(self, db: AsyncSession):
        super().__init__(QuizAttempt, db)

    async def get_user_attempts(
        self,
        user_id: UUID,
        quiz_id: UUID,
        skip: int = 0,
        limit: int = 20
    ) -> List[QuizAttempt]:
        stmt = (
            select(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.quiz_id == quiz_id
            )
            .order_by(self.model.started_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_user_attempts(self, user_id: UUID, quiz_id: UUID) -> int:
        stmt = (
            select(func.count(self.model.id))
            .where(
                self.model.user_id == user_id,
                self.model.quiz_id == quiz_id
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_with_responses(self, attempt_id: UUID) -> Optional[QuizAttempt]:
        stmt = (
            select(self.model)
            .options(selectinload(self.model.responses))
            .where(self.model.id == attempt_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_best_attempt(self, user_id: UUID, quiz_id: UUID) -> Optional[QuizAttempt]:
        stmt = (
            select(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.quiz_id == quiz_id,
                self.model.completed_at.isnot(None)
            )
            .order_by(self.model.percentage.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class QuizResponseRepository(BaseRepository[QuizResponse]):
    """Repository for QuizResponse model."""

    def __init__(self, db: AsyncSession):
        super().__init__(QuizResponse, db)

    async def create_bulk(self, responses: List[dict]) -> List[QuizResponse]:
        instances = []
        for r_data in responses:
            instance = QuizResponse(**r_data)
            self.db.add(instance)
            instances.append(instance)
        await self.db.flush()
        for inst in instances:
            await self.db.refresh(inst)
        return instances

    async def get_by_attempt(self, attempt_id: UUID) -> List[QuizResponse]:
        stmt = (
            select(self.model)
            .where(self.model.attempt_id == attempt_id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
