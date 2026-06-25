"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: FastAPI entrypoint for the OCI RAG agent.
"""

from __future__ import annotations

import logging
from os import environ
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent.agent import process_agent_request, stream_agent_request
from agent.config import load_settings
from agent.document_ingestion import (
    ConnectorIngestionRequest,
    DocumentIngestionDisabledError,
    DocumentIngestionError,
    IncomingDocument,
    build_oci_document_ingestion_clients,
    get_connector_ingestion_status,
    load_document_ingestion_settings,
    submit_connector_ingestion,
)
from agent.environment_diagnostics import build_environment_diagnostics
from agent.openai_client import create_openai_client
from agent.schema_validator import (
    SchemaValidationError,
    validate_agent_request,
    validate_agent_response,
)
from management.document_ingestion import load_file_sync_details_class

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
app.state.document_ingestion_client_factory = build_oci_document_ingestion_clients
app.state.file_sync_details_factory = load_file_sync_details_class

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


@app.get("/config/environment")
def runtime_environment() -> dict[str, dict[str, str] | list[str]]:
    """Return non-secret runtime environment variables for diagnostics.

    Returns:
        dict[str, dict[str, str] | list[str]]: Environment diagnostics payload.
    """

    return build_environment_diagnostics(environ)


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


@app.post("/documents/ingestions")
async def submit_document_ingestion(
    request: Request,
    files: list[UploadFile] | None = File(None),
    prefix: str = Form(""),
    sync_display_name: str | None = Form(None),
    overwrite: bool = Form(False),
) -> JSONResponse:
    """Upload documents and submit a connector ingestion job.

    Args:
        request: FastAPI request object.
        files: Uploaded document files.
        prefix: Optional Object Storage object prefix.
        sync_display_name: Optional connector file sync display name.
        overwrite: Whether existing Object Storage objects may be replaced.

    Returns:
        JSONResponse: Ingestion submission result or structured error.
    """

    try:
        settings = load_document_ingestion_settings()
        if not settings.enabled:
            raise DocumentIngestionDisabledError("Document ingestion is not enabled.")
        object_storage_client, generative_ai_client = (
            request.app.state.document_ingestion_client_factory()
        )
        incoming_documents = [
            IncomingDocument(
                filename=file.filename or "",
                body=file.file,
                size_bytes=_uploaded_file_size(file),
            )
            for file in files or []
        ]
        result = submit_connector_ingestion(
            ConnectorIngestionRequest(
                documents=incoming_documents,
                prefix=prefix,
                sync_display_name=sync_display_name,
                overwrite=overwrite,
                details_factory=request.app.state.file_sync_details_factory(),
            ),
            settings,
            object_storage_client,
            generative_ai_client,
        )
    except ValueError as exc:
        LOGGER.info(
            "Document ingestion configuration error request_id=%s error=%s",
            _request_id(request),
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=500)
    except DocumentIngestionError as exc:
        LOGGER.info(
            "Document ingestion submission failed request_id=%s error=%s",
            _request_id(request),
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception(
            "Document ingestion submission failure request_id=%s",
            _request_id(request),
        )
        return JSONResponse(
            {"error": f"Document ingestion submission failed: {exc}"},
            status_code=502,
        )

    return JSONResponse(_document_ingestion_result_payload(result))


@app.get("/documents/ingestions/{job_id}")
async def get_document_ingestion_status(request: Request, job_id: str) -> JSONResponse:
    """Return the current state of a connector ingestion job.

    Args:
        request: FastAPI request object.
        job_id: Connector file sync job identifier.

    Returns:
        JSONResponse: Connector job status or structured error.
    """

    try:
        settings = load_document_ingestion_settings()
        if not settings.enabled:
            raise DocumentIngestionDisabledError("Document ingestion is not enabled.")
        _, generative_ai_client = request.app.state.document_ingestion_client_factory()
        status = get_connector_ingestion_status(
            job_id,
            settings,
            generative_ai_client,
        )
    except ValueError as exc:
        LOGGER.info(
            "Document ingestion status configuration error request_id=%s error=%s",
            _request_id(request),
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=500)
    except DocumentIngestionError as exc:
        LOGGER.info(
            "Document ingestion status lookup failed request_id=%s error=%s",
            _request_id(request),
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception(
            "Document ingestion status failure request_id=%s",
            _request_id(request),
        )
        return JSONResponse(
            {"error": f"Document ingestion status lookup failed: {exc}"},
            status_code=502,
        )

    return JSONResponse(_document_ingestion_status_payload(status))


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


def _uploaded_file_size(file: UploadFile) -> int:
    """Return the uploaded file size without consuming its content.

    Args:
        file: FastAPI uploaded file.

    Returns:
        int: File size in bytes.
    """

    if file.size is not None:
        return int(file.size)

    current_position = file.file.tell()
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(current_position)
    return size


def _document_ingestion_result_payload(result: Any) -> dict[str, Any]:
    """Convert an ingestion submission result to a JSON-safe payload.

    Args:
        result: Document ingestion result object.

    Returns:
        dict[str, Any]: JSON response payload.
    """

    payload = {
        "status": "submitted",
        "job_id": result.job_id,
        "connector_id": result.connector_id,
        "namespace": result.namespace,
        "bucket": result.bucket,
        "uploaded_objects": result.uploaded_objects,
        "job_lifecycle_state": result.job_lifecycle_state,
        "job_trigger_type": result.job_trigger_type,
        "job_display_name": result.job_display_name,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _document_ingestion_status_payload(status: Any) -> dict[str, Any]:
    """Convert an ingestion job status to a JSON-safe payload.

    Args:
        status: Document ingestion status object.

    Returns:
        dict[str, Any]: JSON response payload.
    """

    payload = {
        "job_id": status.job_id,
        "connector_id": status.connector_id,
        "lifecycle_state": status.lifecycle_state,
        "display_name": status.display_name,
        "time_created": status.time_created,
        "time_updated": status.time_updated,
        "lifecycle_details": status.lifecycle_details,
        "trigger_type": status.trigger_type,
    }
    return {key: value for key, value in payload.items() if value is not None}


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
