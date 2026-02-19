"""
Sharing Service

Business logic for conversation sharing:
- Create public share links
- Share privately with specific users
- Fork conversations for recipients
- Manage share permissions

Key Concepts:
------------
1. Public Shares: Anyone with the link can view
2. Private Shares: Only invited users can view
3. Forking: When recipients reply, they get their own copy
"""

import logging
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shared_conversation import (
    SharedConversation,
    ConversationAccess,
    ConversationFork,
    ShareType,
)
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.repositories.sharing_repo import (
    SharedConversationRepository,
    ConversationAccessRepository,
    ConversationForkRepository,
)
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.user_repo import UserRepository
from app.schemas.sharing import (
    SharedConversationResponse,
    ConversationAccessResponse,
    SharedConversationPreview,
    SharedConversationFull,
    ConversationForkResponse,
    ShareStatsResponse,
)
from app.schemas.conversation import MessageResponse
from app.core.config import settings

logger = logging.getLogger(__name__)


class SharingServiceError(Exception):
    """Base exception for sharing service errors."""
    pass


class ShareNotFoundError(SharingServiceError):
    """Share not found or expired."""
    pass


class AccessDeniedError(SharingServiceError):
    """User doesn't have permission for this action."""
    pass


class SharingService:
    """
    Service for conversation sharing operations.
    
    Handles:
    - Creating public/private shares
    - Checking access permissions
    - Forking conversations
    - Managing share settings
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.share_repo = SharedConversationRepository(db)
        self.access_repo = ConversationAccessRepository(db)
        self.fork_repo = ConversationForkRepository(db)
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.user_repo = UserRepository(db)
    
    # ============================================================
    # PUBLIC SHARE LINKS
    # ============================================================
    
    async def create_public_share(
        self,
        conversation_id: UUID,
        user_id: UUID,
        title: Optional[str] = None,
        allow_replies: bool = True,
        expires_in_days: Optional[int] = None,
    ) -> SharedConversationResponse:
        """
        Create a public share link for a conversation.
        
        Args:
            conversation_id: Conversation to share
            user_id: User creating the share (must own conversation)
            title: Custom title for shared view
            allow_replies: Allow viewers to fork and continue
            expires_in_days: Days until expiration
        
        Returns:
            SharedConversationResponse with share details
        
        Raises:
            AccessDeniedError: If user doesn't own the conversation
        """
        # Verify ownership
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        if not conversation or conversation.user_id != user_id:
            raise AccessDeniedError("You can only share your own conversations")
        
        # Create share
        share = await self.share_repo.create_share(
            conversation_id=conversation_id,
            user_id=user_id,
            title=title or conversation.title,
            share_type=ShareType.PUBLIC_LINK,
            allow_replies=allow_replies,
            expires_in_days=expires_in_days,
        )
        
        logger.info(f"Created public share {share.id} for conversation {conversation_id}")
        
        return self._build_share_response(share)
    
    async def get_share_by_token(
        self,
        token: str,
        increment_views: bool = True,
    ) -> SharedConversationFull:
        """
        Get a shared conversation by its token.
        
        Args:
            token: The share token from the URL
            increment_views: Whether to increment view count
        
        Returns:
            Full shared conversation with messages
        
        Raises:
            ShareNotFoundError: If share doesn't exist or is expired
        """
        share = await self.share_repo.get_active_by_token(token)
        
        if not share:
            raise ShareNotFoundError("Share not found or has expired")
        
        # Increment view count
        if increment_views:
            await self.share_repo.increment_view_count(share.id)
        
        # Get conversation with messages
        conversation = await self.conversation_repo.get_with_messages(
            share.conversation_id
        )
        
        # Get sharer info
        sharer = await self.user_repo.get_by_id(share.shared_by_user_id)
        sharer_name = sharer.full_name if sharer else "Unknown"
        
        # Build response
        messages = [
            {
                "id": str(msg.id),
                "role": msg.role.value if hasattr(msg.role, 'value') else msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in conversation.messages
        ]
        
        return SharedConversationFull(
            share_id=share.id,
            conversation_id=share.conversation_id,
            title=share.title or conversation.title,
            shared_by_name=sharer_name,
            shared_at=share.created_at,
            message_count=len(messages),
            allow_replies=share.allow_replies,
            is_socratic=conversation.is_socratic,
            preview_messages=messages[:3],
            messages=messages,
        )
    
    async def get_my_shares(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[SharedConversationResponse]:
        """Get all shares created by the current user."""
        shares = await self.share_repo.get_user_shares(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        
        return [self._build_share_response(share) for share in shares]
    
    async def update_share(
        self,
        share_id: UUID,
        user_id: UUID,
        title: Optional[str] = None,
        allow_replies: Optional[bool] = None,
        is_active: Optional[bool] = None,
    ) -> SharedConversationResponse:
        """
        Update share settings.
        
        Args:
            share_id: Share to update
            user_id: User making the update (must own share)
            title: New title
            allow_replies: Update reply permission
            is_active: Enable/disable share
        
        Returns:
            Updated share response
        """
        share = await self.share_repo.get_by_id(share_id)
        
        if not share or share.shared_by_user_id != user_id:
            raise AccessDeniedError("You can only update your own shares")
        
        update_data = {}
        if title is not None:
            update_data["title"] = title
        if allow_replies is not None:
            update_data["allow_replies"] = allow_replies
        if is_active is not None:
            update_data["is_active"] = is_active
        
        if update_data:
            share = await self.share_repo.update(share_id, **update_data)
        
        return self._build_share_response(share)
    
    async def delete_share(
        self,
        share_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Delete a share link."""
        share = await self.share_repo.get_by_id(share_id)
        
        if not share or share.shared_by_user_id != user_id:
            raise AccessDeniedError("You can only delete your own shares")
        
        return await self.share_repo.delete(share_id)
    
    # ============================================================
    # PRIVATE SHARING
    # ============================================================
    
    async def share_with_users(
        self,
        conversation_id: UUID,
        user_id: UUID,
        user_emails: List[str],
        can_reply: bool = True,
    ) -> List[ConversationAccessResponse]:
        """
        Share a conversation privately with specific users.
        
        Args:
            conversation_id: Conversation to share
            user_id: User creating the share (must own conversation)
            user_emails: Email addresses of recipients
            can_reply: Allow recipients to fork
        
        Returns:
            List of access grants
        """
        # Verify ownership
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        if not conversation or conversation.user_id != user_id:
            raise AccessDeniedError("You can only share your own conversations")
        
        access_grants = []
        
        for email in user_emails:
            # Find user by email
            recipient = await self.user_repo.get_by_email(email)
            
            if not recipient:
                logger.warning(f"User not found for email: {email}")
                continue
            
            if recipient.id == user_id:
                continue  # Skip self
            
            # Grant access
            access = await self.access_repo.grant_access(
                conversation_id=conversation_id,
                user_id=recipient.id,
                granted_by_user_id=user_id,
                can_reply=can_reply,
            )
            
            access_grants.append(ConversationAccessResponse(
                id=access.id,
                conversation_id=access.conversation_id,
                user_id=access.user_id,
                user_email=email,
                user_name=recipient.full_name,
                can_reply=access.can_reply,
                is_active=access.is_active,
                granted_at=access.created_at,
            ))
        
        logger.info(
            f"Shared conversation {conversation_id} with {len(access_grants)} users"
        )
        
        return access_grants
    
    async def get_shared_with_me(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[SharedConversationPreview]:
        """Get all conversations shared with the current user."""
        access_list = await self.access_repo.get_shared_with_me(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        
        previews = []
        for access in access_list:
            conversation = access.conversation
            granter = access.granted_by
            
            # Get message count
            msg_count = await self.conversation_repo.get_message_count(
                conversation.id
            )
            
            previews.append(SharedConversationPreview(
                share_id=access.id,
                title=conversation.title,
                shared_by_name=granter.full_name if granter else "Unknown",
                shared_at=access.created_at,
                message_count=msg_count,
                allow_replies=access.can_reply,
                is_socratic=conversation.is_socratic,
                preview_messages=[],  # Could load first few messages here
            ))
        
        return previews
    
    async def revoke_user_access(
        self,
        conversation_id: UUID,
        owner_id: UUID,
        revoke_user_id: UUID,
    ) -> bool:
        """Revoke a user's access to a conversation."""
        # Verify ownership
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        if not conversation or conversation.user_id != owner_id:
            raise AccessDeniedError("You can only manage your own conversations")
        
        return await self.access_repo.revoke_access(
            conversation_id=conversation_id,
            user_id=revoke_user_id,
        )
    
    # ============================================================
    # ACCESS CHECKING
    # ============================================================
    
    async def can_view_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Check if a user can view a conversation.
        
        User can view if:
        1. They own the conversation
        2. They have been granted access
        """
        # Check ownership
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        if conversation and conversation.user_id == user_id:
            return True
        
        # Check access grants
        return await self.access_repo.has_access(conversation_id, user_id)
    
    async def can_reply_to_share(
        self,
        share_token: str,
    ) -> bool:
        """Check if a share allows replies."""
        share = await self.share_repo.get_active_by_token(share_token)
        return share is not None and share.allow_replies
    
    # ============================================================
    # FORKING
    # ============================================================
    
    async def fork_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
        initial_message: Optional[str] = None,
    ) -> ConversationForkResponse:
        """
        Fork a conversation for the user to continue.
        
        Creates a new conversation with copied messages.
        
        Args:
            conversation_id: Original conversation to fork
            user_id: User creating the fork
            initial_message: Optional first message in the fork
        
        Returns:
            Fork response with new conversation info
        """
        # Get original conversation and messages
        original = await self.conversation_repo.get_with_messages(conversation_id)
        
        if not original:
            raise ShareNotFoundError("Conversation not found")
        
        # Create new conversation for the user
        forked = await self.conversation_repo.create(
            user_id=user_id,
            project_id=original.project_id,
            title=f"Fork: {original.title}" if original.title else "Forked Conversation",
            is_socratic=original.is_socratic,
        )
        
        # Copy messages
        last_message_id = None
        for msg in original.messages:
            await self.message_repo.create_message(
                conversation_id=forked.id,
                role=msg.role,
                content=msg.content,
                sources=msg.sources,
            )
            last_message_id = msg.id
        
        # Record the fork
        fork_record = await self.fork_repo.create_fork(
            original_conversation_id=conversation_id,
            forked_conversation_id=forked.id,
            forked_by_user_id=user_id,
            forked_at_message_id=last_message_id,
        )
        
        logger.info(
            f"User {user_id} forked conversation {conversation_id} "
            f"to {forked.id}"
        )
        
        return ConversationForkResponse(
            fork_id=fork_record.id,
            conversation_id=forked.id,
            original_conversation_id=conversation_id,
            message_count=len(original.messages),
            created_at=fork_record.created_at,
        )
    
    async def fork_from_share(
        self,
        share_token: str,
        user_id: UUID,
        initial_message: Optional[str] = None,
    ) -> ConversationForkResponse:
        """
        Fork a conversation from a public share link.
        
        Args:
            share_token: The share token
            user_id: User creating the fork
            initial_message: Optional first message
        
        Returns:
            Fork response
        """
        share = await self.share_repo.get_active_by_token(share_token)
        
        if not share:
            raise ShareNotFoundError("Share not found or has expired")
        
        if not share.allow_replies:
            raise AccessDeniedError("This share does not allow replies")
        
        return await self.fork_conversation(
            conversation_id=share.conversation_id,
            user_id=user_id,
            initial_message=initial_message,
        )
    
    # ============================================================
    # STATISTICS
    # ============================================================
    
    async def get_share_stats(
        self,
        share_id: UUID,
        user_id: UUID,
    ) -> ShareStatsResponse:
        """Get statistics for a share."""
        share = await self.share_repo.get_by_id(share_id)
        
        if not share or share.shared_by_user_id != user_id:
            raise AccessDeniedError("You can only view stats for your own shares")
        
        fork_count = await self.fork_repo.count_forks(share.conversation_id)
        access_list = await self.access_repo.get_conversation_access_list(
            share.conversation_id
        )
        
        return ShareStatsResponse(
            share_id=share.id,
            view_count=share.view_count,
            fork_count=fork_count,
            access_grant_count=len(access_list),
            created_at=share.created_at,
            last_viewed_at=None,  # Would need to track this
        )
    
    # ============================================================
    # HELPERS
    # ============================================================
    
    def _build_share_response(
        self,
        share: SharedConversation,
    ) -> SharedConversationResponse:
        """Build a share response from the model."""
        # Build share URL
        frontend_url = settings.FRONTEND_URL or "http://localhost:3000"
        share_url = f"{frontend_url}/shared/{share.share_token}"
        
        return SharedConversationResponse(
            id=share.id,
            conversation_id=share.conversation_id,
            share_token=share.share_token,
            title=share.title,
            share_type=share.share_type.value if hasattr(share.share_type, 'value') else share.share_type,
            allow_replies=share.allow_replies,
            is_active=share.is_active,
            expires_at=share.expires_at,
            view_count=share.view_count,
            created_at=share.created_at,
            share_url=share_url,
            is_expired=share.is_expired,
        )
