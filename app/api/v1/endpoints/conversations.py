"""
Conversation and Chat Endpoints

HTTP API for chat functionality.

Endpoints:
----------
Conversations:
- POST   /conversations                    - Create new conversation
- GET    /conversations                    - List user's conversations
- GET    /conversations/{id}               - Get conversation with messages
- PATCH  /conversations/{id}               - Update conversation (title, socratic)
- DELETE /conversations/{id}               - Delete conversation

Chat:
- POST   /conversations/{id}/messages      - Send message (non-streaming)
- GET    /conversations/{id}/messages/stream - Send message (streaming via SSE)
"""

import logging
import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationWithMessages,
    ConversationListResponse,
    ChatRequest,
    ChatResponse,
    MessageResponse,
)
from app.services.chat_service import (
    ChatService,
    ChatServiceError,
    ConversationNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


# ============================================================
# HELPER
# ============================================================

def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    """Dependency that provides ChatService instance."""
    return ChatService(db)


# ============================================================
# CONVERSATION ENDPOINTS
# ============================================================

@router.post(
    "",
    response_model=ConversationWithMessages,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
    description="""
    Create a new chat conversation.
    
    **Two types of conversations:**
    - **Quick Chat**: Set `project_id` to `null` - uses general AI knowledge
    - **Project Chat**: Provide `project_id` - uses RAG with project documents
    
    **Socratic Mode**: When `is_socratic` is `true` (default), the AI guides 
    learning through questions rather than direct answers.
    
    You can optionally provide an `initial_message` to start the conversation.
    """,
)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Create a new conversation."""
    try:
        return await service.create_conversation(
            user_id=current_user.id,
            data=data
        )
    except ChatServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="List conversations",
    description="""
    Get all conversations for the current user.
    
    **Filtering:**
    - `project_id`: Filter to a specific project's conversations
    - Set `project_id` to empty to get only quick chats
    
    Results are ordered by most recent activity.
    """,
)
async def list_conversations(
    project_id: Optional[UUID] = Query(
        None,
        description="Filter by project ID"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """List user's conversations."""
    conversations = await service.list_conversations(
        user_id=current_user.id,
        project_id=project_id,
        skip=skip,
        limit=limit
    )
    
    return ConversationListResponse(
        conversations=conversations,
        total=len(conversations)  # TODO: Add proper count
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationWithMessages,
    summary="Get conversation with messages",
    description="Get a conversation including all its messages.",
)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get a conversation with all messages."""
    try:
        return await service.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Update conversation",
    description="Update conversation title or Socratic mode setting.",
)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update a conversation."""
    try:
        return await service.update_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            title=data.title,
            is_socratic=data.is_socratic
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversation",
    description="Permanently delete a conversation and all its messages.",
)
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Delete a conversation."""
    try:
        await service.delete_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )


# ============================================================
# CHAT ENDPOINTS
# ============================================================

@router.post(
    "/{conversation_id}/messages",
    response_model=ChatResponse,
    summary="Send a message",
    description="""
    Send a message to the AI and get a response.
    
    This is the **non-streaming** version - the full response is returned 
    at once. For real-time streaming, use the `/stream` endpoint.
    
    The AI will:
    1. Retrieve relevant context from project documents (if project chat)
    2. Consider the conversation history
    3. Generate a response based on Socratic mode setting
    4. Return the response with source citations
    """,
)
async def send_message(
    conversation_id: UUID,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Send a message and get AI response."""
    try:
        result = await service.send_message(
            conversation_id=conversation_id,
            user_id=current_user.id,
            content=data.message
        )
        
        return ChatResponse(
            message=result["message"],
            sources=result.get("sources", []),
            tokens_used=result.get("tokens_used", 0)
        )
        
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate response"
        )


@router.post(
    "/{conversation_id}/messages/stream",
    summary="Send a message (streaming)",
    description="""
    Send a message and receive a streaming response via Server-Sent Events (SSE).
    
    **Event types:**
    - `sources`: Source citations (sent first if available)
    - `content`: Text chunks as they're generated
    - `done`: Completion signal with message ID
    - `error`: Error message if something goes wrong
    
    **Example SSE events:**
    """,
    responses={
        200: {
            "description": "SSE stream of response chunks",
            "content": {"text/event-stream": {}}
        }
    }
)
async def send_message_stream(
    conversation_id: UUID,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    # NOTE: Don't use Depends(get_chat_service) here - session closes before streaming completes!
):
    """Send a message and stream the AI response."""
    
    # Capture user_id before entering generator (user object may be garbage collected)
    user_id = current_user.id
    message_content = data.message
    
    async def event_generator():
        """Generate SSE events from chat stream."""
        # Create database session INSIDE the generator so it stays open during streaming
        from app.db.database import AsyncSessionLocal
        
        async with AsyncSessionLocal() as db:
            service = ChatService(db)
            
            try:
                chunk_count = 0
                logger.info(f"SSE: Starting stream for conversation {conversation_id}")
                
                async for chunk in service.send_message_stream(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    content=message_content
                ):
                    chunk_type = chunk.get("type", "content")
                    logger.info(f"SSE: Yielding chunk type={chunk_type}")
                    
                    if chunk_type == "sources":
                        yield {
                            "event": "sources",
                            "data": json.dumps({
                                "sources": [s.model_dump() for s in chunk["sources"]]
                            })
                        }
                    elif chunk_type == "content":
                        chunk_count += 1
                        content_text = chunk["content"]
                        logger.info(f"SSE: Content chunk #{chunk_count}, length={len(content_text)}")
                        yield {
                            "event": "content",
                            "data": json.dumps({"text": content_text})
                        }
                    elif chunk_type == "done":
                        logger.info(f"SSE: Done event, total chunks={chunk_count}, messageId={chunk.get('message_id')}")
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "message_id": chunk.get("message_id")
                            })
                        }
                    elif chunk_type == "error":
                        logger.error(f"SSE: Error event: {chunk.get('error')}")
                        yield {
                            "event": "error",
                            "data": json.dumps({"error": chunk.get("error")})
                        }
                        
            except ConversationNotFoundError:
                yield {
                    "event": "error",
                    "data": json.dumps({"error": "Conversation not found"})
                }
            except Exception as e:
                import traceback
                logger.error(f"Streaming error: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(e)})
                }
    
    return EventSourceResponse(event_generator())