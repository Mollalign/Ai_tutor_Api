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
    import asyncio
    import queue
    import threading
    
    client = get_client()
    
    contents = format_messages_for_gemini(messages)
    
    # Build generation config
    config = types.GenerateContentConfig(
        temperature=temperature or settings.LLM_TEMPERATURE,
        max_output_tokens=max_tokens or settings.LLM_MAX_TOKENS,
        system_instruction=system_prompt,
    )
    
    # Use a queue to communicate between threads
    chunk_queue: queue.Queue = queue.Queue()
    error_holder = [None]  # Use list to allow mutation in closure
    
    def stream_in_thread():
        """Run the sync streaming in a separate thread."""
        try:
            for chunk in client.models.generate_content_stream(
                model=settings.GEMINI_MODEL,
                contents=contents,
                config=config
            ):
                if chunk.text:
                    chunk_queue.put(chunk.text)
            # Signal completion
            chunk_queue.put(None)
        except Exception as e:
            error_holder[0] = e
            chunk_queue.put(None)
    
    # Start streaming in background thread
    thread = threading.Thread(target=stream_in_thread)
    thread.start()
    
    try:
        loop = asyncio.get_event_loop()
        
        while True:
            # Get chunk from queue (with timeout to allow event loop to run)
            chunk = await loop.run_in_executor(
                None, 
                lambda: chunk_queue.get(timeout=60)
            )
            
            if chunk is None:
                # Stream completed or errored
                if error_holder[0]:
                    raise error_holder[0]
                break
            
            logger.debug(f"Streaming chunk: {len(chunk)} chars")
            yield chunk
            
    except queue.Empty:
        logger.error("Streaming timeout - no response from Gemini")
        raise TimeoutError("Streaming timeout")
    finally:
        thread.join(timeout=5)


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