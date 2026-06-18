"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Data models and validation helpers for Agent Factory deployment runs.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# pylint: disable=too-many-instance-attributes

ResourceMode = Literal["create", "reuse"]
ConnectorMode = Literal["create", "reuse", "skip"]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]

RESOURCE_MODES = {"create", "reuse"}
CONNECTOR_MODES = {"create", "reuse", "skip"}
STREAM_FINALIZATION_MODES = {"never", "auto", "always"}
SUPPORTED_REGIONS = {"eu-frankfurt-1", "us-chicago-1"}
SUPPORTED_MODEL_IDS = {
    "openai.gpt-5.4",
    "google.gemini-2.5-pro",
    "openai.gpt-oss-120b",
}
AUTH_REQUIRED_FIELDS = (
    "identity_domain_compartment",
    "identity_domain_url",
    "auth_scope",
    "auth_audience",
)


@dataclass(frozen=True)
class ValidationResult:
    """Validation result for an incoming deployment payload.

    Attributes:
        payload: Normalized payload when validation succeeds.
        errors: Validation errors keyed by field name.
    """

    payload: dict[str, Any] | None
    errors: dict[str, str]


@dataclass
class FactoryStep:
    """One Agent Factory deployment step.

    Attributes:
        step_id: Stable step identifier.
        display_name: Human-readable step name.
        status: Current step status.
        command: Optional command associated with the step.
        started_at: ISO-8601 start timestamp.
        ended_at: ISO-8601 end timestamp.
        outputs: Non-secret step outputs.
        error: Sanitized step error message.
    """

    step_id: str
    display_name: str
    status: StepStatus = "pending"
    command: list[str] | None = None
    started_at: str | None = None
    ended_at: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the step to a JSON-serializable dictionary.

        Returns:
            dict[str, Any]: Step payload for API responses.
        """

        return {
            "step_id": self.step_id,
            "display_name": self.display_name,
            "status": self.status,
            "command": self.command,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "outputs": self.outputs,
            "error": self.error,
        }


@dataclass
class DeploymentRun:
    """Agent Factory deployment run.

    Attributes:
        deployment_run_id: Unique run identifier.
        dry_run: Whether this run avoids OCI writes.
        status: Overall run status.
        submitted_at: ISO-8601 submission timestamp.
        completed_at: ISO-8601 completion timestamp.
        request: Redacted request payload.
        steps: Ordered workflow steps.
        commands: Commands generated for dry-run review or execution planning.
        outputs: Final non-secret deployment outputs.
        error: Sanitized run-level error message.
    """

    deployment_run_id: str
    dry_run: bool
    status: StepStatus
    submitted_at: str
    completed_at: str | None
    request: dict[str, Any]
    steps: list[FactoryStep]
    commands: list[list[str]]
    outputs: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the run to a JSON-serializable dictionary.

        Returns:
            dict[str, Any]: Deployment run payload for API responses.
        """

        return {
            "deployment_run_id": self.deployment_run_id,
            "dry_run": self.dry_run,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "request": self.request,
            "steps": [step.to_dict() for step in self.steps],
            "commands": self.commands,
            "commands_text": format_commands(self.commands),
            "outputs": self.outputs,
            "error": self.error,
        }


def utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format.

    Returns:
        str: UTC timestamp.
    """

    return datetime.now(timezone.utc).isoformat()


def validate_deployment_payload(payload: dict[str, Any]) -> ValidationResult:
    """Validate and normalize an Agent Factory deployment payload.

    Args:
        payload: Raw JSON payload submitted to the API.

    Returns:
        ValidationResult: Normalized payload or field-level validation errors.
    """

    normalized = _apply_defaults(payload)
    errors: dict[str, str] = {}

    for field_name in _required_fields():
        if not _has_text(normalized.get(field_name)):
            errors[field_name] = "This field is required."

    _validate_choice(errors, normalized, "bucket_mode", RESOURCE_MODES)
    _validate_choice(errors, normalized, "vector_store_mode", RESOURCE_MODES)
    _validate_choice(errors, normalized, "connector_mode", CONNECTOR_MODES)
    _validate_choice(errors, normalized, "region", SUPPORTED_REGIONS)
    _validate_choice(errors, normalized, "model_id", SUPPORTED_MODEL_IDS)
    _validate_choice(
        errors,
        normalized,
        "stream_finalization_mode",
        STREAM_FINALIZATION_MODES,
    )

    if normalized["connector_mode"] in {"create", "reuse"} and not _has_text(
        normalized.get("connector_name")
    ):
        errors["connector_name"] = "Connector name is required for this mode."

    if not isinstance(normalized["jwt_protection_enabled"], bool):
        errors["jwt_protection_enabled"] = "Expected a boolean value."

    if normalized["jwt_protection_enabled"] is True:
        for field_name in AUTH_REQUIRED_FIELDS:
            if not _has_text(normalized.get(field_name)):
                errors[field_name] = "This field is required when auth is enabled."
        if _has_text(normalized.get("identity_domain_url")) and not str(
            normalized["identity_domain_url"]
        ).startswith("https://"):
            errors["identity_domain_url"] = (
                "Identity Domain URL must be the exact https:// URL from OCI Console."
            )

    if normalized["endpoint_visibility"] != "public":
        errors["endpoint_visibility"] = "Only public endpoints are supported yet."

    if normalized["network_mode"] != "oracle_managed":
        errors["network_mode"] = "Only Oracle-managed networking is supported yet."

    if normalized["container_image_tag"] == "latest":
        errors["container_image_tag"] = "Use a non-floating image tag."

    _validate_positive_int(errors, normalized, "file_search_max_num_results", 1, 50)
    _validate_positive_int(errors, normalized, "responses_timeout_seconds", 1, 300)

    if errors:
        return ValidationResult(payload=None, errors=errors)

    return ValidationResult(payload=normalized, errors={})


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a deployment payload safe for API status responses.

    Args:
        payload: Normalized deployment payload.

    Returns:
        dict[str, Any]: Redacted payload.
    """

    redacted = dict(payload)
    if redacted.get("openai_api_key"):
        redacted["openai_api_key"] = "********"
    if redacted.get("ocir_password"):
        redacted["ocir_password"] = "********"
    if redacted.get("confidential_application_secret"):
        redacted["confidential_application_secret"] = "********"
    return redacted


