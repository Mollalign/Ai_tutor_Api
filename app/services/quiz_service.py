"""
Quiz Service

Business logic for quiz operations:
- AI-powered quiz generation from project documents
- Quiz attempt management and grading
- Knowledge state updates after quiz completion
"""

import json
import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quiz import Quiz, QuizDifficulty
from app.models.quiz_question import QuizQuestion
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse as QuizResponseModel
from app.repositories.quiz_repo import (
    QuizRepository,
    QuizQuestionRepository,
    QuizAttemptRepository,
    QuizResponseRepository,
)
from app.repositories.project_repo import ProjectRepository
from app.schemas.quiz import (
    QuizGenerateRequest,
    QuizSubmitRequest,
    QuizResponse,
    QuizDetailResponse,
    QuestionResponse,
    QuestionOptionResponse,
    QuestionWithAnswerResponse,
    QuizAttemptResponse,
    QuizResultDetailResponse,
)
from app.services.knowledge_service import KnowledgeService
from app.ai.rag import get_retriever, Retriever
from app.ai.prompts.quiz_prompts import (
    build_quiz_generation_prompt,
    build_quiz_context_prompt,
)
from app.ai.llm.langchain_client import chat_completion

logger = logging.getLogger(__name__)


class QuizServiceError(Exception):
    pass


class QuizNotFoundError(QuizServiceError):
    pass


class ProjectNotFoundError(QuizServiceError):
    pass


