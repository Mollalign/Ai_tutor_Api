from sqlalchemy import Column, Integer, ForeignKey, Text, DateTime, func, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
import enum
from app.db.database import Base

# Message Roles
class MessageRole(enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        Enum(MessageRole, name="message_role", values_callable=lambda x: [e.value for e in x]), 
        nullable=False,
        index=True 
    )
    content = Column(Text, nullable=False)
    sources = Column(JSONB, nullable=True)     # Citations for AI responses
    tokens_used = Column(Integer, nullable=True)  # LLM token usage
    attachments = Column(JSONB, nullable=True)    # Additional data (images, URLs, etc.)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages")