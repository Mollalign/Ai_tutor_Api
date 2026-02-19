"""
Chat Service

Orchestrates the complete chat flow:
1. Save user message
2. Retrieve relevant context (RAG)
3. Build prompt with context and history
4. Get LLM response (via LangChain)
5. Save assistant response with sources
6. Broadcast message via WebSocket for real-time sync

NEW in LangChain version:
- Multimodal support (images)
- URL content extraction
- LangChain-based LLM calls
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
from app.ai.prompts.chat_prompts import (
    build_system_prompt,
    build_context_prompt,
)
from app.core.config import settings
from app.services.websocket_manager import (
    get_connection_manager,
    WebSocketMessage,
    MessageTypes,
)

# ============================================================
# CHANGED: Import LangChain client instead of direct Gemini
# ============================================================
# OLD:
# from app.ai.llm.gemini_client import chat_completion, chat_completion_stream

# NEW:
from app.ai.llm.langchain_client import (
    chat_completion,
    chat_completion_stream,
    create_image_message,
    analyze_image,
)
from app.ai.loaders.url_loader import (
    load_url,
    extract_urls_from_text,
    detect_url_type,
    URLType,
)
from app.repositories.sharing_repo import ConversationAccessRepository

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
    - LLM interaction (via LangChain)
    - Response streaming
    - Multimodal messages (images)
    - URL content extraction
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.project_repo = ProjectRepository(db)
        self.access_repo = ConversationAccessRepository(db)
        self.retriever: Retriever = get_retriever()
    
    # ============================================================
    # CONVERSATION MANAGEMENT (UNCHANGED)
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
        if data.project_id:
            project = await self.project_repo.get_by_id(data.project_id)
            if not project or project.user_id != user_id:
                raise ChatServiceError("Project not found")
        
        conversation = await self.conversation_repo.create(
            user_id=user_id,
            project_id=data.project_id,
            title=data.title,
            is_socratic=data.is_socratic
        )
        
        messages = []
        if data.initial_message:
            response = await self.send_message(
                conversation_id=conversation.id,
                user_id=user_id,
                content=data.initial_message
            )
            messages = await self.message_repo.get_conversation_messages(
                conversation.id
            )
        
        return self._build_conversation_response(conversation, messages)
    
    async def get_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
        check_shared_access: bool = True
    ) -> ConversationWithMessages:
        """
        Get a conversation with messages.
        
        Access is granted if:
        1. User owns the conversation
        2. User has been granted shared access (if check_shared_access=True)
        """
        conversation = await self.conversation_repo.get_with_messages(
            conversation_id
        )
        
        if not conversation:
            raise ConversationNotFoundError("Conversation not found")
        
        # Check ownership
        has_access = conversation.user_id == user_id
        
        # Check shared access if not owner
        if not has_access and check_shared_access:
            has_access = await self.access_repo.has_access(
                conversation_id=conversation_id,
                user_id=user_id
            )
        
        if not has_access:
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
    # CHAT - MAIN METHOD (UPDATED FOR LANGCHAIN)
    # ============================================================
    
    async def send_message(
        self,
        conversation_id: UUID,
        user_id: UUID,
        content: str,
        # NEW: Optional attachments
        image_base64: Optional[str] = None,
        image_url: Optional[str] = None,
        auto_extract_urls: bool = True,
    ) -> Dict[str, Any]:
        """
        Send a message and get AI response.
        
        This is the main chat method:
        1. Verify access
        2. Extract URLs if present (NEW)
        3. Save user message
        4. Get context (RAG) if project chat
        5. Build prompt with context and URL content
        6. Get LLM response (via LangChain)
        7. Save and return response
        
        Args:
            conversation_id: Conversation UUID
            user_id: User's UUID
            content: User's message
            image_base64: Optional base64-encoded image (NEW)
            image_url: Optional URL to image (NEW)
            auto_extract_urls: Auto-extract content from URLs in message (NEW)
        
        Returns:
            Dict with response, sources, tokens
        """
        # Get and verify conversation
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            raise ConversationNotFoundError("Conversation not found")
        
        # ============================================================
        # NEW: Extract URL content if enabled
        # ============================================================
        url_content = ""
        url_metadata = []
        
        if auto_extract_urls:
            urls = extract_urls_from_text(content)
            
            for url in urls:
                try:
                    url_type = detect_url_type(url)
                    documents = await load_url(url)
                    
                    for doc in documents:
                        # Limit content to avoid token overflow
                        extracted_text = doc.page_content[:5000]
                        url_content += f"\n\n[Content from {url}]:\n{extracted_text}"
                        
                        url_metadata.append({
                            "url": url,
                            "type": url_type,
                            "title": doc.metadata.get("title", ""),
                            "chars_extracted": len(extracted_text),
                        })
                        
                except Exception as e:
                    logger.warning(f"Failed to extract URL {url}: {e}")
                    url_metadata.append({
                        "url": url,
                        "error": str(e),
                    })
        
        # ============================================================
        # Save user message
        # ============================================================
        message_attachments = {}
        if image_base64 or image_url:
            message_attachments["has_image"] = True
            if image_url:
                message_attachments["image_url"] = image_url
        if url_metadata:
            message_attachments["urls"] = url_metadata
        
        user_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            attachments=message_attachments if message_attachments else None
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
        
        # ============================================================
        # Build messages for LLM
        # ============================================================
        llm_messages = self._build_llm_messages(
            history, 
            context,
            url_content=url_content,  # NEW: Include URL content
        )
        
        # Build system prompt
        system_prompt = build_system_prompt(
            is_socratic=conversation.is_socratic,
            has_context=bool(context) or bool(url_content)
        )
        
        # ============================================================
        # Get LLM response (LangChain - same interface, different impl)
        # ============================================================
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
        
        # Broadcast messages for real-time sync
        await self._broadcast_new_message(conversation_id, user_message)
        await self._broadcast_new_message(conversation_id, assistant_message)
        
        result = {
            "message": MessageResponse.model_validate(assistant_message),
            "sources": sources,
            "tokens_used": response["tokens_used"]
        }
        
        # NEW: Include URL extraction info if any
        if url_metadata:
            result["urls_extracted"] = url_metadata
        
        return result
    
    # ============================================================
    # STREAMING (UPDATED FOR LANGCHAIN)
    # ============================================================
    
    async def send_message_stream(
        self,
        conversation_id: UUID,
        user_id: UUID,
        content: str,
        image_base64: Optional[str] = None,
        image_url: Optional[str] = None,
        auto_extract_urls: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Send a message and stream the AI response.
        
        Yields chunks as they're generated.
        
        Yields:
            Dict with type ('content', 'sources', 'urls', 'done', 'error')
        """
        # Get and verify conversation
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            yield {"type": "error", "error": "Conversation not found"}
            return
        
        # ============================================================
        # NEW: Extract URL content
        # ============================================================
        url_content = ""
        url_metadata = []
        
        if auto_extract_urls:
            urls = extract_urls_from_text(content)
            
            for url in urls:
                try:
                    url_type = detect_url_type(url)
                    documents = await load_url(url)
                    
                    for doc in documents:
                        extracted_text = doc.page_content[:5000]
                        url_content += f"\n\n[Content from {url}]:\n{extracted_text}"
                        
                        url_metadata.append({
                            "url": url,
                            "type": url_type,
                            "title": doc.metadata.get("title", ""),
                            "chars_extracted": len(extracted_text),
                        })
                        
                except Exception as e:
                    logger.warning(f"Failed to extract URL {url}: {e}")
                    url_metadata.append({
                        "url": url,
                        "error": str(e),
                    })
        
        # Yield URL extraction results
        if url_metadata:
            yield {"type": "urls", "urls": url_metadata}
        
        # Save user message
        message_attachments = {}
        if image_base64 or image_url:
            message_attachments["has_image"] = True
        if url_metadata:
            message_attachments["urls"] = url_metadata
        
        user_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            attachments=message_attachments if message_attachments else None
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
        llm_messages = self._build_llm_messages(
            history, 
            context,
            url_content=url_content,
        )
        system_prompt = build_system_prompt(
            is_socratic=conversation.is_socratic,
            has_context=bool(context) or bool(url_content)
        )
        
        # ============================================================
        # Handle image analysis (non-streaming part)
        # ============================================================
        image_analysis = None
        if image_base64 or image_url:
            try:
                from app.ai.llm.langchain_client import analyze_image
                logger.info("ChatService: Analyzing attached image...")
                
                image_analysis = await analyze_image(
                    image_base64=image_base64,
                    image_url=image_url,
                    prompt=content,
                    system_prompt=system_prompt
                )
                logger.info(f"ChatService: Image analysis complete, length={len(image_analysis)}")
            except Exception as e:
                logger.error(f"Image analysis failed: {e}")
                yield {"type": "error", "error": f"Image analysis failed: {str(e)}"}
                return
        
        # Stream response
        full_response = ""
        chunk_count = 0
        
        try:
            logger.info("ChatService: Starting LangChain streaming...")
            
            # ============================================================
            # If we have image analysis, stream it directly
            # Otherwise, use normal chat completion streaming
            # ============================================================
            if image_analysis:
                # Stream the image analysis response (already complete, but yield in chunks)
                chunk_size = 20
                for i in range(0, len(image_analysis), chunk_size):
                    chunk = image_analysis[i:i+chunk_size]
                    chunk_count += 1
                    full_response += chunk
                    yield {"type": "content", "content": chunk}
            else:
                # Normal text-only streaming
                async for chunk in chat_completion_stream(
                    messages=llm_messages,
                    system_prompt=system_prompt
                ):
                    chunk_count += 1
                    full_response += chunk
                    logger.debug(f"ChatService: Chunk #{chunk_count}, length={len(chunk)}")
                    yield {"type": "content", "content": chunk}
            
            logger.info(f"ChatService: Streaming complete, {chunk_count} chunks")
            
            # Save assistant message
            assistant_message = await self.message_repo.create_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=full_response,
                sources=[s.model_dump() for s in sources] if sources else None
            )
            
            # Update conversation
            await self.conversation_repo.touch(conversation_id)
            
            # Broadcast messages
            await self._broadcast_new_message(conversation_id, user_message)
            await self._broadcast_new_message(conversation_id, assistant_message)
            
            yield {
                "type": "done",
                "message_id": str(assistant_message.id)
            }
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield {"type": "error", "error": str(e)}
    
    # ============================================================
    # NEW: IMAGE ANALYSIS METHOD
    # ============================================================
    
    async def analyze_image_in_chat(
        self,
        conversation_id: UUID,
        user_id: UUID,
        prompt: str,
        image_base64: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an image within a conversation context.
        
        This method:
        1. Saves the user message with image reference
        2. Sends image + prompt to Gemini via LangChain
        3. Saves and returns the AI's analysis
        
        Args:
            conversation_id: Conversation UUID
            user_id: User's UUID
            prompt: User's question about the image
            image_base64: Base64-encoded image data
            image_url: URL to the image
        
        Returns:
            Dict with AI's image analysis
        """
        if not image_base64 and not image_url:
            raise ChatServiceError("Either image_base64 or image_url is required")
        
        # Verify conversation access
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        
        if not conversation or conversation.user_id != user_id:
            raise ConversationNotFoundError("Conversation not found")
        
        # Save user message
        user_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=prompt,
            attachments={
                "has_image": True,
                "image_url": image_url,
            }
        )
        
        # Build system prompt for image analysis
        system_prompt = build_system_prompt(
            is_socratic=conversation.is_socratic,
            has_context=True
        )
        system_prompt += "\n\nThe user has shared an image. Analyze it thoroughly and helpfully."
        
        # Get image analysis from LangChain
        analysis = await analyze_image(
            image_base64=image_base64,
            image_url=image_url,
            prompt=prompt,
            system_prompt=system_prompt
        )
        
        # Save assistant response
        assistant_message = await self.message_repo.create_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=analysis
        )
        
        # Update conversation
        await self.conversation_repo.touch(conversation_id)
        
        # Broadcast messages
        await self._broadcast_new_message(conversation_id, user_message)
        await self._broadcast_new_message(conversation_id, assistant_message)
        
        return {
            "message": MessageResponse.model_validate(assistant_message),
            "sources": [],
            "tokens_used": 0  # Token tracking for images is complex
        }
    
    # ============================================================
    # HELPER METHODS (UPDATED)
    # ============================================================
    
    def _build_llm_messages(
        self,
        history: List[Message],
        context: str = "",
        url_content: str = "",  # NEW parameter
    ) -> List[Dict[str, str]]:
        """Build message list for LLM."""
        messages = []
        
        # Add RAG context if available
        if context:
            context_prompt = build_context_prompt(context)
            messages.append({
                "role": "system",
                "content": context_prompt
            })
        
        # NEW: Add URL content if extracted
        if url_content:
            messages.append({
                "role": "system",
                "content": f"The user's message references URLs. Here is the extracted content:{url_content}"
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
        title = first_message[:50].strip()
        if len(first_message) > 50:
            title += "..."
        
        await self.conversation_repo.update(conversation_id, title=title)
    
    async def _broadcast_new_message(
        self,
        conversation_id: UUID,
        message: Message
    ) -> None:
        """Broadcast a new message to all connected WebSocket clients."""
        try:
            manager = get_connection_manager()
            
            message_data = {
                "id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "role": message.role.value if hasattr(message.role, 'value') else message.role,
                "content": message.content,
                "sources": message.sources,
                "tokens_used": message.tokens_used,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            
            await manager.broadcast_to_conversation(
                conversation_id=str(conversation_id),
                message=WebSocketMessage(
                    type=MessageTypes.NEW_MESSAGE,
                    conversation_id=str(conversation_id),
                    data=message_data
                )
            )
            logger.info(f"Broadcast new message {message.id} to conversation {conversation_id}")
        except Exception as e:
            logger.warning(f"Failed to broadcast message: {e}")