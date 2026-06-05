"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: FastAPI entrypoint for the OCI RAG agent.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent import process_agent_request
from app.config import load_settings
from app.openai_client import create_openai_client
from app.schema_validator import SchemaValidationError, validate_agent_request

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="OCI RAG Agent Blueprint")
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


@app.post("/responses")
async def create_response(request: Request) -> JSONResponse:
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
        settings = load_settings()
        response_payload = process_agent_request(
            validated_payload,
            settings,
            request.app.state.openai_client_factory,
        )
    except ValueError as exc:
        LOGGER.info("Configuration error: %s", exc)
        return _error_response(str(exc), status_code=500)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception("Responses API failure")
        return _error_response(f"Responses API failure: {exc}", status_code=502)

    return JSONResponse(response_payload)


def _error_response(error: str, status_code: int) -> JSONResponse:
    """Create a structured JSON error response.

    Args:
        error: Human-readable error message.
        status_code: HTTP status code to return.

    Returns:
        JSONResponse: Error response conforming to the agent response schema.
    """

    return JSONResponse(
        {
            "conversation_id": "",
            "response_id": None,
            "agent_response": "",
            "references": [],
            "error": error,
        },
        status_code=status_code,
    )
