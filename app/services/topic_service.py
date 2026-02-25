"""
Topic Service

Business logic for AI-powered topic extraction from project documents.
"""

import json
import logging
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topic import Topic, Subtopic
from app.repositories.topic_repo import TopicRepository, SubtopicRepository
from app.repositories.project_repo import ProjectRepository
from app.schemas.topic import TopicResponse, SubtopicResponse
from app.ai.rag import get_retriever, Retriever
from app.ai.prompts.topic_prompts import (
    build_topic_extraction_prompt,
    build_topic_context_prompt,
)
from app.ai.llm.langchain_client import chat_completion

logger = logging.getLogger(__name__)


class TopicServiceError(Exception):
    pass


class ProjectNotFoundError(TopicServiceError):
    pass


class TopicService:
    """Service for topic extraction and management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.topic_repo = TopicRepository(db)
        self.subtopic_repo = SubtopicRepository(db)
        self.project_repo = ProjectRepository(db)
        self.retriever: Retriever = get_retriever()

    # ============================================================
    # EXTRACT TOPICS (AI-powered)
    # ============================================================

    async def extract_topics(
        self,
        project_id: UUID,
        user_id: UUID,
        force_refresh: bool = False,
    ) -> List[TopicResponse]:
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundError("Project not found")

        existing = await self.topic_repo.count_by_project(project_id)
        if existing > 0 and not force_refresh:
            return await self.list_topics(project_id, user_id)

        if force_refresh and existing > 0:
            await self.topic_repo.delete_by_project(project_id)

        context = self.retriever.retrieve_for_context(
            query="main topics, chapters, and key concepts covered",
            project_id=project_id,
            max_tokens=4000,
            top_k=20,
        )

        if not context:
            raise TopicServiceError(
                "No document content found. Upload and process documents first."
            )

        system_prompt = build_topic_extraction_prompt()
        context_prompt = build_topic_context_prompt(context)

        response = await chat_completion(
            messages=[{"role": "user", "content": context_prompt}],
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=8192,
        )

        try:
            topics_data = self._parse_topics_json(response["content"])
        except TopicServiceError:
            logger.warning("First topic extraction attempt failed, retrying with shorter prompt")
            retry_response = await chat_completion(
                messages=[{"role": "user", "content": context_prompt + "\n\nIMPORTANT: Keep output SHORT. Max 4 topics, 3 subtopics each, 2 objectives each. Descriptions under 10 words."}],
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=8192,
            )
            topics_data = self._parse_topics_json(retry_response["content"])

        topic_pairs: list[tuple[Topic, list[Subtopic]]] = []
        for i, t_data in enumerate(topics_data):
            topic = Topic(
                project_id=project_id,
                name=t_data["name"],
                description=t_data.get("description"),
                is_auto_generated=True,
                display_order=i,
            )
            self.db.add(topic)
            await self.db.flush()
            await self.db.refresh(topic)

            subtopics = []
            for j, s_data in enumerate(t_data.get("subtopics", [])):
                subtopic = Subtopic(
                    topic_id=topic.id,
                    name=s_data["name"],
                    description=s_data.get("description"),
                    learning_objectives=s_data.get("learning_objectives"),
                    is_auto_generated=True,
                    display_order=j,
                )
                self.db.add(subtopic)
                subtopics.append(subtopic)

            await self.db.flush()
            for st in subtopics:
                await self.db.refresh(st)

            topic_pairs.append((topic, subtopics))

        await self.db.commit()

        return [
            self._build_topic_response(t, explicit_subtopics=subs)
            for t, subs in topic_pairs
        ]

    # ============================================================
    # LIST TOPICS
    # ============================================================

    async def list_topics(
        self,
        project_id: UUID,
        user_id: UUID,
    ) -> List[TopicResponse]:
        project = await self.project_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundError("Project not found")

        topics = await self.topic_repo.get_by_project(project_id)
        return [self._build_topic_response(t) for t in topics]

    # ============================================================
    # HELPERS
    # ============================================================

    def _parse_topics_json(self, raw_content: str) -> list:
        content = raw_content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "topics" in data:
                return data["topics"]
            return [data]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse topics JSON: {e}\nRaw: {content[:500]}")
            raise TopicServiceError(
                "Failed to parse AI-generated topics. Please try again."
            )

    def _build_topic_response(
        self,
        topic: Topic,
        explicit_subtopics: list[Subtopic] | None = None,
    ) -> TopicResponse:
        subs = explicit_subtopics if explicit_subtopics is not None else (topic.subtopics or [])
        subtopic_responses = [
            SubtopicResponse(
                id=st.id,
                name=st.name,
                description=st.description,
                learning_objectives=st.learning_objectives,
                is_auto_generated=st.is_auto_generated,
                display_order=st.display_order,
            )
            for st in subs
        ]

        return TopicResponse(
            id=topic.id,
            project_id=topic.project_id,
            name=topic.name,
            description=topic.description,
            is_auto_generated=topic.is_auto_generated,
            display_order=topic.display_order,
            subtopics=subtopic_responses,
            created_at=topic.created_at,
        )
