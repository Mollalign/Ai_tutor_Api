"""
Chat Prompts

System prompts and templates for the AI tutor.

Socratic Mode:
-------------
When enabled, the AI guides learning through questions
rather than direct answers. This promotes:
- Critical thinking
- Deeper understanding
- Active learning
"""


def build_system_prompt(
    is_socratic: bool = True,
    has_context: bool = False,
    learning_style_hint: str = "",
    conversation_memory: str = "",
    cross_topic_hint: str = "",
) -> str:
    """
    Build the system prompt for the AI tutor.
    
    Args:
        is_socratic: Whether to use Socratic teaching mode
        has_context: Whether RAG context is provided
        learning_style_hint: Prompt adaptation for detected learning style
        conversation_memory: Summary of recent conversations for continuity
        cross_topic_hint: Cross-topic connections to reference
    
    Returns:
        System prompt string
    """
    base_prompt = """You are an AI Study Tutor helping university and college students learn deeply.

Your role is to:
- Help students understand concepts, not just provide answers
- Explain complex topics in clear, accessible language
- Encourage critical thinking and curiosity
- Provide accurate information from the provided materials when available"""
    
    if is_socratic:
        socratic_addition = """

SOCRATIC MODE ENABLED:
Instead of giving direct answers, guide the student's thinking:
- Ask clarifying questions to understand their current knowledge
- Break complex problems into smaller steps
- Use questions to lead them toward insights
- Celebrate when they discover answers themselves
- Only provide direct answers when the student is truly stuck

Example:
Student: "What is photosynthesis?"
You: "Great question! Let's explore this together. What do you already know about how plants get their energy? And have you noticed what plants need to survive?"
"""
        base_prompt += socratic_addition
    else:
        direct_addition = """

DIRECT MODE:
Provide clear, comprehensive explanations:
- Give direct answers to questions
- Explain concepts thoroughly
- Use examples to illustrate points
- Summarize key takeaways
"""
        base_prompt += direct_addition
    
    if has_context:
        context_addition = """

IMPORTANT: You have been provided with relevant content from the student's course materials.
- Base your answers primarily on this provided context
- Cite specific sources when relevant (e.g., "According to your lecture notes...")
- If the context doesn't contain the answer, say so and provide general knowledge
- Don't make up information that isn't in the context"""
        base_prompt += context_addition
    else:
        no_context_addition = """

Note: No specific course materials are available for this question.
Provide helpful information from your general knowledge while being clear about limitations."""
        base_prompt += no_context_addition

    if learning_style_hint:
        base_prompt += f"\n\nADAPT YOUR TEACHING STYLE:\n{learning_style_hint}"

    if conversation_memory:
        base_prompt += f"\n\nCONVERSATION MEMORY:\n{conversation_memory}"

    if cross_topic_hint:
        base_prompt += (
            f"\n\nCROSS-TOPIC CONNECTIONS:\n{cross_topic_hint}\n"
            "When relevant, mention how this topic connects to concepts "
            "the student has studied in other courses."
        )

    return base_prompt


def build_context_prompt(context: str) -> str:
    """
    Build the context prompt with retrieved documents.
    
    Args:
        context: Formatted context from RAG retrieval
    
    Returns:
        Context prompt string
    """
    return f"""Here is relevant information from the student's course materials:

{context}

Use this information to answer the student's question. Cite the sources when appropriate."""