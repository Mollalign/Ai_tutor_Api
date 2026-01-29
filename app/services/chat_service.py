"""
Chat Service

Orchestrates the complete chat flow:
1. Save user message
2. Retrieve relevant context (RAG)
3. Build prompt with context and history
4. Get LLM response
5. Save assistant response with sources
"""

import logging
from typing import Optional, List, Dict, Any, AsyncGenerator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.project_repo import ProjectRepository
from app.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationWithMessages,
    ChatType,
    MessageResponse,
    SourceCitation,
)
from app.ai.rag import get_retriever, Retriever
from app.ai.llm.gemini_client import chat_completion, chat_completion_stream
from app.ai.prompts.chat_prompts import (
    build_system_prompt,
    build_context_prompt,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class ChatServiceError(Exception):
    """Base exception for chat service errors."""
    pass


class ConversationNotFoundError(ChatServiceError):
    """Conversation not found or access denied."""
    pass


class ChatService:
    """
    Service for chat operations.
    
    Handles:
    - Conversation CRUD
    - Message management
    - RAG retrieval
    - LLM interaction
    - Response streaming
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.project_repo = ProjectRepository(db)
        self.retriever: Retriever = get_retriever()
    
    # ============================================================
    # CONVERSATION MANAGEMENT
    # ============================================================
    
    async def create_conversation(
        self,
        user_id: UUID,
        data: ConversationCreate
    ) -> ConversationWithMessages:
        """
        Create a new conversation.
        
        Args:
            user_id: User's ID
            data: Conversation creation data
        
        Returns:
            Created conversation
        """
        # If project_id provided, verify access
        if data.project_id:
            project = await self.project_repo.get_by_id(data.project_id)
            if not project or project.user_id != user_id:
                raise ChatServiceError("Project not found")
        
        # Create conversation
        conversation = await self.conversation_repo.create(
            user_id=user_id,
            project_id=data.project_id,
            title=data.title,
            is_socratic=data.is_socratic
        )
        
        # If initial message provided, process it
        messages = []
        if data.initial_message:
            response = await self.send_message(
                conversation_id=conversation.id,
                user_id=user_id,
                content=data.initial_message
            )
            # Get messages after sending
            messages = await self.message_repo.get_conversation_messages(
                conversation.id
            )
        
        return self._build_conversation_response(conversation, messages)
    
    async def get_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID
    ) -> ConversationWithMessages:
        """Get a conversation with messages."""
        conversation = await self.conversation_repo.get_with_messages(
            conversation_id
        )
        
        if not conversation or conversation.user_id != user_id:
            raise ConversationNotFoundError("Conversation not found")
        
        return self._build_conversation_response(
            conversation,
            conversation.messages
        )
    
    async def list_conversations(
        self,
        user_id: UUID,
        project_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[ConversationResponse]:
        """List user's conversations."""
        conversations = await self.conversation_repo.get_user_conversations(
            user_id=user_id,
            project_id=project_id,
            skip=skip,
            limit=limit
        )
        
        result = []
        for conv in conversations:
            msg_count = await self.conversation_repo.get_message_count(conv.id)
            last_msg = await self.conversation_repo.get_last_message_time(conv.id)
            
            result.append(ConversationResponse(
                id=conv.id,
                user_id=conv.user_id,
                project_id=conv.project_id,
                title=conv.title,
                is_socratic=conv.is_socratic,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=msg_count,
                last_message_at=last_msg,
                chat_type=ChatType.PROJECT if conv.project_id else ChatType.QUICK
            ))
        
        return result
    
    async def delete_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID
    ) -> bool:
        """Delete a conversation."""
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            raise ConversationNotFoundError("Conversation not found")
        
        return await self.conversation_repo.delete(conversation_id)
    
    async def update_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
        title: Optional[str] = None,
        is_socratic: Optional[bool] = None
    ) -> ConversationResponse:
        """Update conversation settings."""
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            raise ConversationNotFoundError("Conversation not found")
        
        update_data = {}
        if title is not None:
            update_data["title"] = title
        if is_socratic is not None:
            update_data["is_socratic"] = is_socratic
        
        if update_data:
            conversation = await self.conversation_repo.update(
                conversation_id,
                **update_data
            )
        
        return ConversationResponse.model_validate(conversation)
    
    # ============================================================
    # CHAT - MAIN METHOD
    # ============================================================
    
    async def send_message(
        self,
        conversation_id: UUID,
        user_id: UUID,
        content: str
    ) -> Dict[str, Any]:
        """
        Send a message and get AI response.
        
        This is the main chat method:
        1. Verify access
        2. Save user message
        3. Get context (RAG) if project chat
        4. Build prompt
        5. Get LLM response
        6. Save and return response
        
        Args:
            conversation_id: Conversation UUID
            user_id: User's UUID
            content: User's message
        
        Returns:
            Dict with response, sources, tokens
        """
        # Get and verify conversation
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            raise ConversationNotFoundError("Conversation not found")
        
        # Save user message
        user_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content
        )
        
        # Get conversation history
        history = await self.message_repo.get_recent_messages(
            conversation_id,
            limit=10
        )
        
        # Get context from RAG if project chat
        context = ""
        sources = []
        
        if conversation.project_id:
            retrieval_result = self.retriever.retrieve(
                query=content,
                project_id=conversation.project_id,
                top_k=5
            )
            
            if retrieval_result.has_results:
                context = retrieval_result.get_context(max_chunks=5)
                sources = [
                    SourceCitation(
                        document_id=chunk.document_id,
                        document_name=chunk.document_name,
                        page_number=chunk.page_number,
                        relevance_score=chunk.score,
                        excerpt=chunk.text[:200] if chunk.text else None
                    )
                    for chunk in retrieval_result.chunks[:3]
                ]
        
        # Build messages for LLM
        llm_messages = self._build_llm_messages(history, context)
        
        # Build system prompt
        system_prompt = build_system_prompt(
            is_socratic=conversation.is_socratic,
            has_context=bool(context)
        )
        
        # Get LLM response
        response = await chat_completion(
            messages=llm_messages,
            system_prompt=system_prompt
        )
        
        # Save assistant message
        assistant_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=response["content"],
            sources=[s.model_dump() for s in sources] if sources else None,
            tokens_used=response["tokens_used"]
        )
        
        # Update conversation timestamp
        await self.conversation_repo.touch(conversation_id)
        
        # Auto-generate title if needed
        if not conversation.title and len(history) <= 2:
            await self._auto_generate_title(conversation_id, content)
        
        return {
            "message": MessageResponse.model_validate(assistant_message),
            "sources": sources,
            "tokens_used": response["tokens_used"]
        }
    
    async def send_message_stream(
        self,
        conversation_id: UUID,
        user_id: UUID,
        content: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Send a message and stream the AI response.
        
        Yields chunks as they're generated.
        
        Yields:
            Dict with type ('content', 'sources', 'done', 'error')
        """
        # Get and verify conversation
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            yield {"type": "error", "error": "Conversation not found"}
            return
        
        # Save user message
        user_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content
        )
        
        # Get conversation history
        history = await self.message_repo.get_recent_messages(
            conversation_id,
            limit=10
        )
        
        # Get context from RAG
        context = ""
        sources = []
        
        if conversation.project_id:
            retrieval_result = self.retriever.retrieve(
                query=content,
                project_id=conversation.project_id,
                top_k=5
            )
            
            if retrieval_result.has_results:
                context = retrieval_result.get_context(max_chunks=5)
                sources = [
                    SourceCitation(
                        document_id=chunk.document_id,
                        document_name=chunk.document_name,
                        page_number=chunk.page_number,
                        relevance_score=chunk.score,
                        excerpt=chunk.text[:200] if chunk.text else None
                    )
                    for chunk in retrieval_result.chunks[:3]
                ]
        
        # Send sources first
        if sources:
            yield {"type": "sources", "sources": sources}
        
        # Build messages and prompt
        llm_messages = self._build_llm_messages(history, context)
        system_prompt = build_system_prompt(
            is_socratic=conversation.is_socratic,
            has_context=bool(context)
        )
        
        # Stream response
        full_response = ""
        
        try:
            async for chunk in chat_completion_stream(
                messages=llm_messages,
                system_prompt=system_prompt
            ):
                full_response += chunk
                yield {"type": "content", "content": chunk}
            
            # Save assistant message
            assistant_message = await self.message_repo.create_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=full_response,
                sources=[s.model_dump() for s in sources] if sources else None
            )
            
            # Update conversation
            await self.conversation_repo.touch(conversation_id)
            
            yield {
                "type": "done",
                "message_id": str(assistant_message.id)
            }
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield {"type": "error", "error": str(e)}
    
    # ============================================================
    # HELPER METHODS
    # ============================================================
    
    def _build_llm_messages(
        self,
        history: List[Message],
        context: str = ""
    ) -> List[Dict[str, str]]:
        """Build message list for LLM."""
        messages = []
        
        # Add context if available
        if context:
            context_prompt = build_context_prompt(context)
            messages.append({
                "role": "system",
                "content": context_prompt
            })
        
        # Add conversation history
        for msg in history:
            messages.append({
                "role": msg.role.value if hasattr(msg.role, 'value') else msg.role,
                "content": msg.content
            })
        
        return messages
    
    def _build_conversation_response(
        self,
        conversation: Conversation,
        messages: List[Message]
    ) -> ConversationWithMessages:
        """Build conversation response with messages."""
        return ConversationWithMessages(
            id=conversation.id,
            user_id=conversation.user_id,
            project_id=conversation.project_id,
            title=conversation.title,
            is_socratic=conversation.is_socratic,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=len(messages),
            last_message_at=messages[-1].created_at if messages else None,
            chat_type=ChatType.PROJECT if conversation.project_id else ChatType.QUICK,
            messages=[MessageResponse.model_validate(m) for m in messages]
        )
    
    async def _auto_generate_title(
        self,
        conversation_id: UUID,
        first_message: str
    ) -> None:
        """Auto-generate conversation title from first message."""
        # Simple: Use first ~50 chars of message
        title = first_message[:50].strip()
        if len(first_message) > 50:
            title += "..."
        
        await self.conversation_repo.update(conversation_id, title=title)