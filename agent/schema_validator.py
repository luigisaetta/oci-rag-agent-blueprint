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
from typing import Any, Callable

from jsonschema import Draft202012Validator, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "agent-request.schema.json"
RESPONSE_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "agent-response.schema.json"


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


@lru_cache(maxsize=1)
def load_response_schema() -> dict[str, Any]:
    """Load the agent response JSON Schema.

    Returns:
        dict[str, Any]: The parsed response schema.
    """

    with RESPONSE_SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def validate_agent_request(payload: Any) -> dict[str, Any]:
    """Validate an agent request payload against the project JSON Schema.

    Args:
        payload: Parsed JSON payload to validate.

    Returns:
        dict[str, Any]: The validated payload.

    Raises:
        SchemaValidationError: If the payload violates the request schema.
    """

    validation_error = _first_validation_error(payload, _request_validator())
    if validation_error:
        raise SchemaValidationError(_format_validation_error(validation_error))

    return payload


def validate_agent_response(payload: Any) -> dict[str, Any]:
    """Validate an agent response payload against the project JSON Schema.

    Args:
        payload: Response payload to validate.

    Returns:
        dict[str, Any]: The validated response payload.

    Raises:
        SchemaValidationError: If the payload violates the response schema.
    """

    validation_error = _first_validation_error(payload, _response_validator())
    if validation_error:
        raise SchemaValidationError(_format_validation_error(validation_error))

    return payload


@lru_cache(maxsize=1)
def _request_validator() -> Draft202012Validator:
    """Build the request schema validator.

    Returns:
        Draft202012Validator: Validator for agent request payloads.
    """

    schema = load_request_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _response_validator() -> Draft202012Validator:
    """Build the response schema validator.

    Returns:
        Draft202012Validator: Validator for agent response payloads.
    """

    schema = load_response_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _first_validation_error(
    payload: Any,
    validator: Draft202012Validator,
) -> ValidationError | None:
    """Return the first validation error for a payload.

    Args:
        payload: Parsed JSON payload to validate.
        validator: JSON Schema validator for the expected payload type.

    Returns:
        ValidationError | None: First validation error, or None when valid.
    """

    errors = sorted(validator.iter_errors(payload), key=_error_sort_key)
    if errors:
        return errors[0]

    return None


def _error_sort_key(error: ValidationError) -> tuple[list[Any], str]:
    """Build a stable sort key for validation errors.

    Args:
        error: Validation error.

    Returns:
        tuple[list[Any], str]: Stable key based on payload path and validator.
    """

    return (list(error.path), error.validator)


def _format_validation_error(error: ValidationError) -> str:
    """Format a JSON Schema validation error for API clients.

    Args:
        error: JSON Schema validation error.

    Returns:
        str: Stable, human-readable validation error message.
    """

    if error.validator == "type" and not error.path:
        return "Request payload must be a JSON object"

    formatter = _validation_error_formatters().get(error.validator)
    if formatter:
        return formatter(error)

    return error.message


def _validation_error_formatters() -> dict[str, Callable[[ValidationError], str]]:
    """Return formatter functions for supported JSON Schema validators.

    Returns:
        dict[str, Callable[[ValidationError], str]]: Error formatter mapping.
    """

    return {
        "required": _format_required_error,
        "additionalProperties": _format_additional_property_error,
        "type": _format_type_error,
        "minLength": _format_min_length_error,
    }


def _format_required_error(error: ValidationError) -> str:
    """Format a required-field validation error.

    Args:
        error: JSON Schema required-field error.

    Returns:
        str: Human-readable required-field error.
    """

    missing_field = _missing_required_field(error)
    if _is_conditional_conversation_error(error, missing_field):
        return "conversation_id is required when new_conversation is false"

    return f"Missing required field: {missing_field}"


def _is_conditional_conversation_error(
    error: ValidationError,
    missing_field: str,
) -> bool:
    """Return whether an error is the request conversation condition.

    Args:
        error: JSON Schema validation error.
        missing_field: Required field missing from the payload.

    Returns:
        bool: True when the error is the conditional request conversation rule.
    """

    schema_path = [str(path_part) for path_part in error.schema_path]
    return missing_field == "conversation_id" and "then" in schema_path


def _format_additional_property_error(error: ValidationError) -> str:
    """Format an additional-property validation error.

    Args:
        error: JSON Schema additional-property error.

    Returns:
        str: Human-readable additional-property error.
    """

    unexpected_field = _unexpected_field(error)
    return f"Unexpected field: {unexpected_field}"


def _format_type_error(error: ValidationError) -> str:
    """Format a field type validation error.

    Args:
        error: JSON Schema type error.

    Returns:
        str: Human-readable type error.
    """

    field_name = _field_name_from_error(error)
    expected_type = _expected_type(error)
    return f"Field must be a {expected_type}: {field_name}"


def _format_min_length_error(error: ValidationError) -> str:
    """Format a minimum-length validation error.

    Args:
        error: JSON Schema minimum-length error.

    Returns:
        str: Human-readable minimum-length error.
    """

    field_name = _field_name_from_error(error)
    return f"Field must not be empty: {field_name}"


def _field_name_from_error(error: ValidationError) -> str:
    """Return the most relevant payload field for an error.

    Args:
        error: JSON Schema validation error.

    Returns:
        str: Payload field name or a generic label.
    """

    if error.path:
        return str(error.path[-1])

    return "request"


def _missing_required_field(error: ValidationError) -> str:
    """Extract the missing field name from a required-field error.

    Args:
        error: JSON Schema required-field error.

    Returns:
        str: Missing field name.
    """

    return str(error.message.split("'")[1])


def _unexpected_field(error: ValidationError) -> str:
    """Extract the unexpected field name from an additional-property error.

    Args:
        error: JSON Schema additional-property error.

    Returns:
        str: Unexpected field name.
    """

    return str(error.message.split("'")[1])


def _expected_type(error: ValidationError) -> str:
    """Return the JSON type expected by the schema.

    Args:
        error: JSON Schema type error.

    Returns:
        str: Expected type name.
    """

    expected_type = error.validator_value
    if isinstance(expected_type, list):
        return " or ".join(str(value) for value in expected_type)

    return str(expected_type)
