"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: HTTP client helpers for invoking the RAG agent during evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx


@dataclass(frozen=True)
class AgentEvaluationResponse:
    """Normalized response from one agent evaluation request.

    Attributes:
        conversation_id: Agent conversation identifier, when returned.
        response_id: Responses API response identifier, when returned.
        answer: Agent answer text.
        references: Agent references.
        usage: Token usage payload, when returned.
        error: Error message, when the request failed.
        latency_ms: Request latency in milliseconds.
    """

    conversation_id: str = ""
    response_id: str = ""
    answer: str = ""
    references: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = 0


def build_agent_request(question: str) -> dict[str, Any]:
    """Build a non-streaming agent request payload.

    Args:
        question: User question from the golden dataset.

    Returns:
        dict[str, Any]: Agent request payload.
    """

    return {
        "new_conversation": True,
        "user_request": question,
        "stream": False,
    }


def invoke_agent(
    endpoint: str,
    question: str,
    timeout_seconds: int = 120,
    http_client: httpx.Client | None = None,
) -> AgentEvaluationResponse:
    """Invoke the RAG agent for one golden question.

    Args:
        endpoint: Full agent `/responses` endpoint URL.
        question: Golden question.
        timeout_seconds: Request timeout in seconds.
        http_client: Optional HTTPX client for tests.

    Returns:
        AgentEvaluationResponse: Normalized agent response or error.
    """

    close_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout_seconds)
    start_time = perf_counter()
    try:
        response = client.post(
            endpoint,
            json=build_agent_request(question),
            headers={"Accept": "application/json"},
        )
        latency_ms = int((perf_counter() - start_time) * 1000)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return AgentEvaluationResponse(
            error=str(exc),
            latency_ms=int((perf_counter() - start_time) * 1000),
        )
    finally:
        if close_client:
            client.close()

    payload_error = payload.get("error")
    if payload_error:
        return AgentEvaluationResponse(
            conversation_id=str(payload.get("conversation_id") or ""),
            response_id=str(payload.get("response_id") or ""),
            answer=str(payload.get("agent_response") or ""),
            references=_normalize_references(payload.get("references")),
            usage=_normalize_usage(payload.get("usage")),
            error=str(payload_error),
            latency_ms=latency_ms,
        )

    return AgentEvaluationResponse(
        conversation_id=str(payload.get("conversation_id") or ""),
        response_id=str(payload.get("response_id") or ""),
        answer=str(payload.get("agent_response") or ""),
        references=_normalize_references(payload.get("references")),
        usage=_normalize_usage(payload.get("usage")),
        latency_ms=latency_ms,
    )


def _normalize_references(value: Any) -> list[dict[str, Any]]:
    """Normalize a references payload.

    Args:
        value: Raw references value.

    Returns:
        list[dict[str, Any]]: Reference dictionaries.
    """

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_usage(value: Any) -> dict[str, Any] | None:
    """Normalize a usage payload.

    Args:
        value: Raw usage value.

    Returns:
        dict[str, Any] | None: Usage dictionary when present.
    """

    if isinstance(value, dict):
        return value
    return None
