"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Core request processing logic for the OCI RAG agent.
"""

from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from typing import Any, Callable, Iterator

from agent.config import AgentSettings

LOGGER = logging.getLogger(__name__)
RESPONSES_TIMEOUT_SECONDS = 60
AGENT_INSTRUCTIONS = """
You are an OCI Enterprise AI RAG agent.
Answer the user directly and concisely using the available knowledge base.
Do not expose internal reasoning, planning, tool-selection narration, or analysis.
Do not mention web search or external tools.
If the knowledge base does not contain enough information, say so plainly.
""".strip()


def process_agent_request(
    payload: dict[str, Any],
    settings: AgentSettings,
    client_factory: Callable[[AgentSettings], Any],
) -> dict[str, Any]:
    """Process one validated agent request.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model, vector store, and API access.
        client_factory: Callable that creates an OpenAI-compatible client.

    Returns:
        dict[str, Any]: Agent response payload.

    Raises:
        Exception: Propagates Responses API errors to the FastAPI layer, which
            converts them into deterministic JSON error responses.
    """

    client = client_factory(settings)
    conversation_id = _resolve_conversation_id(payload, client)

    LOGGER.info("Processing request for conversation_id=%s", conversation_id)
    response = client.responses.create(
        **_build_response_request(payload, settings, conversation_id),
        timeout=RESPONSES_TIMEOUT_SECONDS,
    )

    response_id = getattr(response, "id", None)
    if response_id:
        LOGGER.info("Responses API returned response_id=%s", response_id)

    return {
        "conversation_id": conversation_id,
        "response_id": response_id,
        "agent_response": _extract_response_text(response),
        "references": [],
        "error": None,
    }


def stream_agent_request(
    payload: dict[str, Any],
    settings: AgentSettings,
    client_factory: Callable[[AgentSettings], Any],
) -> Iterator[str]:
    """Stream one validated agent request using Server-Sent Events.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model, vector store, and API access.
        client_factory: Callable that creates an OpenAI-compatible client.

    Yields:
        str: Server-Sent Event frames.
    """

    conversation_id = ""
    token_events_emitted = 0

    try:
        client = client_factory(settings)
        conversation_id = _resolve_conversation_id(payload, client)
        LOGGER.info("Streaming request for conversation_id=%s", conversation_id)
        yield _format_sse_event("metadata", {"conversation_id": conversation_id})

        stream = client.responses.create(
            **_build_response_request(payload, settings, conversation_id),
            timeout=RESPONSES_TIMEOUT_SECONDS,
            stream=True,
        )

        for event in stream:
            token = _extract_stream_token(event)
            if token:
                token_events_emitted += 1
                yield _format_sse_event("token", {"text": token})

        yield _format_sse_event("done", {"conversation_id": conversation_id})
    except JSONDecodeError as exc:
        if token_events_emitted:
            LOGGER.warning(
                "Responses API stream parser failure after %s token events: %s",
                token_events_emitted,
                exc,
            )
            yield _format_sse_event("done", {"conversation_id": conversation_id})
        else:
            LOGGER.exception("Responses API streaming parser failure")
            yield _format_sse_event("error", {"error": f"Responses API failure: {exc}"})
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception("Responses API streaming failure")
        yield _format_sse_event("error", {"error": f"Responses API failure: {exc}"})


def _resolve_conversation_id(payload: dict[str, Any], client: Any) -> str:
    """Resolve the conversation identifier for the current request.

    Args:
        payload: Validated request payload.
        client: OpenAI-compatible client.

    Returns:
        str: Conversation identifier to pass to Responses API calls.
    """

    if payload["new_conversation"]:
        conversation = client.conversations.create()
        conversation_id = conversation.id
        LOGGER.info("Created conversation_id=%s", conversation_id)
        return conversation_id

    return payload["conversation_id"]


def _build_response_request(
    payload: dict[str, Any],
    settings: AgentSettings,
    conversation_id: str,
) -> dict[str, Any]:
    """Build common Responses API request parameters.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model and vector store access.
        conversation_id: Active conversation identifier.

    Returns:
        dict[str, Any]: Responses API request parameters.
    """

    return {
        "model": settings.oci_model_id,
        "instructions": AGENT_INSTRUCTIONS,
        "input": payload["user_request"],
        "conversation": conversation_id,
        "tools": [
            {
                "type": "file_search",
                "vector_store_ids": [settings.oci_vector_store_id],
            }
        ],
    }


def _extract_response_text(response: Any) -> str:
    """Extract response text from a Responses API response object.

    Args:
        response: Responses API response object.

    Returns:
        str: Extracted output text, or an empty string when unavailable.
    """

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    return ""


def _extract_stream_token(event: Any) -> str:
    """Extract a text delta from a Responses API stream event.

    Args:
        event: Stream event object or dictionary.

    Returns:
        str: Text delta, or an empty string when the event does not contain one.
    """

    if isinstance(event, dict):
        delta = event.get("delta")
        text = event.get("text")
    else:
        delta = getattr(event, "delta", None)
        text = getattr(event, "text", None)

    if isinstance(delta, str):
        return delta
    if isinstance(text, str):
        return text

    return ""


def _format_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    """Format one Server-Sent Event frame.

    Args:
        event_name: SSE event name.
        payload: JSON-serializable event payload.

    Returns:
        str: Formatted SSE frame.
    """

    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
