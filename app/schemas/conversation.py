"""
Conversation and Message Schemas

Pydantic models for chat-related API operations.

Chat Types:
----------
1. QUICK CHAT: No project, uses general AI knowledge
2. PROJECT CHAT: Uses documents from a specific project

Socratic Mode:
-------------
When enabled, AI asks guiding questions instead of direct answers.
This promotes deeper learning and critical thinking.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ============================================================
# ENUMS
# ============================================================

class MessageRole(str, Enum):
    """Message sender role."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatType(str, Enum):
    """Type of chat session."""
    QUICK = "quick"      # No project, general knowledge
    PROJECT = "project"  # Uses project documents


# ============================================================
# MESSAGE SCHEMAS
# ============================================================

class MessageCreate(BaseModel):
    """
    Schema for sending a new message.
    
    This is what the client sends when the user types a message.
    """
    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Message content"
    )
    
    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Clean and validate message content."""
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class MessageResponse(BaseModel):
    """
    Schema for a message returned by the API.
    """
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    sources: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Source citations for AI responses"
    )
    tokens_used: Optional[int] = Field(
        None,
        description="Tokens used to generate this message"
    )
    created_at: datetime
    
    class Config:
        from_attributes = True


class SourceCitation(BaseModel):
    """
    A single source citation for AI responses.
    
    Tells the user where the information came from.
    """
    document_id: str
    document_name: str
    page_number: Optional[int] = None
    relevance_score: float = Field(ge=0, le=1)
    excerpt: Optional[str] = Field(
        None,
        max_length=500,
        description="Relevant excerpt from the source"
    )


# ============================================================
# CONVERSATION SCHEMAS
# ============================================================

class ConversationCreate(BaseModel):
    """
    Schema for creating a new conversation.
    
    project_id is optional:
    - If provided: Project chat (uses RAG with project documents)
    - If None: Quick chat (general AI knowledge)
    """
    project_id: Optional[UUID] = Field(
        None,
        description="Project ID for project-based chat (None for quick chat)"
    )
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="Conversation title (auto-generated if not provided)"
    )
    is_socratic: bool = Field(
        default=True,
        description="Enable Socratic learning mode"
    )
    
    # Initial message (optional - can start empty conversation)
    initial_message: Optional[str] = Field(
        None,
        max_length=10000,
        description="First message to send"
    )


class ConversationUpdate(BaseModel):
    """
    Schema for updating a conversation.
    """
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="New conversation title"
    )
    is_socratic: Optional[bool] = Field(
        None,
        description="Toggle Socratic mode"
    )


class ConversationResponse(BaseModel):
    """
    Schema for a conversation returned by the API.
    """
    id: UUID
    user_id: UUID
    project_id: Optional[UUID] = None
    title: Optional[str] = None
    is_socratic: bool
    created_at: datetime
    updated_at: datetime
    
    # Computed fields
    message_count: int = Field(
        default=0,
        description="Number of messages in conversation"
    )
    last_message_at: Optional[datetime] = Field(
        None,
        description="When the last message was sent"
    )
    chat_type: ChatType = Field(
        default=ChatType.QUICK,
        description="Type of chat (quick or project)"
    )
    
    class Config:
        from_attributes = True


class ConversationWithMessages(ConversationResponse):
    """
    Conversation with its messages included.
    
    Used when fetching a single conversation for the chat view.
    """
    messages: List[MessageResponse] = Field(
        default_factory=list,
        description="Messages in this conversation"
    )
    
    # Project info (if project chat)
    project_name: Optional[str] = Field(
        None,
        description="Name of the associated project"
    )


class ConversationListResponse(BaseModel):
    """
    Response for listing conversations.
    """
    conversations: List[ConversationResponse]
    total: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "conversations": [],
                "total": 0
            }
        }


# ============================================================
# CHAT SCHEMAS (for the actual chat interaction)
# ============================================================

class ChatRequest(BaseModel):
    """
    Request to send a chat message.
    
    This is the main endpoint for chatting.
    """
    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User's message"
    )
    
    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class ChatResponse(BaseModel):
    """
    Response from chat (non-streaming).
    
    For streaming, see SSE endpoint.
    """
    message: MessageResponse = Field(
        ...,
        description="The AI's response message"
    )
    sources: List[SourceCitation] = Field(
        default_factory=list,
        description="Sources used for the response"
    )
    tokens_used: int = Field(
        default=0,
        description="Total tokens used"
    )


class StreamChunk(BaseModel):
    """
    A single chunk in a streaming response.
    
    Sent via Server-Sent Events (SSE).
    """
    type: str = Field(
        ...,
        description="Chunk type: 'content', 'sources', 'done', 'error'"
    )
    content: Optional[str] = Field(
        None,
        description="Text content (for 'content' type)"
    )
    sources: Optional[List[SourceCitation]] = Field(
        None,
        description="Sources (for 'sources' type)"
    )
    error: Optional[str] = Field(
        None,
        description="Error message (for 'error' type)"
    )
    message_id: Optional[str] = Field(
        None,
        description="ID of the completed message (for 'done' type)"
    )