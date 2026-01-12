from sqlalchemy import Column, String, Integer, Float, ForeignKey, Text, DateTime, func, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
import enum
from app.db.database import Base

class QuizDifficulty(enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

class Quiz(Base):
    __tablename__ = "quizzes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Quiz info
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    difficulty = Column(
        Enum(
            QuizDifficulty, 
            name="quiz_difficulty", 
            values_callable=lambda x: [e.value for e in x]
        ),
        default=QuizDifficulty.MEDIUM,
        nullable=False,
        index=True
    )
    
    # Settings
    time_limit_minutes = Column(Integer, nullable=True)  # NULL = no limit
    passing_score = Column(Float, default=0.7, nullable=False)  # 0.7 = 70%
    
    # Topics covered
    topic_ids = Column(JSONB, nullable=True)  # ["topic-uuid-1", "topic-uuid-2"]
    
    # Stats
    question_count = Column(Integer, default=0, nullable=False)
    total_points = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),  
        nullable=False
    )
    
    # Relationships
    project = relationship("Project", back_populates="quizzes")
    questions = relationship("QuizQuestion", back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.display_order")
    attempts = relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan")