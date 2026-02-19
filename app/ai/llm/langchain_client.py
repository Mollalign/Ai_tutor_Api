"""
LangChain-based LLM Client

This module provides a LangChain wrapper around Google's Gemini model.
It replaces direct SDK calls with LangChain abstractions for better
composability, streaming, and integration with RAG.

Key Concepts:
- ChatGoogleGenerativeAI: LangChain's wrapper for Gemini
- Messages: Structured format for conversation history
- LCEL: LangChain Expression Language for chaining operations
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator, Union

# LangChain imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# 1: MODEL INITIALIZATION
# ============================================================
"""
ChatGoogleGenerativeAI is LangChain's wrapper for Gemini.
"""

_llm: Optional[ChatGoogleGenerativeAI] = None


def get_llm(
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    streaming: bool = False
) -> ChatGoogleGenerativeAI:
    """
    Get or create the LangChain LLM instance.
    
    Args:
        temperature: Override default temperature
        max_tokens: Override default max tokens
        streaming: Enable streaming mode
    
    Returns:
        Configured ChatGoogleGenerativeAI instance
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY not set. "
            "Get your free key at https://aistudio.google.com/apikey"
        )
    
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature or settings.LLM_TEMPERATURE,
        max_output_tokens=max_tokens or settings.LLM_MAX_TOKENS,
        convert_system_message_to_human=True,  # Gemini-specific
        streaming=streaming,
    )


# ============================================================
# 2: MESSAGE CONVERSION
# ============================================================
"""
LangChain uses typed message objects instead of dictionaries.

Message Types:
- SystemMessage: Instructions for the AI (persona, rules)
- HumanMessage: User's input
- AIMessage: Assistant's response

Why typed messages?
1. Type safety and validation
2. Additional metadata support (name, example flag)
3. Multimodal content (images, files) via content lists
"""

def convert_to_langchain_messages(
    messages: List[Dict[str, str]]
) -> List[BaseMessage]:
    """
    Convert dict messages to LangChain message objects.
    
    Args:
        messages: List of {"role": "user/assistant/system", "content": "..."}
    
    Returns:
        List of LangChain message objects
    """
    langchain_messages = []

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        
        if role == "system":
            langchain_messages.append(SystemMessage(content=content))
        elif role == "user":
            langchain_messages.append(HumanMessage(content=content))
        elif role in ("assistant", "model"):
            langchain_messages.append(AIMessage(content=content))
        else:
            # Unknown role - treat as human message
            logger.warning(f"Unknown message role: {role}")
            langchain_messages.append(HumanMessage(content=content))
    
    return langchain_messages


def convert_from_langchain_message(message: BaseMessage) -> Dict[str, str]:
    """
    Convert LangChain message back to dict format.
    
    Useful for storing in database or API responses.
    """
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    else:
        role = "unknown"
    
    return {
        "role": role,
        "content": message.content if isinstance(message.content, str) else str(message.content)
    }   

# ============================================================
# 3: PROMPT TEMPLATES
# ============================================================
"""
ChatPromptTemplate creates reusable prompt structures.

Why use templates?
1. Separation of prompt logic from code
2. Variable interpolation with validation
3. Composability - combine multiple templates
4. MessagesPlaceholder for dynamic history insertion

LCEL (LangChain Expression Language):
Templates are "Runnables" - they can be chained with | operator:
    prompt | llm | parser
"""

def create_chat_prompt(
    system_prompt: str,
    include_context: bool = False
) -> ChatPromptTemplate:
    """
    Create a chat prompt template.
    
    Args:
        system_prompt: The system instructions
        include_context: Whether to include RAG context placeholder
    
    Returns:
        ChatPromptTemplate ready for use in chains
    """
    messages = [
        ("system", system_prompt),
    ]

    if include_context:
        # context will be injected here
        messages.append(
            ("system", "Relevant context from documents:\n{context}")
        )

    # MessagesPlaceholder allows variable-length history
    messages.append(MessagesPlaceholder(variable_name="chat_history"))    

    # Current user message
    messages.append(("human", "{input}"))

    return ChatPromptTemplate.from_messages(messages)


# ============================================================
# CONCEPT 4: CHAINS (LCEL)
# ============================================================
"""
LCEL (LangChain Expression Language) uses the | operator to chain operations.

Basic chain:
    prompt | llm | output_parser

How it works:
1. prompt.invoke({"input": "Hello"}) → formatted messages
2. llm.invoke(messages) → AI response
3. output_parser.invoke(response) → extracted string

RunnablePassthrough: Passes input through unchanged
RunnableLambda: Wraps a function as a Runnable
"""

def create_basic_chain(
    system_prompt: str,
    temperature: Optional[float] = None
):
    """
    Create a basic chat chain without RAG.

    This is the simplest chain:
    prompt → LLM → string output

    Returns:
        A Runnable chain that accepts {"input": str, "chat_history": list}
    """
    prompt = create_chat_prompt(system_prompt, include_context=False)
    llm = get_llm(temperature=temperature)

    # StrOutputParser extracts text from AIMessage
    chain = prompt | llm | StrOutputParser()

    return chain


# ============================================================
# 5: ASYNC CHAT COMPLETION
# ============================================================
"""
LangChain provides async methods for all operations:
- .invoke() → .ainvoke()
- .stream() → .astream()
- .batch() → .abatch()
"""

async def chat_completion(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get a chat completion (non-streaming).
    
    This is the direct replacement for the old gemini_client.chat_completion.
    
    Args:
        messages: Conversation history as dicts
        system_prompt: System instructions
        temperature: Creativity level
        max_tokens: Max response length
    
    Returns:
        Dict with content, tokens_used, model, finish_reason
    """
    llm = get_llm(temperature=temperature, max_tokens=max_tokens)

    # built message list
    langchain_messages = []

    if system_prompt:
        langchain_messages.append(SystemMessage(content=system_prompt))

    langchain_messages.extend(convert_to_langchain_messages(messages))   

    try:
        # ainvoke = async invoke
        response = await llm.ainvoke(langchain_messages) 

        # Extract token usage if available
        tokens_used = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens_used = response.usage_metadata.get('total_tokens', 0)
        elif hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('usage_metadata', {})
            tokens_used = (
                usage.get('prompt_token_count', 0) + 
                usage.get('candidates_token_count', 0)
            )

        return {
            "content": response.content,
            "tokens_used": tokens_used,
            "model": settings.GEMINI_MODEL,
            "finish_reason": "stop"
        }

    except Exception as e:
        logger.error(f"LangChain chat completion error: {e}")
        raise  

# ============================================================
# 6: STREAMING
# ============================================================
"""
Streaming returns chunks as they're generated.

LangChain streaming:
- astream() returns an async generator
- Each chunk is an AIMessageChunk with partial content
- Chunks can be accumulated to build full response

Why streaming?
1. Better UX - user sees response as it generates
2. Lower perceived latency
3. Can cancel early if needed
"""

async def chat_completion_stream(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> AsyncGenerator[str, None]:
    """
    Get a streaming chat completion.
    
    Yields text chunks as they're generated.
    
    Usage:
        async for chunk in chat_completion_stream(messages):
            print(chunk, end="", flush=True)
    """
    llm = get_llm(
        temperature=temperature, 
        max_tokens=max_tokens,
        streaming=True
    )

    # Build message list
    langchain_messages = []

    if system_prompt:
        langchain_messages.append(SystemMessage(content=system_prompt))
    
    langchain_messages.extend(convert_to_langchain_messages(messages))

    try:
        # astream = async stream
        async for chunk in llm.astream(langchain_messages):
            # # chunk is AIMessageChunk
            if chunk.content:
                yield chunk.content

    except Exception as e:
        logger.error(f"LangChain streaming error: {e}")
        raise           
    
# ============================================================
# 7: MULTIMODAL (Images)
# ============================================================
"""
Gemini supports multimodal input (text + images).

In LangChain, multimodal content uses a list format:
    HumanMessage(content=[
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ])

For local files, we base64 encode the image.
"""
import base64
from pathlib import Path

def create_image_message(
    text: str,
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_url: Optional[str] = None,
    mime_type: str = "image/jpeg"
) -> HumanMessage:
    """
    Create a multimodal message with text and image.
    
    Provide ONE of: image_path, image_base64, or image_url
    
    Args:
        text: The text prompt
        image_path: Path to local image file
        image_base64: Base64-encoded image data
        image_url: URL to remote image
        mime_type: MIME type of image
    
    Returns:
        HumanMessage with multimodal content
    """
    content = [{"type": "text", "text": text}]

    if image_path:
        # Read and encode local file
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Detect MIME type from extension
        ext = path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(ext, mime_type)    

        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_data}"
            }
        })

    elif image_base64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_base64}"
            }
        }) 

    elif image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url}
        })    

    return HumanMessage(content=content)       

async def analyze_image(
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_url: Optional[str] = None,
    prompt: str = "Describe this image in detail.",
    system_prompt: Optional[str] = None    
) -> str:
    """
    Analyze an image using Gemini's vision capabilities.
    
    Args:
        image_path: Path to local image
        image_base64: Base64 encoded image
        image_url: URL to image
        prompt: Question or instruction about the image
        system_prompt: Optional system instructions
    
    Returns:
        AI's description/analysis of the image
    """
    llm = get_llm()

    messages = []

    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))

    messages.append(create_image_message(
        text=prompt,
        image_path=image_path,
        image_base64=image_base64,
        image_url=image_url
    ))
    
    response = await llm.ainvoke(messages)
    return response.content    


# ============================================================
# CONCEPT 8: HEALTH CHECK
# ============================================================

async def check_health() -> bool:
    """Check if LangChain + Gemini is working."""
    try:
        llm = get_llm()
        response = await llm.ainvoke([HumanMessage(content="Hi")])
        return bool(response.content)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False