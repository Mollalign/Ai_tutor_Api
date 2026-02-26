"""
Smart Tutor Service

Provides intelligent, adaptive learning features by analyzing
existing user data (knowledge states, quiz attempts, conversations).

Features:
- Adaptive quiz difficulty based on mastery scores
- Smart topic suggestions based on knowledge gaps
- Study plan generation with day-by-day scheduling
- Exam readiness scoring
- Cross-topic connection discovery
- Learning style inference from interaction patterns
"""

import logging
import math
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, cast, Date, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_state import KnowledgeState
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz import Quiz, QuizDifficulty
from app.models.quiz_question import QuizQuestion
from app.models.project import Project
from app.models.topic import Topic, Subtopic
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.repositories.project_repo import ProjectRepository
from app.repositories.knowledge_repo import KnowledgeStateRepository
from app.ai.llm.langchain_client import chat_completion

logger = logging.getLogger(__name__)


class SmartTutorService:
    """All intelligent/adaptive features in one service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.project_repo = ProjectRepository(db)

    # ================================================================
    # 1. ADAPTIVE DIFFICULTY
    # ================================================================

    async def get_adaptive_difficulty(
        self,
        user_id: UUID,
        project_id: UUID,
    ) -> Dict[str, Any]:
        """
        Recommend quiz difficulty based on the user's mastery level
        and recent quiz performance in this project.
        """
        result = await self.db.execute(
            select(
                func.avg(KnowledgeState.mastery_score),
                func.count(KnowledgeState.id),
            ).where(
                KnowledgeState.user_id == user_id,
                KnowledgeState.project_id == project_id,
            )
        )
        row = result.one()
        avg_mastery = float(row[0] or 0)
        topic_count = row[1] or 0

        result = await self.db.execute(
            select(
                func.avg(QuizAttempt.percentage),
                func.count(QuizAttempt.id),
            )
            .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
            .where(
                QuizAttempt.user_id == user_id,
                Quiz.project_id == project_id,
                QuizAttempt.completed_at.isnot(None),
            )
        )
        row = result.one()
        avg_quiz_score = float(row[0] or 0)
        quiz_count = row[1] or 0

        # Blend mastery and recent quiz performance
        if quiz_count == 0 and topic_count == 0:
            difficulty = "easy"
            confidence = 0.3
            reason = "No prior data — starting with easy questions."
        else:
            blended = (avg_mastery * 100 * 0.6) + (avg_quiz_score * 0.4) if quiz_count else avg_mastery * 100
            if blended >= 75:
                difficulty = "hard"
                reason = f"Strong mastery ({avg_mastery:.0%}) and quiz scores ({avg_quiz_score:.0f}%)."
            elif blended >= 40:
                difficulty = "medium"
                reason = f"Growing mastery ({avg_mastery:.0%}). Medium challenge is optimal."
            else:
                difficulty = "easy"
                reason = f"Building foundations ({avg_mastery:.0%}). Easy questions reinforce basics."
            confidence = min(1.0, (quiz_count + topic_count) / 10)

        return {
            "recommended_difficulty": difficulty,
            "confidence": round(confidence, 2),
            "reason": reason,
            "avg_mastery": round(avg_mastery, 3),
            "avg_quiz_score": round(avg_quiz_score, 1),
            "total_attempts": quiz_count,
        }

    # ================================================================
    # 2. SMART TOPIC SUGGESTIONS
    # ================================================================

    async def get_smart_suggestions(
        self,
        user_id: UUID,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        Analyse knowledge gaps across all projects and recommend
        what the student should study next.
        """
        # Weakest topics (lowest mastery that has been attempted)
        result = await self.db.execute(
            select(
                KnowledgeState.project_id,
                KnowledgeState.topic_id,
                KnowledgeState.subtopic_id,
                KnowledgeState.mastery_score,
                KnowledgeState.status,
                KnowledgeState.total_attempts,
                KnowledgeState.last_reviewed,
                Project.name.label("project_name"),
            )
            .join(Project, KnowledgeState.project_id == Project.id)
            .where(
                KnowledgeState.user_id == user_id,
                KnowledgeState.total_attempts > 0,
                KnowledgeState.mastery_score < 0.8,
            )
            .order_by(KnowledgeState.mastery_score.asc())
            .limit(limit * 2)
        )
        weak_states = result.all()

        # Enrich with topic names
        suggestions = []
        for ws in weak_states:
            topic_name = None
            subtopic_name = None
            if ws.topic_id:
                t = await self.db.get(Topic, ws.topic_id)
                topic_name = t.name if t else None
            if ws.subtopic_id:
                st = await self.db.get(Subtopic, ws.subtopic_id)
                subtopic_name = st.name if st else None

            days_since = None
            if ws.last_reviewed:
                days_since = (datetime.now(timezone.utc) - ws.last_reviewed).days

            priority = self._calc_priority(ws.mastery_score, days_since, ws.total_attempts)

            suggestions.append({
                "project_id": str(ws.project_id),
                "project_name": ws.project_name,
                "topic_id": str(ws.topic_id) if ws.topic_id else None,
                "topic_name": topic_name,
                "subtopic_id": str(ws.subtopic_id) if ws.subtopic_id else None,
                "subtopic_name": subtopic_name,
                "mastery_score": round(ws.mastery_score, 3),
                "status": ws.status,
                "days_since_review": days_since,
                "priority": round(priority, 2),
                "action": self._suggest_action(ws.mastery_score, days_since),
            })

        suggestions.sort(key=lambda x: x["priority"], reverse=True)
        suggestions = suggestions[:limit]

        # Also find topics never attempted
        result = await self.db.execute(
            select(Topic.id, Topic.name, Topic.project_id, Project.name.label("project_name"))
            .join(Project, Topic.project_id == Project.id)
            .where(Project.user_id == user_id)
            .limit(50)
        )
        all_topics = result.all()

        result = await self.db.execute(
            select(KnowledgeState.topic_id).where(
                KnowledgeState.user_id == user_id,
                KnowledgeState.topic_id.isnot(None),
            )
        )
        attempted_ids = {str(r[0]) for r in result.all()}

        not_started = []
        for t in all_topics:
            if str(t.id) not in attempted_ids:
                not_started.append({
                    "project_id": str(t.project_id),
                    "project_name": t.project_name,
                    "topic_id": str(t.id),
                    "topic_name": t.name,
                    "action": "Start learning this topic with a quiz",
                })
            if len(not_started) >= 3:
                break

        return {
            "weak_topics": suggestions,
            "not_started_topics": not_started,
            "total_weak": len(weak_states),
        }

    # ================================================================
    # 3. STUDY PLAN GENERATION
    # ================================================================

    async def generate_study_plan(
        self,
        user_id: UUID,
        project_id: UUID,
        exam_date: Optional[str] = None,
        daily_hours: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Generate a day-by-day study plan for a project.
        Uses AI to create a structured plan based on knowledge gaps.
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ValueError("Project not found")

        # Gather topic mastery
        result = await self.db.execute(
            select(Topic.id, Topic.name, Topic.description)
            .where(Topic.project_id == project_id)
            .order_by(Topic.display_order)
        )
        topics = result.all()

        topic_mastery = []
        for t in topics:
            result = await self.db.execute(
                select(func.avg(KnowledgeState.mastery_score)).where(
                    KnowledgeState.user_id == user_id,
                    KnowledgeState.topic_id == t.id,
                )
            )
            mastery = float(result.scalar() or 0)
            topic_mastery.append({
                "name": t.name,
                "description": t.description or "",
                "mastery": round(mastery, 2),
            })

        if exam_date:
            try:
                exam_dt = datetime.strptime(exam_date, "%Y-%m-%d").date()
            except ValueError:
                exam_dt = date.today() + timedelta(days=14)
        else:
            exam_dt = date.today() + timedelta(days=14)

        days_until = max(1, (exam_dt - date.today()).days)

        prompt = self._build_study_plan_prompt(
            project_name=project.name,
            topics=topic_mastery,
            days_until_exam=days_until,
            daily_hours=daily_hours,
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You are a study planning expert. Create a structured, actionable "
                "study plan. Focus more time on weak topics. "
                "Return ONLY valid JSON, no markdown fences, no extra text."
            ),
            temperature=0.3,
            max_tokens=4096,
        )

        import json, re
        raw = response["content"].strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if fence_match:
            raw = fence_match.group(1).strip()

        # Try to find JSON object even if surrounded by extra text
        if not raw.startswith("{"):
            brace_start = raw.find("{")
            if brace_start != -1:
                raw = raw[brace_start:]

        # Trim trailing garbage after last }
        last_brace = raw.rfind("}")
        if last_brace != -1:
            raw = raw[: last_brace + 1]

        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Study plan JSON parse failed, wrapping as summary")
            plan = {"days": [], "summary": raw[:1000]}

        return {
            "project_id": str(project_id),
            "project_name": project.name,
            "exam_date": str(exam_dt),
            "days_until_exam": days_until,
            "daily_hours": daily_hours,
            "plan": plan,
            "topic_mastery": topic_mastery,
        }

    # ================================================================
    # 4. EXAM READINESS SCORE
    # ================================================================

    async def get_exam_readiness(
        self,
        user_id: UUID,
        project_id: UUID,
    ) -> Dict[str, Any]:
        """
        Calculate a readiness percentage based on mastery, quiz performance,
        coverage, and recency of study.
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ValueError("Project not found")

        # Total topics in project
        result = await self.db.execute(
            select(func.count(Topic.id)).where(Topic.project_id == project_id)
        )
        total_topics = result.scalar() or 0

        # Knowledge states for this project
        result = await self.db.execute(
            select(KnowledgeState).where(
                KnowledgeState.user_id == user_id,
                KnowledgeState.project_id == project_id,
            )
        )
        states = result.scalars().all()

        if not states and total_topics == 0:
            return {
                "readiness_score": 0,
                "grade": "Not Started",
                "breakdown": {},
                "recommendations": ["Upload documents and extract topics to get started."],
            }

        # 1. Mastery score (40% weight)
        avg_mastery = sum(s.mastery_score for s in states) / len(states) if states else 0

        # 2. Coverage (20% weight) — how many topics have been studied
        studied_topics = len({s.topic_id for s in states if s.topic_id and s.total_attempts > 0})
        coverage = studied_topics / total_topics if total_topics > 0 else 0

        # 3. Quiz performance (25% weight)
        result = await self.db.execute(
            select(func.avg(QuizAttempt.percentage), func.count(QuizAttempt.id))
            .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
            .where(
                QuizAttempt.user_id == user_id,
                Quiz.project_id == project_id,
                QuizAttempt.completed_at.isnot(None),
            )
        )
        row = result.one()
        avg_quiz = float(row[0] or 0) / 100
        quiz_count = row[1] or 0

        # 4. Recency (15% weight) — have you studied recently?
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent_states = [s for s in states if s.last_reviewed and s.last_reviewed >= recent_cutoff]
        recency = min(1.0, len(recent_states) / max(1, len(states)))

        readiness = (
            avg_mastery * 0.40
            + coverage * 0.20
            + avg_quiz * 0.25
            + recency * 0.15
        )
        readiness_pct = round(readiness * 100, 1)

        grade = self._readiness_grade(readiness_pct)

        # Build recommendations
        recommendations = []
        if coverage < 0.5:
            unstudied = total_topics - studied_topics
            recommendations.append(f"You haven't studied {unstudied} of {total_topics} topics yet.")
        if avg_mastery < 0.5:
            recommendations.append("Focus on weak topics — take more quizzes to improve mastery.")
        if quiz_count < 3:
            recommendations.append("Take more practice quizzes to solidify your knowledge.")
        if recency < 0.3:
            recommendations.append("You haven't studied recently. A review session would help.")
        if readiness_pct >= 80:
            recommendations.append("Great progress! Do a final review of your weakest topics.")

        # Weakest topics
        weak = sorted(states, key=lambda s: s.mastery_score)[:3]
        weak_topics = []
        for w in weak:
            name = None
            if w.topic_id:
                t = await self.db.get(Topic, w.topic_id)
                name = t.name if t else None
            weak_topics.append({
                "topic_name": name or "Unknown",
                "mastery": round(w.mastery_score, 2),
            })

        return {
            "readiness_score": readiness_pct,
            "grade": grade,
            "breakdown": {
                "mastery": round(avg_mastery * 100, 1),
                "coverage": round(coverage * 100, 1),
                "quiz_performance": round(avg_quiz * 100, 1),
                "recency": round(recency * 100, 1),
            },
            "total_topics": total_topics,
            "studied_topics": studied_topics,
            "quiz_count": quiz_count,
            "weak_topics": weak_topics,
            "recommendations": recommendations,
        }

    # ================================================================
    # 5. CROSS-TOPIC CONNECTIONS
    # ================================================================

    async def get_cross_connections(
        self,
        user_id: UUID,
        project_id: UUID,
    ) -> Dict[str, Any]:
        """
        Use AI to discover connections between topics in this project
        and topics in the user's other projects.
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ValueError("Project not found")

        # Current project topics
        result = await self.db.execute(
            select(Topic.name).where(Topic.project_id == project_id)
        )
        current_topics = [r[0] for r in result.all()]

        # Other project topics
        result = await self.db.execute(
            select(Project.name, Topic.name)
            .join(Topic, Topic.project_id == Project.id)
            .where(
                Project.user_id == user_id,
                Project.id != project_id,
            )
            .limit(50)
        )
        other_topics = [{"project": r[0], "topic": r[1]} for r in result.all()]

        if not current_topics or not other_topics:
            return {"connections": [], "message": "Need topics in multiple projects to find connections."}

        prompt = (
            f"Current project: {project.name}\n"
            f"Current topics: {', '.join(current_topics[:20])}\n\n"
            f"Other projects and topics:\n"
        )
        for ot in other_topics[:30]:
            prompt += f"- {ot['project']}: {ot['topic']}\n"

        prompt += (
            "\nFind meaningful connections between the current project topics and "
            "topics from other projects. Return JSON array of objects with fields: "
            "current_topic, related_topic, related_project, connection_explanation. "
            "Return ONLY valid JSON, no markdown."
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You are an educational expert. Find genuine conceptual connections "
                "between topics across different courses/subjects. Return valid JSON only."
            ),
            temperature=0.3,
            max_tokens=1024,
        )

        import json
        raw = response["content"].strip()
        if raw.startswith("```"):
            lines = raw.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        try:
            connections = json.loads(raw)
        except json.JSONDecodeError:
            connections = []

        return {
            "project_name": project.name,
            "connections": connections if isinstance(connections, list) else [],
        }

    # ================================================================
    # 6. LEARNING STYLE DETECTION
    # ================================================================

    async def detect_learning_style(
        self,
        user_id: UUID,
    ) -> Dict[str, Any]:
        """
        Infer learning style from interaction patterns:
        - Conversation length & question types
        - Quiz performance across difficulties
        - Socratic mode preference
        """
        # Check Socratic preference
        result = await self.db.execute(
            select(
                func.count(Conversation.id).filter(Conversation.is_socratic.is_(True)).label("socratic"),
                func.count(Conversation.id).filter(Conversation.is_socratic.is_(False)).label("direct"),
            ).where(Conversation.user_id == user_id)
        )
        row = result.one()
        socratic_count = row.socratic or 0
        direct_count = row.direct or 0

        # Average message length (indicates preference for detail)
        result = await self.db.execute(
            select(func.avg(func.length(Message.content)))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == user_id,
                Message.role == MessageRole.USER,
            )
        )
        avg_msg_length = float(result.scalar() or 0)

        # Quiz performance by difficulty
        result = await self.db.execute(
            select(Quiz.difficulty, func.avg(QuizAttempt.percentage))
            .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
            .where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.completed_at.isnot(None),
            )
            .group_by(Quiz.difficulty)
        )
        perf_by_diff = {
            (r[0].value if hasattr(r[0], "value") else str(r[0])): round(float(r[1] or 0), 1)
            for r in result.all()
        }

        # Total conversations & quizzes
        result = await self.db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        total_convos = result.scalar() or 0

        result = await self.db.execute(
            select(func.count(QuizAttempt.id)).where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.completed_at.isnot(None),
            )
        )
        total_quizzes = result.scalar() or 0

        # Determine style
        style = self._classify_learning_style(
            socratic_count, direct_count,
            avg_msg_length, total_convos, total_quizzes,
        )

        return {
            "primary_style": style["primary"],
            "description": style["description"],
            "traits": style["traits"],
            "stats": {
                "socratic_conversations": socratic_count,
                "direct_conversations": direct_count,
                "avg_message_length": round(avg_msg_length),
                "total_conversations": total_convos,
                "total_quizzes": total_quizzes,
                "performance_by_difficulty": perf_by_diff,
            },
            "ai_prompt_hint": style["prompt_hint"],
        }

    # ================================================================
    # 7. CONVERSATION MEMORY CONTEXT
    # ================================================================

    async def get_conversation_memory(
        self,
        user_id: UUID,
        project_id: Optional[UUID],
        current_conversation_id: UUID,
        limit: int = 3,
    ) -> str:
        """
        Build a brief summary of the user's recent conversations
        to inject into the current chat for continuity.
        """
        query = (
            select(Conversation.title, Message.content)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == user_id,
                Conversation.id != current_conversation_id,
                Message.role == MessageRole.USER,
            )
            .order_by(Conversation.updated_at.desc(), Message.created_at.desc())
            .limit(limit * 2)
        )
        if project_id:
            query = query.where(Conversation.project_id == project_id)

        result = await self.db.execute(query)
        rows = result.all()

        if not rows:
            return ""

        seen_titles = set()
        summaries = []
        for title, content in rows:
            t = title or "Untitled"
            if t in seen_titles:
                continue
            seen_titles.add(t)
            snippet = content[:120].replace("\n", " ")
            summaries.append(f'- "{t}": {snippet}')
            if len(summaries) >= limit:
                break

        return (
            "The student has recently discussed these topics in other conversations:\n"
            + "\n".join(summaries)
            + "\nYou may reference these if relevant to build continuity."
        )

    # ================================================================
    # PRIVATE HELPERS
    # ================================================================

    @staticmethod
    def _calc_priority(mastery: float, days_since: Optional[int], attempts: int) -> float:
        gap_score = 1.0 - mastery
        recency_score = min(1.0, (days_since or 0) / 14) if days_since else 0.3
        effort_score = min(1.0, attempts / 5)
        return gap_score * 0.5 + recency_score * 0.3 + effort_score * 0.2

    @staticmethod
    def _suggest_action(mastery: float, days_since: Optional[int]) -> str:
        if mastery < 0.3:
            return "Review fundamentals and take an easy quiz"
        if mastery < 0.6:
            return "Take a medium quiz to strengthen understanding"
        if days_since and days_since > 7:
            return "Quick review — it's been a while since you studied this"
        return "Take a hard quiz to push toward mastery"

    @staticmethod
    def _readiness_grade(score: float) -> str:
        if score >= 85:
            return "Excellent"
        if score >= 70:
            return "Good"
        if score >= 50:
            return "Fair"
        if score >= 30:
            return "Needs Work"
        return "Not Ready"

    @staticmethod
    def _build_study_plan_prompt(
        project_name: str,
        topics: List[Dict],
        days_until_exam: int,
        daily_hours: float,
    ) -> str:
        topics_str = "\n".join(
            f"- {t['name']} (mastery: {t['mastery']:.0%})"
            for t in topics[:15]
        )
        # For long plans, group into phases instead of individual days
        if days_until_exam > 10:
            day_instruction = (
                f"Group the {days_until_exam} days into phases (e.g. 'Days 1-3', 'Days 4-6'). "
                f"Return 5-8 phase entries max."
            )
        else:
            day_instruction = f"Create one entry per day ({days_until_exam} entries)."

        return (
            f"Create a study plan for '{project_name}'. "
            f"Student has {daily_hours}h/day, {days_until_exam} days until exam.\n\n"
            f"Topics and mastery:\n{topics_str}\n\n"
            f"Rules: Spend more time on low-mastery topics. Include quizzes every 2-3 days. "
            f"Final review before exam.\n"
            f"{day_instruction}\n\n"
            f'Return compact JSON: {{"summary":"brief overview",'
            f'"days":[{{"day":1,"focus":"topic focus","topics":["t1"],'
            f'"activities":["activity1","activity2"],"hours":2.0}}]}}\n'
            f"Keep activity descriptions short (under 8 words each). No markdown."
        )

    @staticmethod
    def _classify_learning_style(
        socratic: int, direct: int,
        avg_msg_len: float, convos: int, quizzes: int,
    ) -> Dict[str, Any]:
        if convos == 0 and quizzes == 0:
            return {
                "primary": "unknown",
                "description": "Not enough data yet. Keep using the app!",
                "traits": [],
                "prompt_hint": "",
            }

        traits = []

        if socratic > direct:
            traits.append("Prefers guided discovery (Socratic)")
        elif direct > socratic:
            traits.append("Prefers direct explanations")

        if avg_msg_len > 150:
            traits.append("Asks detailed, thorough questions")
        elif avg_msg_len < 50:
            traits.append("Asks concise, focused questions")

        if quizzes > convos:
            traits.append("Practice-oriented learner")
        elif convos > quizzes * 2:
            traits.append("Discussion-oriented learner")

        # Classify
        if quizzes > convos and avg_msg_len < 80:
            primary = "practical"
            desc = "You learn best through practice and testing. You prefer doing over reading."
            hint = "Use concrete examples, code snippets, and practice problems. Be concise."
        elif socratic > direct and avg_msg_len > 100:
            primary = "reflective"
            desc = "You learn through deep thinking and guided questions. You enjoy exploring concepts."
            hint = "Use Socratic questioning. Encourage the student to think through problems step by step."
        elif direct > socratic and avg_msg_len > 120:
            primary = "theoretical"
            desc = "You prefer comprehensive explanations with strong theoretical foundations."
            hint = "Provide detailed theoretical explanations with examples. Structure answers clearly."
        else:
            primary = "balanced"
            desc = "You use a mix of learning strategies. You adapt based on the topic."
            hint = "Mix explanations with examples and practice problems. Be adaptable."

        return {
            "primary": primary,
            "description": desc,
            "traits": traits,
            "prompt_hint": hint,
        }
