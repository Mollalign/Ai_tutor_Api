"""
Quiz Generation Prompts

System prompts and templates for AI-powered quiz generation.
The LLM generates questions based on uploaded course materials.
"""

import json


def build_quiz_generation_prompt(
    num_questions: int = 5,
    difficulty: str = "medium",
    question_types: list[str] = None,
    topic_focus: str | None = None,
) -> str:
    if question_types is None:
        question_types = ["multiple_choice", "true_false"]

    type_instructions = []
    if "multiple_choice" in question_types:
        type_instructions.append(
            '- multiple_choice: Provide exactly 4 options as {"A": "...", "B": "...", "C": "...", "D": "..."}. '
            'correct_answer is the key letter (e.g. "B").'
        )
    if "true_false" in question_types:
        type_instructions.append(
            '- true_false: options should be {"A": "True", "B": "False"}. '
            'correct_answer is "A" or "B".'
        )
    if "code_output" in question_types:
        type_instructions.append(
            '- code_output: Include a code_snippet field with the code. '
            'Provide 4 options for possible outputs. correct_answer is the key letter.'
        )

    types_block = "\n".join(type_instructions)
    topic_line = f'\nFocus specifically on: {topic_focus}' if topic_focus else ''

    return f"""You are an expert educational assessment creator. Generate a quiz based on the provided course materials.

REQUIREMENTS:
- Generate exactly {num_questions} questions
- Difficulty level: {difficulty}
- Question types to use: {', '.join(question_types)}{topic_line}

QUESTION TYPE FORMATS:
{types_block}

DIFFICULTY GUIDELINES:
- easy: Test recall and basic understanding. Straightforward questions.
- medium: Test comprehension and application. Require some reasoning.
- hard: Test analysis and synthesis. Require deep understanding and critical thinking.

OUTPUT FORMAT:
Return ONLY valid JSON (no markdown fences, no extra text). The JSON must be an object with this structure:

{{
  "title": "A descriptive quiz title",
  "description": "Brief description of what the quiz covers",
  "questions": [
    {{
      "question_type": "multiple_choice",
      "question_text": "Clear, well-formed question?",
      "code_snippet": null,
      "options": {{"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"}},
      "correct_answer": "B",
      "explanation": "Clear explanation of why this answer is correct and others are wrong.",
      "points": 10
    }}
  ]
}}

RULES:
- Each question must have a clear, unambiguous correct answer
- Explanations must be educational and thorough
- Distractors (wrong options) should be plausible but clearly incorrect
- Questions should test understanding, not trick the student
- Base questions ONLY on the provided context
- Points: easy=5, medium=10, hard=15"""


def build_quiz_context_prompt(context: str) -> str:
    return f"""Here is the course material to generate questions from:

{context}

Generate questions based ONLY on the information provided above. Do not use outside knowledge."""
