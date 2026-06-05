"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: FastAPI entrypoint for the OCI RAG agent.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent.agent import process_agent_request, stream_agent_request
from agent.config import load_settings
from agent.openai_client import create_openai_client
from agent.schema_validator import (
    SchemaValidationError,
    validate_agent_request,
    validate_agent_response,
)

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="OCI RAG Agent Blueprint")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.openai_client_factory = create_openai_client

LOGGER.info("OCI RAG agent application initialized")


@app.get("/health")
def health() -> dict[str, str]:
    """Return agent health status.

    Returns:
        dict[str, str]: Health status payload.
    """

    LOGGER.debug("Health check requested")
    return {"status": "ok"}


@app.post("/responses", response_model=None)
async def create_response(request: Request) -> Response:
    """Handle an agent response request.

    Args:
        request: FastAPI request object containing the JSON payload.

    Returns:
        JSONResponse: Agent response or structured error payload.
    """

    try:
        payload = await request.json()
    except ValueError:
        LOGGER.info("Invalid JSON payload")
        return _error_response("Invalid JSON payload", status_code=400)

    try:
        validated_payload = validate_agent_request(payload)
    except SchemaValidationError as exc:
        LOGGER.info("Request validation error: %s", exc)
        return _error_response(str(exc), status_code=400)

    try:
        return _handle_validated_response_request(request, validated_payload)
    except ValueError as exc:
        LOGGER.info("Configuration error: %s", exc)
        return _error_response(str(exc), status_code=500)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception("Responses API failure")
        return _error_response(f"Responses API failure: {exc}", status_code=502)


def _handle_validated_response_request(
    request: Request,
    validated_payload: dict[str, Any],
) -> Response:
    """Handle a schema-valid response request.

    Args:
        request: FastAPI request object.
        validated_payload: Request payload already validated against JSON Schema.

    Returns:
        Response: Streaming or JSON response for the agent request.

    Raises:
        ValueError: If required runtime configuration is missing.
        Exception: Propagates Responses API failures to the endpoint handler.
    """

    settings = load_settings()
    client_factory = request.app.state.openai_client_factory

    if validated_payload.get("stream", False):
        return StreamingResponse(
            stream_agent_request(
                validated_payload,
                settings,
                client_factory,
            ),
            media_type="text/event-stream",
        )

    response_payload = process_agent_request(
        validated_payload,
        settings,
        client_factory,
    )

    return JSONResponse(validate_agent_response(response_payload))


def _error_response(error: str, status_code: int) -> JSONResponse:
    """Create a structured JSON error response.

    Args:
        error: Human-readable error message.
        status_code: HTTP status code to return.

    Returns:
        JSONResponse: Error response conforming to the agent response schema.
    """

    error_payload = {
        "conversation_id": "",
        "response_id": None,
        "agent_response": "",
        "references": [],
        "usage": None,
        "error": error,
    }
    return JSONResponse(validate_agent_response(error_payload), status_code=status_code)
