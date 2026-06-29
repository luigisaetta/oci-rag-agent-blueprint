"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: LLM prompt and validation helpers for golden Q&A generation.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

FORBIDDEN_QUESTION_PATTERNS = (
    r"\bpage\b",
    r"\bdocument\b",
    r"\bsection\b",
    r"\bpdf\b",
    r"\bfile\b",
    r"\bon this page\b",
    r"\bin this document\b",
    r"\bin this section\b",
)


class ResponsesClientProtocol(Protocol):
    """Protocol for the OpenAI-compatible Responses API client."""

    class responses:  # pylint: disable=too-few-public-methods,invalid-name
        """OpenAI-compatible Responses API namespace."""

        @staticmethod
        def create(**kwargs: Any) -> Any:
            """Create a response."""


@dataclass(frozen=True)
class GeneratedQuestionAnswer:
    """Generated question and expected answer.

    Attributes:
        question: Grounded generated question.
        expected_answer: Grounded generated expected answer.
    """

    question: str
    expected_answer: str


@dataclass(frozen=True)
class QuestionGenerationRequest:
    """Inputs required to generate one golden question-answer pair.

    Attributes:
        model: Evaluation model identifier.
        page_text: Source page text.
        compartment_id: OCI compartment OCID required by OCI Enterprise AI.
        temperature: Generation temperature.
    """

    model: str
    page_text: str
    compartment_id: str
    temperature: float = 0.0


def build_generation_instructions() -> str:
    """Build Responses API instructions for Q&A generation.

    Returns:
        str: Instructions for structured golden example generation.
    """

    return (
        "You generate evaluation examples for a RAG system. Return only valid "
        "JSON with keys question and expected_answer. Use only the provided "
        "page text. Do not mention page numbers, PDF names, documents, files, "
        "or sections."
    )


def build_generation_input(page_text: str) -> str:
    """Build Responses API input for Q&A generation.

    Args:
        page_text: Extracted page text.

    Returns:
        str: User input for the Responses API request.
    """

    return (
        "Create one conceptual question and one concise expected answer that "
        "can be answered using only this source text.\n\n"
        f"Source text:\n{page_text}"
    )


def parse_generated_payload(raw_content: str) -> GeneratedQuestionAnswer:
    """Parse and validate an LLM-generated JSON payload.

    Args:
        raw_content: Raw model output.

    Returns:
        GeneratedQuestionAnswer: Validated generated example.

    Raises:
        ValueError: If the output is not valid or violates question rules.
    """

    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model output is not valid JSON: {exc}") from exc

    question = str(payload.get("question", "")).strip()
    expected_answer = str(payload.get("expected_answer", "")).strip()
    if not question:
        raise ValueError("Generated question is empty.")
    if not expected_answer:
        raise ValueError("Generated expected answer is empty.")
    validate_question(question)
    return GeneratedQuestionAnswer(question=question, expected_answer=expected_answer)


def validate_question(question: str) -> None:
    """Validate that a generated question avoids source-location references.

    Args:
        question: Question to validate.

    Raises:
        ValueError: If the question violates forbidden-reference rules.
    """

    lower_question = question.lower()
    for pattern in FORBIDDEN_QUESTION_PATTERNS:
        if re.search(pattern, lower_question):
            raise ValueError(f"Question contains forbidden reference: {pattern}")


def generate_question_answer(
    client: Any,
    request: QuestionGenerationRequest,
    max_retries: int = 2,
) -> GeneratedQuestionAnswer:
    """Generate and validate one grounded question-answer pair.

    Args:
        client: OpenAI-compatible client.
        request: Question generation request.
        max_retries: Number of retries after invalid model output.

    Returns:
        GeneratedQuestionAnswer: Generated question and answer.

    Raises:
        ValueError: If all attempts return invalid output.
    """

    last_error: ValueError | None = None
    for _ in range(max_retries + 1):
        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "instructions": build_generation_instructions(),
            "input": build_generation_input(request.page_text),
            "extra_body": {"compartmentId": request.compartment_id},
        }
        if request.temperature > 0:
            create_kwargs["temperature"] = request.temperature
        response = client.responses.create(**create_kwargs)
        raw_content = extract_response_output_text(response)
        try:
            return parse_generated_payload(raw_content)
        except ValueError as exc:
            last_error = exc

    raise ValueError(f"Unable to generate valid question-answer pair: {last_error}")


def extract_response_output_text(response: Any) -> str:
    """Extract text from an OpenAI-compatible Responses API response.

    Args:
        response: Responses API response object.

    Returns:
        str: Extracted response text.
    """

    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    text_parts: list[str] = []
    for output_item in getattr(response, "output", []) or []:
        for content_item in getattr(output_item, "content", []) or []:
            text_value = getattr(content_item, "text", None)
            if text_value:
                text_parts.append(str(text_value))
    return "".join(text_parts)
