"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: HTTP client helpers for invoking the RAG agent during evaluations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
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


def build_agent_request(question: str, stream: bool = True) -> dict[str, Any]:
    """Build an agent request payload.

    Args:
        question: User question from the golden dataset.
        stream: Whether to request Server-Sent Event streaming.

    Returns:
        dict[str, Any]: Agent request payload.
    """

    return {
        "new_conversation": True,
        "user_request": question,
        "stream": stream,
    }


def invoke_agent(
    endpoint: str,
    question: str,
    timeout_seconds: int = 120,
    http_client: httpx.Client | None = None,
    stream: bool = True,
) -> AgentEvaluationResponse:
    """Invoke the RAG agent for one golden question.

    Args:
        endpoint: Full agent `/responses` endpoint URL.
        question: Golden question.
        timeout_seconds: Request timeout in seconds.
        http_client: Optional HTTPX client for tests.
        stream: Whether to use the streaming contract used by the UI.

    Returns:
        AgentEvaluationResponse: Normalized agent response or error.
    """

    close_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout_seconds)
    start_time = perf_counter()
    try:
        if stream:
            result = _invoke_streaming_agent(client, endpoint, question)
            return _with_latency(result, start_time)

        payload = _invoke_json_agent(client, endpoint, question)
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
            latency_ms=int((perf_counter() - start_time) * 1000),
        )

    return AgentEvaluationResponse(
        conversation_id=str(payload.get("conversation_id") or ""),
        response_id=str(payload.get("response_id") or ""),
        answer=str(payload.get("agent_response") or ""),
        references=_normalize_references(payload.get("references")),
        usage=_normalize_usage(payload.get("usage")),
        latency_ms=int((perf_counter() - start_time) * 1000),
    )


def _invoke_json_agent(
    client: httpx.Client,
    endpoint: str,
    question: str,
) -> dict[str, Any]:
    """Invoke the non-streaming JSON agent contract."""

    response = client.post(
        endpoint,
        json=build_agent_request(question, stream=False),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def _invoke_streaming_agent(
    client: httpx.Client,
    endpoint: str,
    question: str,
) -> AgentEvaluationResponse:
    """Invoke the streaming SSE agent contract used by the reference UI."""

    with client.stream(
        "POST",
        endpoint,
        json=build_agent_request(question, stream=True),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
    ) as response:
        response.raise_for_status()
        return _parse_agent_stream(response.iter_lines())


def _parse_agent_stream(lines: Any) -> AgentEvaluationResponse:
    """Parse agent Server-Sent Events into a normalized response."""

    event_name = "message"
    data_lines: list[str] = []
    metadata_seen = False
    state: dict[str, Any] = {
        "conversation_id": "",
        "response_id": "",
        "answer": "",
        "references": [],
        "usage": None,
        "error": None,
    }

    for line in lines:
        clean_line = line.rstrip("\n")
        if not clean_line:
            metadata_seen = _consume_sse_frame(
                event_name,
                data_lines,
                metadata_seen,
                state,
            )
            event_name = "message"
            data_lines = []
            if state["error"]:
                break
            continue

        if clean_line.startswith("event:"):
            event_name = clean_line.split(":", 1)[1].strip()
        elif clean_line.startswith("data:"):
            data_lines.append(clean_line.split(":", 1)[1].strip())

    if data_lines and not state["error"]:
        _consume_sse_frame(event_name, data_lines, metadata_seen, state)

    return AgentEvaluationResponse(
        conversation_id=str(state["conversation_id"] or ""),
        response_id=str(state["response_id"] or ""),
        answer=str(state["answer"] or ""),
        references=_normalize_references(state["references"]),
        usage=_normalize_usage(state["usage"]),
        error=str(state["error"]) if state["error"] else None,
    )


def _consume_sse_frame(
    event_name: str,
    data_lines: list[str],
    metadata_seen: bool,
    state: dict[str, Any],
) -> bool:
    """Consume one SSE frame and update parsed stream state."""

    if not data_lines:
        return metadata_seen

    payload = _loads_sse_payload(data_lines)
    normalized_event = _normalize_sse_event_name(event_name, payload, metadata_seen)

    if normalized_event == "metadata":
        state["conversation_id"] = payload.get("conversation_id") or ""
        return True
    if normalized_event == "token":
        state["answer"] = f"{state['answer']}{payload.get('text') or ''}"
    elif normalized_event == "references":
        state["references"] = payload.get("references") or []
    elif normalized_event == "usage":
        state["usage"] = payload.get("usage")
    elif normalized_event == "error":
        state["error"] = payload.get("error") or "Agent stream error."
    elif normalized_event == "done":
        state["conversation_id"] = (
            payload.get("conversation_id") or state["conversation_id"]
        )
        state["response_id"] = payload.get("response_id") or ""

    return metadata_seen


def _loads_sse_payload(data_lines: list[str]) -> dict[str, Any]:
    """Load an SSE JSON payload."""

    try:
        payload = json.loads("\n".join(data_lines))
    except JSONDecodeError as exc:
        raise ValueError(f"Invalid SSE JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid SSE payload: expected a JSON object.")

    return payload


def _normalize_sse_event_name(
    event_name: str,
    payload: dict[str, Any],
    metadata_seen: bool,
) -> str:
    """Infer event names when an intermediate gateway strips SSE event lines."""

    if event_name != "message":
        return event_name

    payload_key_events = {
        "text": "token",
        "references": "references",
        "usage": "usage",
        "error": "error",
    }
    for payload_key, inferred_event_name in payload_key_events.items():
        if payload_key in payload:
            return inferred_event_name

    if "conversation_id" in payload:
        return "done" if metadata_seen else "metadata"

    return event_name


def _with_latency(
    response: AgentEvaluationResponse,
    start_time: float,
) -> AgentEvaluationResponse:
    """Return a response copy with latency populated."""

    return AgentEvaluationResponse(
        conversation_id=response.conversation_id,
        response_id=response.response_id,
        answer=response.answer,
        references=response.references,
        usage=response.usage,
        error=response.error,
        latency_ms=int((perf_counter() - start_time) * 1000),
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
