from sqlalchemy import Column, String, Integer, ForeignKey, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.database import Base
import uuid
from datetime import datetime

class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True)
    subtopic_id = Column(UUID(as_uuid=True), ForeignKey("subtopics.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Question content
    question_type = Column(String(30), nullable=False)  # multiple_choice, true_false, code_output, etc.
    question_text = Column(Text, nullable=False)
    code_snippet = Column(Text, nullable=True)  # For code questions
    
    # Answer options and correct answer
    options = Column(JSONB, nullable=True)       # For MCQ
    correct_answer = Column(JSONB, nullable=False)
    explanation = Column(Text, nullable=False)
    
    # Metadata
    points = Column(Integer, default=10, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),  
        nullable=False
    )
    
    # Relationships
    quiz = relationship("Quiz", back_populates="questions")
    subtopic = relationship("Subtopic", back_populates="quiz_questions")
    responses = relationship("QuizResponse", back_populates="question", cascade="all, delete-orphan")