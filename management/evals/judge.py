"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: LLM-as-judge helpers for RAG evaluation runs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from management.evals.question_generation import extract_response_output_text
from management.evals.reference_checks import ReferenceCheck

ANSWER_CORRECTNESS_VALUES = frozenset(
    {"correct", "partially_correct", "incorrect", "not_answered", "judge_error"}
)
GROUNDING_VALUES = frozenset(
    {"grounded", "weakly_grounded", "ungrounded", "unknown", "judge_error"}
)
HALLUCINATION_RISK_VALUES = frozenset(
    {"low", "medium", "high", "unknown", "judge_error"}
)
OVERALL_VALUES = frozenset({"pass", "review", "fail", "error"})


@dataclass(frozen=True)
class JudgeRequest:
    """Inputs for one LLM judge request."""

    question: str
    expected_answer: str
    agent_answer: str
    source_pdf_name: str
    page_number: int
    references: list[dict[str, Any]]
    reference_check: ReferenceCheck


@dataclass(frozen=True)
class JudgeResult:
    """Validated LLM judge result."""

    answer_correctness: str
    grounding: str
    hallucination_risk: str
    overall: str
    confidence: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


def build_judge_instructions() -> str:
    """Build LLM judge instructions.

    Returns:
        str: Judge instructions.
    """

    return (
        "You are a strict but fair evaluator for a RAG system. Compare the "
        "agent answer to the expected answer semantically, not by exact string "
        "matching. Evaluate whether the answer is correct, grounded in returned "
        "references, and free of unsupported claims. Return only valid JSON."
    )


def build_judge_input(request: JudgeRequest) -> str:
    """Build judge input text.

    Args:
        request: Judge request.

    Returns:
        str: Judge input.
    """

    payload = {
        "question": request.question,
        "expected_answer": request.expected_answer,
        "agent_answer": request.agent_answer,
        "expected_source": {
            "source_pdf_name": request.source_pdf_name,
            "page_number": request.page_number,
        },
        "reference_check": request.reference_check.to_dict(),
        "references": request.references,
        "allowed_values": {
            "answer_correctness": sorted(ANSWER_CORRECTNESS_VALUES - {"judge_error"}),
            "grounding": sorted(GROUNDING_VALUES - {"judge_error"}),
            "hallucination_risk": sorted(HALLUCINATION_RISK_VALUES - {"judge_error"}),
            "overall": sorted(OVERALL_VALUES - {"error"}),
        },
    }
    return (
        "Classify this RAG answer. Use `pass` only when the answer is correct, "
        "grounded or weakly grounded, and hallucination risk is low. Use "
        "`review` for partial correctness, weak/unknown grounding, or medium "
        "hallucination risk. Use `fail` for incorrect, not answered, ungrounded, "
        "or high hallucination risk.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def judge_answer(
    client: Any,
    model: str,
    compartment_id: str,
    request: JudgeRequest,
    temperature: float = 0.0,
    timeout_seconds: int = 120,
) -> JudgeResult:
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Judge one agent answer with the evaluation model.

    Args:
        client: OpenAI-compatible client.
        model: Evaluation model identifier.
        compartment_id: Evaluation compartment OCID.
        request: Judge request.
        temperature: Optional positive temperature.
        timeout_seconds: Judge request timeout.

    Returns:
        JudgeResult: Validated judge result.
    """

    create_kwargs: dict[str, Any] = {
        "model": model,
        "instructions": build_judge_instructions(),
        "input": build_judge_input(request),
        "extra_body": {"compartmentId": compartment_id},
        "timeout": timeout_seconds,
    }
    if temperature > 0:
        create_kwargs["temperature"] = temperature

    response = client.responses.create(**create_kwargs)
    return parse_judge_payload(extract_response_output_text(response))


def parse_judge_payload(raw_content: str) -> JudgeResult:
    """Parse and validate judge JSON output.

    Args:
        raw_content: Raw judge model output.

    Returns:
        JudgeResult: Validated judge result.

    Raises:
        ValueError: If the payload is invalid.
    """

    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge output is not valid JSON: {exc}") from exc

    result = JudgeResult(
        answer_correctness=str(payload.get("answer_correctness", "")).strip(),
        grounding=str(payload.get("grounding", "")).strip(),
        hallucination_risk=str(payload.get("hallucination_risk", "")).strip(),
        overall=str(payload.get("overall", "")).strip(),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        rationale=str(payload.get("rationale", "")).strip(),
    )
    validate_judge_result(result)
    return result


def validate_judge_result(result: JudgeResult) -> None:
    """Validate judge labels.

    Args:
        result: Judge result.

    Raises:
        ValueError: If a label is invalid.
    """

    _validate_choice(
        "answer_correctness", result.answer_correctness, ANSWER_CORRECTNESS_VALUES
    )
    _validate_choice("grounding", result.grounding, GROUNDING_VALUES)
    _validate_choice(
        "hallucination_risk",
        result.hallucination_risk,
        HALLUCINATION_RISK_VALUES,
    )
    _validate_choice("overall", result.overall, OVERALL_VALUES)
    if not 0 <= result.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1.")


def error_judge_result() -> JudgeResult:
    """Return a judge error result.

    Returns:
        JudgeResult: Error classification.
    """

    return JudgeResult(
        answer_correctness="judge_error",
        grounding="judge_error",
        hallucination_risk="judge_error",
        overall="error",
        confidence=0.0,
        rationale="Judge failed.",
    )


def _validate_choice(
    field_name: str, value: str, allowed_values: frozenset[str]
) -> None:
    """Validate one choice label.

    Args:
        field_name: Field name.
        value: Label value.
        allowed_values: Allowed labels.

    Raises:
        ValueError: If the label is invalid.
    """

    if value not in allowed_values:
        raise ValueError(f"{field_name} has invalid value: {value}")
