"""
Shared Conversation Models

Models for conversation sharing functionality:
- SharedConversation: Public link sharing with unique tokens
- ConversationAccess: Private sharing with specific users

Key Concepts:
- Public sharing: Anyone with the link can view (and optionally reply)
- Private sharing: Only invited users can access
- Fork on reply: When recipients reply, they get their own copy
"""

import uuid
import secrets
import enum
from datetime import datetime

from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, Enum, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ShareType(enum.Enum):
    """Types of conversation sharing."""
    PUBLIC_LINK = "public_link"  # Anyone with link can access
    PRIVATE = "private"          # Only invited users


class SharedConversation(BaseModel):
    """
    Model for publicly shared conversations.
    
    When a user shares a conversation with a public link:
    1. A unique share_token is generated
    2. Anyone with the token URL can view the conversation
    3. If allow_replies=True, viewers can fork and continue
    
    Attributes:
        conversation_id: The original conversation being shared
        shared_by_user_id: User who created the share
        share_token: Unique token for the public URL
        title: Optional custom title for shared view
        share_type: PUBLIC_LINK or PRIVATE
        allow_replies: Whether recipients can fork and reply
        is_active: Whether the share is currently active
        expires_at: Optional expiration datetime
        view_count: Number of times the share was viewed
    """
    __tablename__ = "shared_conversations"
    
    # Foreign keys
    conversation_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("conversations.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    shared_by_user_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    
    # Share configuration
    share_token = Column(
        String(64), 
        unique=True, 
        nullable=False, 
        index=True,
        default=lambda: secrets.token_urlsafe(32)
    )
    title = Column(String(200), nullable=True)
    share_type = Column(
        Enum(ShareType, name="share_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ShareType.PUBLIC_LINK
    )
    allow_replies = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    view_count = Column(Integer, default=0, nullable=False)
    
    # Relationships
    conversation = relationship("Conversation", backref="shares")
    shared_by = relationship("User", foreign_keys=[shared_by_user_id])
    
    @property
    def is_expired(self) -> bool:
        """Check if the share has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_accessible(self) -> bool:
        """Check if the share is currently accessible."""
        return self.is_active and not self.is_expired


class ConversationAccess(BaseModel):
    """
    Model for private conversation sharing with specific users.
    
    When a user shares privately:
    1. An access record is created for each recipient
    2. Recipients can view the conversation
    3. If can_reply=True, they can fork and continue
    
    Attributes:
        conversation_id: The conversation being shared
        user_id: The recipient user
        granted_by_user_id: User who granted access
        can_reply: Whether the recipient can fork and reply
        is_active: Whether the access is currently active
    """
    __tablename__ = "conversation_access"
    
    # Foreign keys
    conversation_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("conversations.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    user_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    granted_by_user_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False
    )
    
    # Access configuration
    can_reply = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    conversation = relationship("Conversation", backref="access_grants")
    user = relationship("User", foreign_keys=[user_id], backref="conversation_access")
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])


class ConversationFork(BaseModel):
    """
    Model to track forked conversations.
    
    When a recipient replies to a shared conversation:
    1. A new conversation is created (fork)
    2. Messages from the original are copied
    3. The recipient continues in their own fork
    
    This maintains the relationship for reference.
    
    Attributes:
        original_conversation_id: The source conversation
        forked_conversation_id: The new conversation created
        forked_by_user_id: User who created the fork
        forked_at_message_id: Last message from original included in fork
    """
    __tablename__ = "conversation_forks"
    
    # Foreign keys
    original_conversation_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("conversations.id", ondelete="SET NULL"), 
        nullable=True,
        index=True
    )
    forked_conversation_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("conversations.id", ondelete="CASCADE"), 
        nullable=False,
        unique=True,
        index=True
    )
    forked_by_user_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    forked_at_message_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("messages.id", ondelete="SET NULL"), 
        nullable=True
    )
    
    # Relationships
    original_conversation = relationship(
        "Conversation", 
        foreign_keys=[original_conversation_id],
        backref="forks_from"
    )
    forked_conversation = relationship(
        "Conversation", 
        foreign_keys=[forked_conversation_id],
        backref="fork_info"
    )
    forked_by = relationship("User")
    forked_at_message = relationship("Message")
