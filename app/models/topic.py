from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.database import Base
import uuid
from .base import BaseModel


class Topic(BaseModel):
    __tablename__ = "topics"
    
    # Which project does this topic belong to?
    project_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("projects.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    
    # Which document was this topic extracted from? (optional)
    document_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("documents.id", ondelete="SET NULL"), 
        nullable=True, 
        index=True
    )
    
    # Topic details
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # Hierarchy within the project
    parent_topic_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("topics.id", ondelete="CASCADE"), 
        nullable=True, 
        index=True
    )
    
    # Where in the document(s) is this topic covered?
    source_references = Column(JSONB, nullable=True)
    # Example: [
    #   {"document_id": "doc-001", "pages": [1, 2, 3]},
    #   {"document_id": "doc-002", "slides": [5, 6, 7]}
    # ]
    
    # Was this extracted automatically by AI or created manually by user?
    is_auto_generated = Column(Boolean, default=True, nullable=False)
    
    # Display order for UI
    display_order = Column(Integer, default=0, nullable=False)
    
    
    # Relationships
    project = relationship("Project", back_populates="topics")
    document = relationship("Document", back_populates="topics")
    parent_topic = relationship("Topic", remote_side=[id], backref="child_topics")
    subtopics = relationship("Subtopic", back_populates="topic", cascade="all, delete-orphan")
    knowledge_states = relationship("KnowledgeState", back_populates="topic")



# ===================
# Subtopic Model
# ===================
class Subtopic(Base):
    __tablename__ = "subtopics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Which topic does this subtopic belong to?
    topic_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("topics.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    
    # Subtopic details
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # What should students learn about this subtopic?
    learning_objectives = Column(JSONB, nullable=True)
    # Example: [
    #   "Explain the process of mitosis",
    #   "Identify the 4 phases of mitosis",
    #   "Compare mitosis and meiosis"
    # ]
    
    # Where in the document(s) is this subtopic covered?
    source_references = Column(JSONB, nullable=True)
    # Example: [{"document_id": "doc-001", "pages": [1, 2]}]
    
    # Was this extracted automatically or created manually?
    is_auto_generated = Column(Boolean, default=True, nullable=False)
    
    display_order = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),  
        nullable=False
    )
    
    # Relationships
    topic = relationship("Topic", back_populates="subtopics")
    quiz_questions = relationship("QuizQuestion", back_populates="subtopic")
    knowledge_states = relationship("KnowledgeState", back_populates="subtopic")