"""
Chat Sharing Schemas

Pydantic models for conversation sharing functionality.

Sharing Types:
-------------
1. PUBLIC LINK: Anyone with the link can view (and optionally reply)
2. PRIVATE: Only invited users can access

Reply Behavior:
--------------
When recipients reply, they get a fork (copy) of the conversation.
This preserves the original while allowing them to continue.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator, EmailStr


# ============================================================
# ENUMS
# ============================================================

class ShareType(str, Enum):
    """Type of sharing."""
    PUBLIC_LINK = "public_link"
    PRIVATE = "private"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class CreatePublicShareRequest(BaseModel):
    """
    Request to create a public share link.
    
    The share_token will be auto-generated.
    """
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="Custom title for the shared view"
    )
    allow_replies: bool = Field(
        default=True,
        description="Allow viewers to fork and continue the conversation"
    )
    expires_in_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Days until the share expires (None = never)"
    )


class CreatePrivateShareRequest(BaseModel):
    """
    Request to share a conversation privately with specific users.
    """
    user_emails: List[EmailStr] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Email addresses of users to share with"
    )
    can_reply: bool = Field(
        default=True,
        description="Allow recipients to fork and continue"
    )
    
    @field_validator("user_emails")
    @classmethod
    def validate_emails(cls, v: List[EmailStr]) -> List[EmailStr]:
        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for email in v:
            email_lower = email.lower()
            if email_lower not in seen:
                seen.add(email_lower)
                unique.append(email)
        return unique


class UpdateShareRequest(BaseModel):
    """
    Request to update share settings.
    """
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="Update the share title"
    )
    allow_replies: Optional[bool] = Field(
        None,
        description="Update reply permission"
    )
    is_active: Optional[bool] = Field(
        None,
        description="Enable/disable the share"
    )


class ForkConversationRequest(BaseModel):
    """
    Request to fork a shared conversation.
    
    Creates a copy that the user can continue.
    """
    initial_message: Optional[str] = Field(
        None,
        max_length=10000,
        description="Optional first message to send in the fork"
    )


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class SharedConversationResponse(BaseModel):
    """
    Response for a shared conversation.
    """
    id: UUID
    conversation_id: UUID
    share_token: str
    title: Optional[str] = None
    share_type: ShareType
    allow_replies: bool
    is_active: bool
    expires_at: Optional[datetime] = None
    view_count: int = 0
    created_at: datetime
    
    # Computed
    share_url: Optional[str] = Field(
        None,
        description="Full URL to access the share"
    )
    is_expired: bool = Field(
        default=False,
        description="Whether the share has expired"
    )
    
    class Config:
        from_attributes = True


class ConversationAccessResponse(BaseModel):
    """
    Response for a private share access grant.
    """
    id: UUID
    conversation_id: UUID
    user_id: UUID
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    can_reply: bool
    is_active: bool
    granted_at: datetime
    
    class Config:
        from_attributes = True


class SharedConversationPreview(BaseModel):
    """
    Preview of a shared conversation (for recipients).
    
    This is what recipients see before they fork.
    """
    share_id: UUID
    title: Optional[str] = None
    shared_by_name: str
    shared_at: datetime
    message_count: int
    allow_replies: bool
    is_socratic: bool
    
    # Preview of messages (first few)
    preview_messages: List[dict] = Field(
        default_factory=list,
        description="First few messages as preview"
    )


class SharedConversationFull(SharedConversationPreview):
    """
    Full shared conversation with all messages.
    
    Returned when viewing a shared conversation.
    """
    conversation_id: UUID
    messages: List[dict] = Field(
        default_factory=list,
        description="All messages in the conversation"
    )


class ConversationForkResponse(BaseModel):
    """
    Response after forking a shared conversation.
    """
    fork_id: UUID
    conversation_id: UUID = Field(
        description="ID of the new forked conversation"
    )
    original_conversation_id: Optional[UUID] = Field(
        None,
        description="ID of the original conversation"
    )
    message_count: int = Field(
        description="Number of messages copied"
    )
    created_at: datetime
    
    class Config:
        from_attributes = True


class ShareStatsResponse(BaseModel):
    """
    Statistics for a shared conversation.
    """
    share_id: UUID
    view_count: int
    fork_count: int
    access_grant_count: int = Field(
        description="Number of private access grants"
    )
    created_at: datetime
    last_viewed_at: Optional[datetime] = None


# ============================================================
# LIST RESPONSES
# ============================================================

class SharedByMeListResponse(BaseModel):
    """
    List of conversations shared by the current user.
    """
    shares: List[SharedConversationResponse]
    total: int


class SharedWithMeListResponse(BaseModel):
    """
    List of conversations shared with the current user.
    """
    shares: List[SharedConversationPreview]
    total: int