class QuizService:
    """Service for quiz generation, taking, and grading."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.quiz_repo = QuizRepository(db)
        self.question_repo = QuizQuestionRepository(db)
        self.attempt_repo = QuizAttemptRepository(db)
        self.response_repo = QuizResponseRepository(db)
        self.project_repo = ProjectRepository(db)
        self.retriever: Retriever = get_retriever()

    # ============================================================
    # GENERATE QUIZ (AI-powered)
    # ============================================================

    async def generate_quiz(
        self,
        project_id: UUID,
        user_id: UUID,
        request: QuizGenerateRequest,
    ) -> QuizDetailResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundError("Project not found")

        topic_query = request.topic_focus or "main topics and key concepts"
        context = self.retriever.retrieve_for_context(
            query=topic_query,
            project_id=project_id,
            max_tokens=3000,
            top_k=15,
        )

        if not context:
            raise QuizServiceError(
                "No document content found. Upload and process documents first."
            )

        system_prompt = build_quiz_generation_prompt(
            num_questions=request.num_questions,
            difficulty=request.difficulty.value,
            question_types=[qt.value for qt in request.question_types],
            topic_focus=request.topic_focus,
        )
        context_prompt = build_quiz_context_prompt(context)

        messages = [{"role": "user", "content": context_prompt}]

        response = await chat_completion(
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.4,
            max_tokens=4096,
        )

        quiz_data = self._parse_quiz_json(response["content"])

        difficulty_enum = QuizDifficulty(request.difficulty.value)
        quiz = await self.quiz_repo.create(
            project_id=project_id,
            title=request.title or quiz_data.get("title", "Generated Quiz"),
            description=quiz_data.get("description"),
            difficulty=difficulty_enum,
            passing_score=0.7,
            question_count=0,
            total_points=0,
        )

        questions_data = quiz_data.get("questions", [])
        db_questions = []
        total_points = 0

        for i, q_data in enumerate(questions_data):
            options = q_data.get("options")
            if isinstance(options, dict):
                options = options
            
            correct_answer = q_data.get("correct_answer")
            points = q_data.get("points", 10)
            total_points += points

            question = QuizQuestion(
                quiz_id=quiz.id,
                question_type=q_data.get("question_type", "multiple_choice"),
                question_text=q_data["question_text"],
                code_snippet=q_data.get("code_snippet"),
                options=options,
                correct_answer=correct_answer,
                explanation=q_data.get("explanation", ""),
                points=points,
                display_order=i,
            )
            self.db.add(question)
            db_questions.append(question)

        await self.db.flush()
        for q in db_questions:
            await self.db.refresh(q)

        quiz.question_count = len(db_questions)
        quiz.total_points = total_points
        await self.db.commit()
        await self.db.refresh(quiz)

        return self._build_quiz_detail_response(quiz, db_questions)

    # ============================================================
    # LIST QUIZZES
    # ============================================================

    async def list_quizzes(
        self,
        project_id: UUID,
        user_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[QuizResponse], int]:
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundError("Project not found")

        quizzes = await self.quiz_repo.get_by_project(project_id, skip, limit)
        total = await self.quiz_repo.count_by_project(project_id)

        responses = [
            QuizResponse(
                id=q.id,
                project_id=q.project_id,
                title=q.title,
                description=q.description,
                difficulty=q.difficulty.value if hasattr(q.difficulty, "value") else q.difficulty,
                time_limit_minutes=q.time_limit_minutes,
                passing_score=q.passing_score,
                question_count=q.question_count,
                total_points=q.total_points,
                created_at=q.created_at,
            )
            for q in quizzes
        ]
        return responses, total

    # ============================================================
    # GET QUIZ (for taking)
    # ============================================================

    async def get_quiz(
        self,
        quiz_id: UUID,
        user_id: UUID,
    ) -> QuizDetailResponse:
        quiz = await self.quiz_repo.get_with_questions(quiz_id)
        if not quiz:
            raise QuizNotFoundError("Quiz not found")

        project = await self.project_repo.get_by_id(quiz.project_id)
        if not project or project.user_id != user_id:
            raise QuizNotFoundError("Quiz not found")

        return self._build_quiz_detail_response(quiz, quiz.questions)

    # ============================================================
    # SUBMIT QUIZ ATTEMPT
    # ============================================================

    async def submit_quiz(
        self,
        quiz_id: UUID,
        user_id: UUID,
        submission: QuizSubmitRequest,
    ) -> QuizResultDetailResponse:
        quiz = await self.quiz_repo.get_with_questions(quiz_id)
        if not quiz:
            raise QuizNotFoundError("Quiz not found")

        project = await self.project_repo.get_by_id(quiz.project_id)
        if not project or project.user_id != user_id:
            raise QuizNotFoundError("Quiz not found")

        questions_by_id = {str(q.id): q for q in quiz.questions}

        attempt = QuizAttempt(
            user_id=user_id,
            quiz_id=quiz_id,
        )
        self.db.add(attempt)
        await self.db.flush()
        await self.db.refresh(attempt)

        total_score = 0
        max_score = quiz.total_points
        response_details = []

        for answer in submission.answers:
            question = questions_by_id.get(str(answer.question_id))
            if not question:
                continue

            is_correct = self._check_answer(question, answer.user_answer)
            points_earned = question.points if is_correct else 0
            total_score += points_earned

            quiz_response = QuizResponseModel(
                attempt_id=attempt.id,
                question_id=question.id,
                user_answer=answer.user_answer,
                is_correct=is_correct,
                points_earned=points_earned,
                time_spent_seconds=answer.time_spent_seconds,
            )
            self.db.add(quiz_response)

            response_details.append({
                "question": question,
                "user_answer": answer.user_answer,
                "is_correct": is_correct,
                "points_earned": points_earned,
            })

        percentage = (total_score / max_score * 100) if max_score > 0 else 0
        passed = percentage >= (quiz.passing_score * 100)

        attempt.score = total_score
        attempt.max_score = max_score
        attempt.percentage = percentage
        attempt.passed = passed
        attempt.time_taken_seconds = submission.time_taken_seconds
        attempt.completed_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(attempt)

        # Update knowledge states from quiz results
        try:
            knowledge_service = KnowledgeService(self.db)
            knowledge_updates = [
                {
                    "subtopic_id": str(d["question"].subtopic_id) if d["question"].subtopic_id else None,
                    "is_correct": d["is_correct"],
                }
                for d in response_details
            ]
            await knowledge_service.update_from_quiz(
                user_id=user_id,
                project_id=quiz.project_id,
                question_results=knowledge_updates,
            )
        except Exception as e:
            logger.warning(f"Failed to update knowledge states: {e}")

        question_results = []
        for detail in response_details:
            q = detail["question"]
            options = self._format_options(q.options) if q.options else None

            question_results.append(
                QuestionWithAnswerResponse(
                    id=q.id,
                    question_type=q.question_type,
                    question_text=q.question_text,
                    code_snippet=q.code_snippet,
                    options=options,
                    points=q.points,
                    display_order=q.display_order,
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    user_answer=detail["user_answer"],
                    is_correct=detail["is_correct"],
                    points_earned=detail["points_earned"],
                )
            )

        return QuizResultDetailResponse(
            id=attempt.id,
            quiz_id=attempt.quiz_id,
            score=attempt.score,
            max_score=attempt.max_score,
            percentage=attempt.percentage,
            passed=attempt.passed,
            time_taken_seconds=attempt.time_taken_seconds,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            questions=question_results,
        )

    # ============================================================
    # GET ATTEMPT RESULTS
    # ============================================================

    async def get_attempt_result(
        self,
        attempt_id: UUID,
        user_id: UUID,
    ) -> QuizResultDetailResponse:
        attempt = await self.attempt_repo.get_with_responses(attempt_id)
        if not attempt or attempt.user_id != user_id:
            raise QuizNotFoundError("Attempt not found")

        quiz = await self.quiz_repo.get_with_questions(attempt.quiz_id)
        if not quiz:
            raise QuizNotFoundError("Quiz not found")

        responses_by_question = {
            str(r.question_id): r for r in attempt.responses
        }

        question_results = []
        for q in quiz.questions:
            resp = responses_by_question.get(str(q.id))
            options = self._format_options(q.options) if q.options else None

            question_results.append(
                QuestionWithAnswerResponse(
                    id=q.id,
                    question_type=q.question_type,
                    question_text=q.question_text,
                    code_snippet=q.code_snippet,
                    options=options,
                    points=q.points,
                    display_order=q.display_order,
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    user_answer=resp.user_answer if resp else None,
                    is_correct=resp.is_correct if resp else None,
                    points_earned=resp.points_earned if resp else None,
                )
            )

        return QuizResultDetailResponse(
            id=attempt.id,
            quiz_id=attempt.quiz_id,
            score=attempt.score or 0,
            max_score=attempt.max_score or 0,
            percentage=attempt.percentage or 0,
            passed=attempt.passed or False,
            time_taken_seconds=attempt.time_taken_seconds,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            questions=question_results,
        )

    # ============================================================
    # LIST ATTEMPTS
    # ============================================================

    async def list_attempts(
        self,
        quiz_id: UUID,
        user_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[QuizAttemptResponse], int]:
        quiz = await self.quiz_repo.get_by_id(quiz_id)
        if not quiz:
            raise QuizNotFoundError("Quiz not found")

        project = await self.project_repo.get_by_id(quiz.project_id)
        if not project or project.user_id != user_id:
            raise QuizNotFoundError("Quiz not found")

        attempts = await self.attempt_repo.get_user_attempts(
            user_id, quiz_id, skip, limit
        )
        total = await self.attempt_repo.count_user_attempts(user_id, quiz_id)

        responses = [
            QuizAttemptResponse(
                id=a.id,
                quiz_id=a.quiz_id,
                score=a.score or 0,
                max_score=a.max_score or 0,
                percentage=a.percentage or 0,
                passed=a.passed or False,
                time_taken_seconds=a.time_taken_seconds,
                started_at=a.started_at,
                completed_at=a.completed_at,
            )
            for a in attempts
        ]
        return responses, total

    # ============================================================
    # DELETE QUIZ
    # ============================================================

    async def delete_quiz(
        self,
        quiz_id: UUID,
        user_id: UUID,
    ) -> bool:
        quiz = await self.quiz_repo.get_by_id(quiz_id)
        if not quiz:
            raise QuizNotFoundError("Quiz not found")

        project = await self.project_repo.get_by_id(quiz.project_id)
        if not project or project.user_id != user_id:
            raise QuizNotFoundError("Quiz not found")

        return await self.quiz_repo.delete(quiz_id)

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    def _parse_quiz_json(self, raw_content: str) -> dict:
        content = raw_content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse quiz JSON: {e}\nRaw: {content[:500]}")
            raise QuizServiceError(
                "Failed to parse AI-generated quiz. Please try again."
            )

    def _check_answer(self, question: QuizQuestion, user_answer: Any) -> bool:
        correct = question.correct_answer
        if isinstance(correct, str) and isinstance(user_answer, str):
            return correct.strip().upper() == user_answer.strip().upper()
        return correct == user_answer

    def _format_options(self, options: Any) -> Optional[List[QuestionOptionResponse]]:
        if not options:
            return None
        if isinstance(options, dict):
            return [
                QuestionOptionResponse(key=k, text=v)
                for k, v in options.items()
            ]
        return None

    def _build_quiz_detail_response(
        self, quiz: Quiz, questions: List[QuizQuestion]
    ) -> QuizDetailResponse:
        q_responses = []
        for q in questions:
            options = self._format_options(q.options) if q.options else None
            q_responses.append(
                QuestionResponse(
                    id=q.id,
                    question_type=q.question_type,
                    question_text=q.question_text,
                    code_snippet=q.code_snippet,
                    options=options,
                    points=q.points,
                    display_order=q.display_order,
                )
            )

        return QuizDetailResponse(
            id=quiz.id,
            project_id=quiz.project_id,
            title=quiz.title,
            description=quiz.description,
            difficulty=quiz.difficulty.value if hasattr(quiz.difficulty, "value") else quiz.difficulty,
            time_limit_minutes=quiz.time_limit_minutes,
            passing_score=quiz.passing_score,
            question_count=quiz.question_count,
            total_points=quiz.total_points,
            created_at=quiz.created_at,
            questions=q_responses,
        )
