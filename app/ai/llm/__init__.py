"""
LLM Module

Language Model integrations for the AI tutor.

Currently using Google Gemini.
"""

from app.ai.llm.gemini_client import (
    chat_completion,
    chat_completion_stream,
    simple_generate,
    check_gemini_health,
)

__all__ = [
    "chat_completion",
    "chat_completion_stream", 
    "simple_generate",
    "check_gemini_health",
    "initialize_gemini",
    "get_model",
]