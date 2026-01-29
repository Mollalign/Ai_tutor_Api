"""
Conversation Repository

Data access layer for Conversation model.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.repositories.base import BaseRepository
from app.models.conversation import Conversation
from app.models.message import Message


class ConversationRepository(BaseRepository[Conversation]):
    """Repository for Conversation model."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(Conversation, db)
    
    async def get_with_messages(
        self,
        conversation_id: UUID
    ) -> Optional[Conversation]:
        """
        Get conversation with all messages loaded.
        
        Uses eager loading to fetch messages in one query.
        """
        stmt = (
            select(self.model)
            .options(selectinload(self.model.messages))
            .where(self.model.id == conversation_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_user_conversations(
        self,
        user_id: UUID,
        project_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[Conversation]:
        """
        Get conversations for a user.
        
        Args:
            user_id: User's ID
            project_id: Optional filter by project (None = all)
            skip: Pagination offset
            limit: Maximum results
        
        Returns:
            List ordered by most recent activity
        """
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
        )
        
        # Filter by project if specified
        if project_id is not None:
            stmt = stmt.where(self.model.project_id == project_id)
        
        # Order by updated_at descending (most recent first)
        stmt = stmt.order_by(desc(self.model.updated_at))
        stmt = stmt.offset(skip).limit(limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_quick_chats(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50
    ) -> List[Conversation]:
        """Get conversations without a project (quick chats)."""
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .where(self.model.project_id.is_(None))
            .order_by(desc(self.model.updated_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def count_user_conversations(
        self,
        user_id: UUID,
        project_id: Optional[UUID] = None
    ) -> int:
        """Count conversations for a user."""
        stmt = select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        )
        
        if project_id is not None:
            stmt = stmt.where(self.model.project_id == project_id)
        
        result = await self.db.execute(stmt)
        return result.scalar() or 0
    
    async def get_message_count(self, conversation_id: UUID) -> int:
        """Get number of messages in a conversation."""
        stmt = select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0
    
    async def get_last_message_time(
        self,
        conversation_id: UUID
    ) -> Optional[datetime]:
        """Get timestamp of last message."""
        stmt = (
            select(func.max(Message.created_at))
            .where(Message.conversation_id == conversation_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar()
    
    async def touch(self, conversation_id: UUID) -> None:
        """
        Update conversation's updated_at timestamp.
        
        Called when a new message is added.
        """
        conversation = await self.get_by_id(conversation_id)
        if conversation:
            # SQLAlchemy will auto-update updated_at
            await self.db.commit()
            await self.db.refresh(conversation)