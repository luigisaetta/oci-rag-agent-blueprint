"""
Author: L. Saetta
Date last modified: 2026-06-09
License: MIT
Description: FastAPI entrypoint for the OCI RAG agent.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

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


@app.middleware("http")
async def log_request_failures(request: Request, call_next: Any) -> Response:
    """Log request lifecycle and unhandled failures with a request identifier.

    Args:
        request: Incoming FastAPI request.
        call_next: Next ASGI handler in the middleware chain.

    Returns:
        Response: Downstream response, or a sanitized JSON error response.
    """

    request_id = str(uuid4())
    request.state.request_id = request_id
    LOGGER.info(
        "Request started request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
    )
    try:
        response = await call_next(request)
    except Exception:  # pylint: disable=broad-exception-caught
        LOGGER.exception(
            "Unhandled request failure request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        return _error_response(
            f"Internal server error. See server logs for request_id={request_id}.",
            status_code=500,
        )

    LOGGER.info(
        "Request completed request_id=%s method=%s path=%s status_code=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
    )
    response.headers["x-request-id"] = request_id
    return response


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
        LOGGER.info(
            "Invalid JSON payload request_id=%s",
            _request_id(request),
        )
        return _error_response("Invalid JSON payload", status_code=400)

    try:
        validated_payload = validate_agent_request(payload)
    except SchemaValidationError as exc:
        LOGGER.info(
            "Request validation error request_id=%s error=%s",
            _request_id(request),
            exc,
        )
        return _error_response(str(exc), status_code=400)

    try:
        return _handle_validated_response_request(request, validated_payload)
    except ValueError as exc:
        LOGGER.exception(
            "Configuration error request_id=%s",
            _request_id(request),
        )
        return _error_response(str(exc), status_code=500)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception(
            "Responses API failure request_id=%s",
            _request_id(request),
        )
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


def _request_id(request: Request) -> str:
    """Return the request identifier assigned by middleware.

    Args:
        request: FastAPI request object.

    Returns:
        str: Request identifier, or `n/a` if middleware did not assign one.
    """

    return str(getattr(request.state, "request_id", "n/a"))
