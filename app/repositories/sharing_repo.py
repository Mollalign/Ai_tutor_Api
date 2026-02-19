"""
Sharing Repository

Data access layer for conversation sharing:
- SharedConversation: Public link sharing
- ConversationAccess: Private user sharing
- ConversationFork: Tracking forked conversations
"""

import secrets
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.repositories.base import BaseRepository
from app.models.shared_conversation import (
    SharedConversation,
    ConversationAccess,
    ConversationFork,
    ShareType,
)
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User


class SharedConversationRepository(BaseRepository[SharedConversation]):
    """Repository for public share links."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(SharedConversation, db)
    
    async def create_share(
        self,
        conversation_id: UUID,
        user_id: UUID,
        title: Optional[str] = None,
        share_type: ShareType = ShareType.PUBLIC_LINK,
        allow_replies: bool = True,
        expires_in_days: Optional[int] = None,
    ) -> SharedConversation:
        """
        Create a new share link for a conversation.
        
        Args:
            conversation_id: Conversation to share
            user_id: User creating the share
            title: Custom title for shared view
            share_type: PUBLIC_LINK or PRIVATE
            allow_replies: Whether recipients can fork
            expires_in_days: Days until expiration (None = never)
        
        Returns:
            Created SharedConversation
        """
        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        return await self.create(
            conversation_id=conversation_id,
            shared_by_user_id=user_id,
            share_token=secrets.token_urlsafe(32),
            title=title,
            share_type=share_type,
            allow_replies=allow_replies,
            expires_at=expires_at,
        )
    
    async def get_by_token(self, token: str) -> Optional[SharedConversation]:
        """Get a share by its unique token."""
        stmt = (
            select(self.model)
            .where(self.model.share_token == token)
            .options(selectinload(self.model.conversation))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_active_by_token(self, token: str) -> Optional[SharedConversation]:
        """Get an active, non-expired share by token."""
        share = await self.get_by_token(token)
        
        if share and share.is_accessible:
            return share
        return None
    
    async def get_user_shares(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
        active_only: bool = True,
    ) -> List[SharedConversation]:
        """
        Get all shares created by a user.
        
        Args:
            user_id: User who created the shares
            skip: Pagination offset
            limit: Max results
            active_only: Only return active shares
        
        Returns:
            List of SharedConversation
        """
        stmt = (
            select(self.model)
            .where(self.model.shared_by_user_id == user_id)
        )
        
        if active_only:
            stmt = stmt.where(self.model.is_active == True)
        
        stmt = (
            stmt
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_conversation_shares(
        self,
        conversation_id: UUID,
    ) -> List[SharedConversation]:
        """Get all shares for a specific conversation."""
        stmt = (
            select(self.model)
            .where(self.model.conversation_id == conversation_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def increment_view_count(self, share_id: UUID) -> None:
        """Increment the view count for a share."""
        share = await self.get_by_id(share_id)
        if share:
            share.view_count += 1
            await self.db.commit()
    
    async def deactivate(self, share_id: UUID) -> bool:
        """Deactivate a share link."""
        share = await self.get_by_id(share_id)
        if share:
            share.is_active = False
            await self.db.commit()
            return True
        return False


class ConversationAccessRepository(BaseRepository[ConversationAccess]):
    """Repository for private sharing with specific users."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(ConversationAccess, db)
    
    async def grant_access(
        self,
        conversation_id: UUID,
        user_id: UUID,
        granted_by_user_id: UUID,
        can_reply: bool = True,
    ) -> ConversationAccess:
        """
        Grant a user access to a conversation.
        
        Args:
            conversation_id: Conversation to share
            user_id: User receiving access
            granted_by_user_id: User granting access
            can_reply: Whether recipient can fork
        
        Returns:
            Created ConversationAccess
        """
        # Check if access already exists
        existing = await self.get_user_access(conversation_id, user_id)
        if existing:
            # Update existing access
            existing.can_reply = can_reply
            existing.is_active = True
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        
        return await self.create(
            conversation_id=conversation_id,
            user_id=user_id,
            granted_by_user_id=granted_by_user_id,
            can_reply=can_reply,
        )
    
    async def get_user_access(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> Optional[ConversationAccess]:
        """Check if a user has access to a conversation."""
        stmt = select(self.model).where(
            and_(
                self.model.conversation_id == conversation_id,
                self.model.user_id == user_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def has_access(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Check if a user has active access to a conversation."""
        access = await self.get_user_access(conversation_id, user_id)
        return access is not None and access.is_active
    
    async def get_conversation_access_list(
        self,
        conversation_id: UUID,
    ) -> List[ConversationAccess]:
        """Get all users with access to a conversation."""
        stmt = (
            select(self.model)
            .where(self.model.conversation_id == conversation_id)
            .options(selectinload(self.model.user))
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_shared_with_me(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
        active_only: bool = True,
    ) -> List[ConversationAccess]:
        """
        Get all conversations shared with a user.
        
        Returns list of access grants with conversation info.
        """
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .options(
                selectinload(self.model.conversation),
                selectinload(self.model.granted_by),
            )
        )
        
        if active_only:
            stmt = stmt.where(self.model.is_active == True)
        
        stmt = (
            stmt
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def revoke_access(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Revoke a user's access to a conversation."""
        access = await self.get_user_access(conversation_id, user_id)
        if access:
            access.is_active = False
            await self.db.commit()
            return True
        return False


class ConversationForkRepository(BaseRepository[ConversationFork]):
    """Repository for tracking forked conversations."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(ConversationFork, db)
    
    async def create_fork(
        self,
        original_conversation_id: UUID,
        forked_conversation_id: UUID,
        forked_by_user_id: UUID,
        forked_at_message_id: Optional[UUID] = None,
    ) -> ConversationFork:
        """
        Record a conversation fork.
        
        Args:
            original_conversation_id: Source conversation
            forked_conversation_id: New forked conversation
            forked_by_user_id: User who created the fork
            forked_at_message_id: Last message from original
        
        Returns:
            Created ConversationFork
        """
        return await self.create(
            original_conversation_id=original_conversation_id,
            forked_conversation_id=forked_conversation_id,
            forked_by_user_id=forked_by_user_id,
            forked_at_message_id=forked_at_message_id,
        )
    
    async def get_fork_info(
        self,
        conversation_id: UUID,
    ) -> Optional[ConversationFork]:
        """Get fork info for a conversation (if it's a fork)."""
        stmt = (
            select(self.model)
            .where(self.model.forked_conversation_id == conversation_id)
            .options(selectinload(self.model.original_conversation))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_forks_of_conversation(
        self,
        conversation_id: UUID,
    ) -> List[ConversationFork]:
        """Get all forks created from a conversation."""
        stmt = (
            select(self.model)
            .where(self.model.original_conversation_id == conversation_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def count_forks(
        self,
        conversation_id: UUID,
    ) -> int:
        """Count the number of forks from a conversation."""
        stmt = (
            select(func.count(self.model.id))
            .where(self.model.original_conversation_id == conversation_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0