def format_commands(commands: list[list[str]]) -> str:
    """Format structured commands as a shell script.

    Args:
        commands: Command arguments.

    Returns:
        str: Shell script text.
    """

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
    ]
    lines.extend(_shell_join(command) for command in commands)
    lines.append("")
    return "\n".join(lines)


def _apply_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply deployment defaults to a raw payload.

    Args:
        payload: Raw JSON payload.

    Returns:
        dict[str, Any]: Payload with defaults applied.
    """

    normalized = _strip_text_values(payload)
    normalized.setdefault("bucket_mode", "create")
    normalized.setdefault("vector_store_mode", "create")
    normalized.setdefault("connector_mode", "create")
    normalized.setdefault("jwt_protection_enabled", False)
    normalized.setdefault("identity_domain_compartment", "")
    if "identity_domain_url" not in normalized and "identity_domain_name" in normalized:
        normalized["identity_domain_url"] = normalized["identity_domain_name"]
    normalized.setdefault("identity_domain_url", "")
    normalized.setdefault("auth_scope", "")
    normalized.setdefault("auth_audience", "")
    normalized.setdefault("confidential_application_id", "")
    normalized.setdefault("confidential_application_secret", "")
    normalized.setdefault("endpoint_visibility", "public")
    normalized.setdefault("network_mode", "oracle_managed")
    normalized.setdefault("file_search_max_num_results", 10)
    normalized.setdefault("responses_timeout_seconds", 60)
    normalized.setdefault("stream_finalization_mode", "never")
    normalized.setdefault("dry_run", True)
    if "genai_project" not in normalized and "genai_project_ocid" in normalized:
        normalized["genai_project"] = normalized["genai_project_ocid"]
    return normalized


def _strip_text_values(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a payload with surrounding whitespace removed.

    Args:
        payload: Raw JSON payload.

    Returns:
        dict[str, Any]: Payload with string values stripped.
    """

    return {
        field_name: value.strip() if isinstance(value, str) else value
        for field_name, value in payload.items()
    }


def _required_fields() -> tuple[str, ...]:
    """Return fields required for the first Agent Factory implementation.

    Returns:
        tuple[str, ...]: Required field names.
    """

    return (
        "compartment",
        "region",
        "bucket_name",
        "vector_store_name",
        "hosted_application_name",
        "deployment_name",
        "genai_project",
        "model_id",
        "openai_api_key",
        "ocir_username",
        "ocir_password",
        "container_repository_name",
        "container_image_tag",
    )


def _validate_choice(
    errors: dict[str, str],
    payload: dict[str, Any],
    field_name: str,
    accepted_values: set[str],
) -> None:
    """Validate an enumerated string field.

    Args:
        errors: Mutable validation errors.
        payload: Normalized payload.
        field_name: Field to validate.
        accepted_values: Accepted string values.
    """

    value = payload.get(field_name)
    if value not in accepted_values:
        accepted = ", ".join(sorted(accepted_values))
        errors[field_name] = f"Expected one of: {accepted}."


def _validate_positive_int(
    errors: dict[str, str],
    payload: dict[str, Any],
    field_name: str,
    minimum_value: int,
    maximum_value: int,
) -> None:
    """Validate an integer range field.

    Args:
        errors: Mutable validation errors.
        payload: Normalized payload.
        field_name: Field to validate.
        minimum_value: Minimum accepted value.
        maximum_value: Maximum accepted value.
    """

    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        errors[field_name] = "Expected an integer value."
        return

    if not minimum_value <= value <= maximum_value:
        errors[field_name] = (
            f"Expected a value from {minimum_value} to {maximum_value}."
        )


def _has_text(value: Any) -> bool:
    """Return whether a value is a non-empty string.

    Args:
        value: Value to inspect.

    Returns:
        bool: True when the value contains non-whitespace text.
    """

    return isinstance(value, str) and bool(value.strip())


def _shell_join(command: list[str]) -> str:
    """Join command arguments for display in a shell script.

    Args:
        command: Command arguments.

    Returns:
        str: Shell-safe command display string.
    """

    return shlex.join(command)
