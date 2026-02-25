"""
Quiz Schemas

Pydantic models for quiz-related API requests and responses.
"""

from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ============================================================
# Enums
# ============================================================

class QuizDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    CODE_OUTPUT = "code_output"


# ============================================================
# Request Schemas
# ============================================================

class QuizGenerateRequest(BaseModel):
    """Request to generate a quiz from project documents."""
    num_questions: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of questions to generate"
    )
    difficulty: QuizDifficulty = Field(
        default=QuizDifficulty.MEDIUM,
        description="Quiz difficulty level"
    )
    question_types: List[QuestionType] = Field(
        default_factory=lambda: [QuestionType.MULTIPLE_CHOICE, QuestionType.TRUE_FALSE],
        description="Types of questions to include"
    )
    topic_focus: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional topic to focus questions on"
    )
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="Custom quiz title (auto-generated if not provided)"
    )


class AnswerSubmission(BaseModel):
    """A single answer for one question."""
    question_id: UUID
    user_answer: Any = Field(..., description="The user's answer (varies by question type)")
    time_spent_seconds: Optional[int] = Field(None, ge=0)


class QuizSubmitRequest(BaseModel):
    """Request to submit answers for a quiz attempt."""
    answers: List[AnswerSubmission] = Field(
        ...,
        min_length=1,
        description="List of answers for each question"
    )
    time_taken_seconds: Optional[int] = Field(None, ge=0)


# ============================================================
# Response Schemas
# ============================================================

class QuestionOptionResponse(BaseModel):
    """A single option for a multiple-choice question."""
    key: str
    text: str


class QuestionResponse(BaseModel):
    """A quiz question returned to the client (no correct answer)."""
    id: UUID
    question_type: str
    question_text: str
    code_snippet: Optional[str] = None
    options: Optional[List[QuestionOptionResponse]] = None
    points: int
    display_order: int

    class Config:
        from_attributes = True


class QuestionWithAnswerResponse(QuestionResponse):
    """A quiz question with the correct answer (shown after submission)."""
    correct_answer: Any
    explanation: str
    user_answer: Optional[Any] = None
    is_correct: Optional[bool] = None
    points_earned: Optional[int] = None


class QuizResponse(BaseModel):
    """Quiz metadata response."""
    id: UUID
    project_id: UUID
    title: str
    description: Optional[str] = None
    difficulty: str
    time_limit_minutes: Optional[int] = None
    passing_score: float
    question_count: int
    total_points: int
    created_at: datetime

    class Config:
        from_attributes = True


class QuizDetailResponse(QuizResponse):
    """Quiz with questions (for taking the quiz)."""
    questions: List[QuestionResponse]


class QuizAttemptResponse(BaseModel):
    """Result of a quiz attempt."""
    id: UUID
    quiz_id: UUID
    score: int
    max_score: int
    percentage: float
    passed: bool
    time_taken_seconds: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QuizResultDetailResponse(QuizAttemptResponse):
    """Detailed quiz results with per-question breakdown."""
    questions: List[QuestionWithAnswerResponse]


class QuizListResponse(BaseModel):
    """Paginated list of quizzes."""
    quizzes: List[QuizResponse]
    total: int


class AttemptListResponse(BaseModel):
    """Paginated list of attempts for a quiz."""
    attempts: List[QuizAttemptResponse]
    total: int
