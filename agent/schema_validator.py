"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: JSON Schema based request validation for the OCI RAG agent.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "agent-request.schema.json"


class SchemaValidationError(ValueError):
    """Error raised when a payload does not satisfy the request schema."""


@lru_cache(maxsize=1)
def load_request_schema() -> dict[str, Any]:
    """Load the agent request JSON Schema.

    Returns:
        dict[str, Any]: The parsed request schema.
    """

    with REQUEST_SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def validate_agent_request(payload: Any) -> dict[str, Any]:
    """Validate an agent request payload against the project JSON Schema.

    The MVP validator implements the JSON Schema features used by
    `schemas/agent-request.schema.json`: object type checks, required fields,
    additional property rejection, scalar type checks, string minLength, and the
    conditional requirement for `conversation_id`.

    Args:
        payload: Parsed JSON payload to validate.

    Returns:
        dict[str, Any]: The validated payload.

    Raises:
        SchemaValidationError: If the payload violates the request schema.
    """

    schema = load_request_schema()
    if not isinstance(payload, dict):
        raise SchemaValidationError("Request payload must be a JSON object")

    _validate_required_fields(payload, schema)
    _validate_additional_properties(payload, schema)
    _validate_property_types(payload, schema)
    _validate_conversation_rule(payload)

    return payload


def _validate_required_fields(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate required fields declared by the schema.

    Args:
        payload: Request payload.
        schema: Request JSON Schema.

    Raises:
        SchemaValidationError: If a required field is missing.
    """

    for field_name in schema.get("required", []):
        if field_name not in payload:
            raise SchemaValidationError(f"Missing required field: {field_name}")


def _validate_additional_properties(
    payload: dict[str, Any], schema: dict[str, Any]
) -> None:
    """Reject properties not declared by the schema.

    Args:
        payload: Request payload.
        schema: Request JSON Schema.

    Raises:
        SchemaValidationError: If the payload contains an unknown field.
    """

    if schema.get("additionalProperties", True):
        return

    allowed_fields = set(schema.get("properties", {}))
    unexpected_fields = sorted(set(payload) - allowed_fields)
    if unexpected_fields:
        names = ", ".join(unexpected_fields)
        raise SchemaValidationError(f"Unexpected field: {names}")


def _validate_property_types(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate property types and string length constraints.

    Args:
        payload: Request payload.
        schema: Request JSON Schema.

    Raises:
        SchemaValidationError: If a property has an invalid type or value.
    """

    properties = schema.get("properties", {})
    for field_name, value in payload.items():
        field_schema = properties[field_name]
        expected_type = field_schema.get("type")
        if expected_type == "boolean" and not isinstance(value, bool):
            raise SchemaValidationError(f"Field must be a boolean: {field_name}")
        if expected_type == "string":
            _validate_string_field(field_name, value, field_schema)


def _validate_string_field(
    field_name: str, value: Any, field_schema: dict[str, Any]
) -> None:
    """Validate one string field.

    Args:
        field_name: Name of the field being validated.
        value: Value to validate.
        field_schema: JSON Schema fragment for the field.

    Raises:
        SchemaValidationError: If the value is not a valid string.
    """

    if not isinstance(value, str):
        raise SchemaValidationError(f"Field must be a string: {field_name}")

    min_length = field_schema.get("minLength")
    if min_length is not None and len(value) < min_length:
        raise SchemaValidationError(f"Field must not be empty: {field_name}")


def _validate_conversation_rule(payload: dict[str, Any]) -> None:
    """Validate conversation-specific request rules.

    Args:
        payload: Request payload.

    Raises:
        SchemaValidationError: If conversation fields are inconsistent.
    """

    if payload.get("new_conversation") is False and not payload.get("conversation_id"):
        raise SchemaValidationError(
            "conversation_id is required when new_conversation is false"
        )
