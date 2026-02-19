"""
Conversation Sharing Endpoints

HTTP API for sharing conversations.

Endpoints:
----------
Public Sharing:
- POST   /shares                           - Create public share link
- GET    /shares                           - List my shares
- GET    /shares/{share_id}                - Get share details
- PATCH  /shares/{share_id}                - Update share settings
- DELETE /shares/{share_id}                - Delete share

Public Access (no auth required):
- GET    /shared/{token}                   - View shared conversation
- POST   /shared/{token}/fork              - Fork shared conversation

Private Sharing:
- POST   /conversations/{id}/share-private - Share with specific users
- GET    /shared-with-me                   - List conversations shared with me
- DELETE /conversations/{id}/access/{user_id} - Revoke user access

Forking:
- POST   /conversations/{id}/fork          - Fork a conversation (with access)
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.sharing import (
    CreatePublicShareRequest,
    CreatePrivateShareRequest,
    UpdateShareRequest,
    ForkConversationRequest,
    SharedConversationResponse,
    ConversationAccessResponse,
    SharedConversationPreview,
    SharedConversationFull,
    ConversationForkResponse,
    ShareStatsResponse,
    SharedByMeListResponse,
    SharedWithMeListResponse,
)
from app.services.sharing_service import (
    SharingService,
    SharingServiceError,
    ShareNotFoundError,
    AccessDeniedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sharing"])


# ============================================================
# HELPER
# ============================================================

def get_sharing_service(db: AsyncSession = Depends(get_db)) -> SharingService:
    """Dependency that provides SharingService instance."""
    return SharingService(db)


# ============================================================
# PUBLIC SHARE LINKS
# ============================================================

@router.post(
    "/shares",
    response_model=SharedConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a public share link",
    description="""
    Create a public link to share a conversation.
    
    Anyone with the link can view the conversation.
    If `allow_replies` is true, viewers can fork and continue the conversation.
    
    **Expiration**: Set `expires_in_days` to auto-expire the share.
    """,
)
async def create_public_share(
    conversation_id: UUID = Query(..., description="Conversation to share"),
    data: CreatePublicShareRequest = None,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Create a public share link for a conversation."""
    if data is None:
        data = CreatePublicShareRequest()
    
    try:
        share = await service.create_public_share(
            conversation_id=conversation_id,
            user_id=current_user.id,
            title=data.title,
            allow_replies=data.allow_replies,
            expires_in_days=data.expires_in_days,
        )
        return share
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.get(
    "/shares",
    response_model=SharedByMeListResponse,
    summary="List my shares",
    description="Get all conversations you have shared.",
)
async def list_my_shares(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """List all shares created by the current user."""
    shares = await service.get_my_shares(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    return SharedByMeListResponse(
        shares=shares,
        total=len(shares),
    )


@router.get(
    "/shares/{share_id}",
    response_model=SharedConversationResponse,
    summary="Get share details",
)
async def get_share(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Get details of a specific share."""
    shares = await service.get_my_shares(
        user_id=current_user.id,
        skip=0,
        limit=1000,
    )
    
    for share in shares:
        if share.id == share_id:
            return share
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Share not found"
    )


@router.patch(
    "/shares/{share_id}",
    response_model=SharedConversationResponse,
    summary="Update share settings",
)
async def update_share(
    share_id: UUID,
    data: UpdateShareRequest,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Update share settings."""
    try:
        share = await service.update_share(
            share_id=share_id,
            user_id=current_user.id,
            title=data.title,
            allow_replies=data.allow_replies,
            is_active=data.is_active,
        )
        return share
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.delete(
    "/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a share",
)
async def delete_share(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Delete a share link."""
    try:
        deleted = await service.delete_share(
            share_id=share_id,
            user_id=current_user.id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Share not found"
            )
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.get(
    "/shares/{share_id}/stats",
    response_model=ShareStatsResponse,
    summary="Get share statistics",
)
async def get_share_stats(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Get statistics for a share (views, forks, etc.)."""
    try:
        return await service.get_share_stats(
            share_id=share_id,
            user_id=current_user.id,
        )
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================
# PUBLIC ACCESS (NO AUTH REQUIRED)
# ============================================================

@router.get(
    "/shared/{token}",
    response_model=SharedConversationFull,
    summary="View shared conversation",
    description="""
    View a shared conversation using its share token.
    
    No authentication required for public shares.
    """,
)
async def view_shared_conversation(
    token: str,
    service: SharingService = Depends(get_sharing_service),
):
    """View a shared conversation by token."""
    try:
        return await service.get_share_by_token(
            token=token,
            increment_views=True,
        )
    except ShareNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post(
    "/shared/{token}/fork",
    response_model=ConversationForkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fork a shared conversation",
    description="""
    Create your own copy of a shared conversation.
    
    The forked conversation becomes yours to continue.
    Requires authentication.
    """,
)
async def fork_shared_conversation(
    token: str,
    data: ForkConversationRequest = None,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Fork a shared conversation."""
    if data is None:
        data = ForkConversationRequest()
    
    try:
        return await service.fork_from_share(
            share_token=token,
            user_id=current_user.id,
            initial_message=data.initial_message,
        )
    except ShareNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================
# PRIVATE SHARING
# ============================================================

@router.post(
    "/conversations/{conversation_id}/share-private",
    response_model=List[ConversationAccessResponse],
    summary="Share with specific users",
    description="""
    Share a conversation privately with specific users by email.
    
    Recipients will see the conversation in their "Shared with me" list.
    """,
)
async def share_with_users(
    conversation_id: UUID,
    data: CreatePrivateShareRequest,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Share a conversation privately with specific users."""
    try:
        return await service.share_with_users(
            conversation_id=conversation_id,
            user_id=current_user.id,
            user_emails=data.user_emails,
            can_reply=data.can_reply,
        )
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.get(
    "/shared-with-me",
    response_model=SharedWithMeListResponse,
    summary="List conversations shared with me",
)
async def list_shared_with_me(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """List all conversations shared with the current user."""
    shares = await service.get_shared_with_me(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    return SharedWithMeListResponse(
        shares=shares,
        total=len(shares),
    )


@router.delete(
    "/conversations/{conversation_id}/access/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke user access",
)
async def revoke_user_access(
    conversation_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Revoke a user's access to a conversation."""
    try:
        revoked = await service.revoke_user_access(
            conversation_id=conversation_id,
            owner_id=current_user.id,
            revoke_user_id=user_id,
        )
        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Access grant not found"
            )
    except AccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================
# DIRECT FORKING (for private shares)
# ============================================================

@router.post(
    "/conversations/{conversation_id}/fork",
    response_model=ConversationForkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fork a conversation",
    description="""
    Create your own copy of a conversation you have access to.
    
    You can fork:
    - Conversations shared with you privately
    - Your own conversations
    """,
)
async def fork_conversation(
    conversation_id: UUID,
    data: ForkConversationRequest = None,
    current_user: User = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
):
    """Fork a conversation you have access to."""
    if data is None:
        data = ForkConversationRequest()
    
    # Check access
    can_view = await service.can_view_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    
    if not can_view:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this conversation"
        )
    
    try:
        return await service.fork_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            initial_message=data.initial_message,
        )
    except ShareNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
