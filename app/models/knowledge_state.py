from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint
from .base import BaseModel

class KnowledgeState(BaseModel):
    __tablename__ = "knowledge_states"
    
    # Foreign Keys - Who knows what?
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=True, index=True)
    subtopic_id = Column(UUID(as_uuid=True), ForeignKey("subtopics.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Mastery tracking
    mastery_score = Column(Float, default=0.0, nullable=False)  # 0.0 to 1.0
    status = Column(String(20), default="not_started", nullable=False)
    
    # Performance data
    correct_count = Column(Integer, default=0, nullable=False)
    total_attempts = Column(Integer, default=0, nullable=False)
    misconceptions = Column(JSONB, default={}, nullable=False)
    last_reviewed = Column(DateTime(timezone=True), nullable=True)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'project_id', 'topic_id', 'subtopic_id', name='uq_user_project_topic_subtopic'),
    )
    
    # Relationships
    user = relationship("User", back_populates="knowledge_states")
    project = relationship("Project", back_populates="knowledge_states")
    topic = relationship("Topic", back_populates="knowledge_states")
    subtopic = relationship("Subtopic", back_populates="knowledge_states")