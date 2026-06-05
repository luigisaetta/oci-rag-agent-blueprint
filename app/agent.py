"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Core request processing logic for the OCI RAG agent.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.config import AgentSettings

LOGGER = logging.getLogger(__name__)
RESPONSES_TIMEOUT_SECONDS = 60


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
        model=settings.oci_model_id,
        input=payload["user_request"],
        conversation=conversation_id,
        tools=[
            {
                "type": "file_search",
                "vector_store_ids": [settings.oci_vector_store_id],
            }
        ],
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
