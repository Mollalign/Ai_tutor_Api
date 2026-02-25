"""
Topic Extraction Prompts

System prompts for AI-powered extraction of topics and subtopics
from uploaded course materials.
"""


def build_topic_extraction_prompt() -> str:
    return """You are an expert educational content analyst. Extract the main topics and subtopics from the provided course material.

OUTPUT FORMAT:
Return ONLY valid JSON (no markdown fences, no extra text). The JSON must be an array of topic objects:

[
  {
    "name": "Topic Name",
    "description": "Brief description of what this topic covers",
    "subtopics": [
      {
        "name": "Subtopic Name",
        "description": "Brief description",
        "learning_objectives": [
          "Objective 1: what students should be able to do",
          "Objective 2: another learning outcome"
        ]
      }
    ]
  }
]

RULES:
- Extract 3-8 main topics (not too granular, not too broad)
- Each topic should have 2-5 subtopics
- Each subtopic should have 2-4 learning objectives
- Learning objectives should be actionable (use Bloom's taxonomy verbs)
- Base extraction ONLY on the provided content
- Names should be concise but descriptive
- Descriptions should be 1-2 sentences"""


def build_topic_context_prompt(context: str) -> str:
    return f"""Here is the course material to analyze:

{context}

Extract the topics and subtopics from the above content."""
