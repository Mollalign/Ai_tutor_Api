"""
Google Gemini LLM Client (New SDK)

Integration with Google's Gemini API using the new google-genai package.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# CLIENT INITIALIZATION
# ============================================================

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Get or create the Gemini client."""
    global _client
    
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY not set. "
                "Get your free key at https://aistudio.google.com/apikey"
            )
        
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info(f"Gemini client initialized (model: {settings.GEMINI_MODEL})")
    
    return _client


# ============================================================
# MESSAGE FORMATTING
# ============================================================

def format_messages_for_gemini(
    messages: List[Dict[str, str]]
) -> List[types.Content]:
    """
    Format messages for Gemini API.
    
    Args:
        messages: List of {"role": "user/assistant", "content": "..."}
    
    Returns:
        List of Content objects for Gemini
    """
    contents = []
    
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        
        # Convert roles: assistant -> model, system -> user context
        if role == "assistant":
            role = "model"
        elif role == "system":
            # System messages become user messages in Gemini
            role = "user"
            content = f"[Context]\n{content}"
        
        # Use Part constructor directly instead of from_text()
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part(text=content)]  # <-- CHANGED LINE
            )
        )
    
    return contents

# ============================================================
# CHAT COMPLETION
# ============================================================

async def chat_completion(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get a chat completion (non-streaming).
    
    Args:
        messages: Conversation history
        system_prompt: System instructions
        temperature: Creativity (0-2)
        max_tokens: Maximum response length
    
    Returns:
        Dict with content, tokens, etc.
    """
    client = get_client()
    
    contents = format_messages_for_gemini(messages)
    
    # Build generation config
    config = types.GenerateContentConfig(
        temperature=temperature or settings.LLM_TEMPERATURE,
        max_output_tokens=max_tokens or settings.LLM_MAX_TOKENS,
        system_instruction=system_prompt,
    )
    
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=config
        )
        
        # Extract token counts if available
        tokens_used = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens_used = getattr(response.usage_metadata, 'total_token_count', 0) or 0
        
        return {
            "content": response.text,
            "tokens_used": tokens_used,
            "model": settings.GEMINI_MODEL,
            "finish_reason": "stop"
        }
        
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise


async def chat_completion_stream(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> AsyncGenerator[str, None]:
    """
    Get a streaming chat completion.
    
    Yields text chunks as they're generated.
    """
    client = get_client()
    
    contents = format_messages_for_gemini(messages)
    
    # Build generation config
    config = types.GenerateContentConfig(
        temperature=temperature or settings.LLM_TEMPERATURE,
        max_output_tokens=max_tokens or settings.LLM_MAX_TOKENS,
        system_instruction=system_prompt,
    )
    
    try:
        # Use streaming
        for chunk in client.models.generate_content_stream(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=config
        ):
            if chunk.text:
                yield chunk.text
                
    except Exception as e:
        logger.error(f"Gemini streaming error: {e}")
        raise


# ============================================================
# SIMPLE GENERATION
# ============================================================

async def simple_generate(prompt: str, max_tokens: int = 100) -> str:
    """Simple text generation without chat context."""
    client = get_client()
    
    config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
    )
    
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=config
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini generation error: {e}")
        raise


# ============================================================
# HEALTH CHECK
# ============================================================

async def check_gemini_health() -> bool:
    """Check if Gemini API is accessible."""
    try:
        client = get_client()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents="Hello"
        )
        return bool(response.text)
    except Exception as e:
        logger.error(f"Gemini health check failed: {e}")
        return False