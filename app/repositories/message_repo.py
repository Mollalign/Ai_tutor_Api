"""
Message Repository

Data access layer for Message model.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.message import Message, MessageRole


class MessageRepository(BaseRepository[Message]):
    """Repository for Message model."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(Message, db)
    
    async def get_conversation_messages(
        self,
        conversation_id: UUID,
        limit: Optional[int] = None,
        before_id: Optional[UUID] = None
    ) -> List[Message]:
        """
        Get messages for a conversation.
        
        Args:
            conversation_id: Conversation ID
            limit: Maximum messages (None = all)
            before_id: Get messages before this ID (for pagination)
        
        Returns:
            Messages ordered by created_at ascending
        """
        stmt = (
            select(self.model)
            .where(self.model.conversation_id == conversation_id)
        )
        
        if before_id:
            # Get the message to find its timestamp
            before_msg = await self.get_by_id(before_id)
            if before_msg:
                stmt = stmt.where(self.model.created_at < before_msg.created_at)
        
        stmt = stmt.order_by(self.model.created_at.asc())
        
        if limit:
            stmt = stmt.limit(limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_recent_messages(
        self,
        conversation_id: UUID,
        limit: int = 10
    ) -> List[Message]:
        """
        Get most recent messages (for context building).
        
        Returns in chronological order (oldest first).
        """
        # Get recent messages in reverse order
        stmt = (
            select(self.model)
            .where(self.model.conversation_id == conversation_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        messages = list(result.scalars().all())
        
        # Reverse to chronological order
        return list(reversed(messages))
    
    async def create_message(
        self,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
        sources: Optional[dict] = None,
        tokens_used: Optional[int] = None,
        attachments: Optional[dict] = None
    ) -> Message:
        """
        Create a new message.
        
        Args:
            conversation_id: Parent conversation
            role: Message role (user, assistant, system)
            content: Message text
            sources: Citation data (for assistant messages)
            tokens_used: Token count (for assistant messages)
            attachments: Additional data (images, URLs, etc.)
        
        Returns:
            Created message
        """
        return await self.create(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=sources,
            tokens_used=tokens_used,
            attachments=attachments
        )
    
    async def count_conversation_messages(
        self,
        conversation_id: UUID
    ) -> int:
        """Count messages in a conversation."""
        stmt = select(func.count(self.model.id)).where(
            self.model.conversation_id == conversation_id
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0
    
    async def get_total_tokens(
        self,
        conversation_id: UUID
    ) -> int:
        """Get total tokens used in a conversation."""
        stmt = (
            select(func.sum(self.model.tokens_used))
            .where(self.model.conversation_id == conversation_id)
            .where(self.model.tokens_used.isnot(None))
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0
    
    async def delete_conversation_messages(
        self,
        conversation_id: UUID
    ) -> int:
        """Delete all messages in a conversation."""
        messages = await self.get_conversation_messages(conversation_id)
        count = len(messages)
        
        for msg in messages:
            await self.db.delete(msg)
        
        await self.db.commit()
        return count