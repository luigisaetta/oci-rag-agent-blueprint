"""
Author: L. Saetta
Date last modified: 2026-06-17
License: MIT
Description: Live command execution helpers for Agent Factory deployments.
"""

from __future__ import annotations

# pylint: disable=duplicate-code,too-many-lines

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from agent_factory_api.commands import (
    build_agent_runtime_environment,
    build_hosted_application_artifacts,
    build_ocir_registry,
    build_resolved_identifiers,
)

ProgressCallback = Callable[[str, str, dict[str, Any] | None], None]
ENTITY_OCID_PREFIXES = {
    "HOSTED_APPLICATION": "ocid1.generativeaihostedapplication.",
    "HOSTED_DEPLOYMENT": "ocid1.generativeaihosteddeployment.",
}
HOSTED_APPLICATION_API_VERSION = "20251112"
DEFAULT_DEPLOYMENT_WAIT_INTERVAL_SECONDS = 15.0
DEFAULT_DEPLOYMENT_WAIT_TIMEOUT_SECONDS = 900.0
DEPLOYMENT_WAIT_INTERVAL_ENV_VAR = "AGENT_FACTORY_DEPLOYMENT_WAIT_INTERVAL_SECONDS"
DEPLOYMENT_WAIT_TIMEOUT_ENV_VAR = "AGENT_FACTORY_DEPLOYMENT_WAIT_TIMEOUT_SECONDS"
READY_DEPLOYMENT_STATES = {"ACTIVE", "SUCCEEDED"}
FAILED_DEPLOYMENT_STATES = {
    "CANCELED",
    "CANCELING",
    "DELETED",
    "DELETING",
    "FAILED",
}


class CommandExecutionError(RuntimeError):
    """Raised when a live deployment command fails."""

    def __init__(
        self,
        step_id: str,
        message: str,
        partial_outputs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the command execution error.

        Args:
            step_id: Workflow step that failed.
            message: Sanitized failure message.
            partial_outputs: Non-secret outputs collected before failure.
        """

        super().__init__(message)
        self.step_id = step_id
        self.partial_outputs = partial_outputs or {}


def execute_live_deployment_commands(  # pylint: disable=too-many-locals
    payload: dict[str, Any],
    commands_by_step_id: dict[str, list[str]],
    progress_callback: ProgressCallback,
) -> dict[str, Any]:
    """Execute the live Docker, OCIR, and Hosted Application commands.

    Args:
        payload: Resolved deployment payload.
        commands_by_step_id: Planned commands keyed by workflow step.
        progress_callback: Callback used to update step state.

    Returns:
        dict[str, Any]: Non-secret execution outputs.

    Raises:
        CommandExecutionError: If a required command fails or a required local
            executable is missing.
    """

    _require_executable("docker", "docker-build")
    _require_executable("oci", "hosted-application")

    repo_root = _repo_root()
    resolved_identifiers = build_resolved_identifiers(payload)
    _ensure_live_identifiers_resolved(resolved_identifiers)
    runtime_environment = build_agent_runtime_environment(payload, resolved_identifiers)
    artifacts = build_hosted_application_artifacts(
        payload,
        runtime_environment,
        resolved_identifiers,
    )

    outputs: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="agent-factory-artifacts-") as artifact_dir:
        artifact_path = Path(artifact_dir)
        _write_artifacts(artifact_path, artifacts)

        with tempfile.TemporaryDirectory(prefix="agent-factory-docker-") as docker_dir:
            environment = dict(os.environ)
            environment["DOCKER_CONFIG"] = docker_dir

            _run_step(
                "docker-build",
                _command(commands_by_step_id, "docker-build"),
                progress_callback,
                cwd=repo_root,
                env=environment,
                secrets=[str(payload["ocir_password"])],
            )
            _run_step(
                "registry",
                _command(commands_by_step_id, "registry"),
                progress_callback,
                payload=payload,
                cwd=repo_root,
                env=environment,
                secrets=[str(payload["ocir_password"])],
            )
            _run_docker_login(payload, progress_callback, environment, repo_root)
            _run_step(
                "docker-push",
                _command(commands_by_step_id, "docker-push"),
                progress_callback,
                cwd=repo_root,
                env=environment,
                secrets=[str(payload["ocir_password"])],
            )

        progress_callback(
            "runtime-environment",
            "succeeded",
            {
                "artifact": str(
                    artifact_path / "hosted-application-environment-variables.json"
                )
            },
        )

        hosted_application_id = _find_existing_hosted_application_id(
            payload=payload,
            compartment_id=resolved_identifiers["compartment_id"],
            progress_callback=progress_callback,
            cwd=repo_root,
            secrets=[str(payload["ocir_password"]), str(payload["openai_api_key"])],
        )
        if not hosted_application_id:
            hosted_application_output = _run_json_step(
                "hosted-application",
                _resolve_artifact_paths(
                    _command(commands_by_step_id, "hosted-application"), artifact_path
                ),
                progress_callback,
                cwd=repo_root,
                secrets=[str(payload["ocir_password"]), str(payload["openai_api_key"])],
            )
            hosted_application_id = _extract_identifier(
                hosted_application_output,
                entity_type="HOSTED_APPLICATION",
            )
        if not hosted_application_id:
            raise CommandExecutionError(
                "hosted-application",
                "Hosted Application creation did not return an OCID.",
            )
        outputs["hosted_application_id"] = hosted_application_id

        hosted_deployment_output = _run_json_step(
            "hosted-deployment",
            _replace_placeholders(
                _resolve_artifact_paths(
                    _command(commands_by_step_id, "hosted-deployment"), artifact_path
                ),
                {
                    "<hosted-application-ocid-from-create-response>": hosted_application_id
                },
            ),
            progress_callback,
            cwd=repo_root,
            secrets=[str(payload["ocir_password"]), str(payload["openai_api_key"])],
        )
        hosted_deployment_id = _extract_identifier(
            hosted_deployment_output,
            entity_type="HOSTED_DEPLOYMENT",
        )
        if not hosted_deployment_id:
            raise CommandExecutionError(
                "hosted-deployment",
                "Hosted deployment creation did not return an OCID.",
            )
        outputs["hosted_deployment_id"] = hosted_deployment_id

        readiness_command = _replace_placeholders(
            _command(commands_by_step_id, "deployment-readiness"),
            {"<hosted-deployment-ocid>": hosted_deployment_id},
        )
        readiness_output = _wait_for_deployment_ready(
            command=readiness_command,
            progress_callback=progress_callback,
            cwd=repo_root,
            secrets=[str(payload["ocir_password"]), str(payload["openai_api_key"])],
        )
        endpoint_url = _find_endpoint_url(readiness_output) or _build_invoke_url(
            region=str(payload["region"]),
            hosted_application_id=hosted_application_id,
        )
        outputs["endpoint_url"] = endpoint_url
        try:
            _run_step(
                "health",
                _replace_placeholders(
                    _command(commands_by_step_id, "health"),
                    {"<deployed-health-endpoint>": endpoint_url.rstrip("/")},
                ),
                progress_callback,
                cwd=repo_root,
                secrets=[str(payload["ocir_password"]), str(payload["openai_api_key"])],
            )
        except CommandExecutionError as exc:
            raise CommandExecutionError(
                exc.step_id,
                str(exc),
                partial_outputs=outputs,
            ) from exc

    return outputs


def _run_step(  # pylint: disable=too-many-arguments
    step_id: str,
    command: list[str],
    progress_callback: ProgressCallback,
    *,
    payload: dict[str, Any] | None = None,
    cwd: Path,
    env: dict[str, str] | None = None,
    secrets: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and update progress for one workflow step.

    Args:
        step_id: Workflow step identifier.
        command: Command arguments to execute.
        progress_callback: Callback used to update run state.
        payload: Normalized deployment payload, if step-specific output needs it.
        cwd: Working directory for the command.
        env: Optional command environment.
        secrets: Secret values to redact from command outputs.

    Returns:
        subprocess.CompletedProcess[str]: Completed command result.
    """

    progress_callback(step_id, "running", None)
    try:
        result = _run_command(
            command,
            cwd=cwd,
            env=env,
            secrets=secrets,
            step_id=step_id,
        )
    except CommandExecutionError as exc:
        if step_id == "registry" and _is_existing_registry_repository_error(str(exc)):
            progress_callback(
                step_id,
                "succeeded",
                _registry_reuse_outputs(payload),
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr=str(exc))
        raise

    outputs = _command_outputs(result, secrets or [])
    if step_id == "registry":
        outputs = {**outputs, "created": True}
    progress_callback(step_id, "succeeded", outputs)
    return result


def _run_json_step(
    step_id: str,
    command: list[str],
    progress_callback: ProgressCallback,
    *,
    cwd: Path,
    secrets: list[str] | None = None,
) -> dict[str, Any]:
    """Run a command that should return JSON and update progress."""

    result = _run_step(
        step_id,
        command,
        progress_callback,
        cwd=cwd,
        secrets=secrets,
    )
    return _load_json_output(step_id, result, secrets or [])


def _wait_for_deployment_ready(
    *,
    command: list[str],
    progress_callback: ProgressCallback,
    cwd: Path,
    secrets: list[str],
) -> dict[str, Any]:
    """Poll Hosted Deployment status until it is ready or fails.

    Args:
        command: OCI CLI get command for the Hosted Deployment.
        progress_callback: Callback used to update step state.
        cwd: Working directory for the command.
        secrets: Secret values to redact from command outputs.

    Returns:
        dict[str, Any]: Last readiness command output.

    Raises:
        CommandExecutionError: If the deployment fails or times out.
    """

    deadline = time.monotonic() + _deployment_wait_timeout_seconds()
    interval = _deployment_wait_interval_seconds()
    last_state = "UNKNOWN"

    while True:
        output = _run_json_step(
            "deployment-readiness",
            command,
            progress_callback,
            cwd=cwd,
            secrets=secrets,
        )
        state = _deployment_lifecycle_state(output)
        if state:
            last_state = state
        if state in READY_DEPLOYMENT_STATES:
            return output
        if state in FAILED_DEPLOYMENT_STATES:
            raise CommandExecutionError(
                "deployment-readiness",
                f"Hosted Deployment entered failed state {state}.",
            )
        if not state and _find_endpoint_url(output):
            return output
        if time.monotonic() >= deadline:
            raise CommandExecutionError(
                "deployment-readiness",
                "Hosted Deployment was not ready after "
                f"{_deployment_wait_timeout_seconds():g} seconds. "
                f"Last state: {last_state}.",
            )
        progress_callback(
            "deployment-readiness",
            "running",
            {"lifecycle_state": last_state, "waiting": True},
        )
        time.sleep(interval)


def _load_json_output(
    step_id: str,
    result: subprocess.CompletedProcess[str],
    secrets: list[str],
) -> dict[str, Any]:
    """Load JSON output from a command result, allowing OCI CLI status prefixes.

    Args:
        step_id: Workflow step identifier.
        result: Completed command result.
        secrets: Secret values to redact from diagnostic messages.

    Returns:
        dict[str, Any]: Parsed JSON object, or an empty object for empty stdout.

    Raises:
        CommandExecutionError: If stdout does not contain a JSON object.
    """

    output = (result.stdout or "").strip()
    if not output:
        return {}

    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            decoded, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded

    sanitized_output = _sanitize_text(output, secrets)
    if len(sanitized_output) > 500:
        sanitized_output = f"{sanitized_output[:500]}..."
    detail = f" Output was: {sanitized_output}" if sanitized_output else ""
    try:
        json.loads(output)
    except json.JSONDecodeError as exc:
        raise CommandExecutionError(
            step_id,
            f"{step_id} did not return valid JSON.{detail}",
        ) from exc
    raise CommandExecutionError(
        step_id,
        f"{step_id} returned JSON that was not an object.{detail}",
    )


def _find_existing_hosted_application_id(  # pylint: disable=too-many-arguments
    *,
    payload: dict[str, Any],
    compartment_id: str,
    progress_callback: ProgressCallback,
    cwd: Path,
    secrets: list[str],
) -> str | None:
    """Return an existing Hosted Application OCID for the requested display name.

    Args:
        payload: Normalized deployment payload.
        compartment_id: Resolved compartment OCID to search.
        progress_callback: Callback used to update the Hosted Application step.
        cwd: Working directory for OCI CLI execution.
        secrets: Secret values to redact from command output.

    Returns:
        str | None: Existing Hosted Application OCID, if one is found.
    """

    progress_callback("hosted-application", "running", {"action": "lookup"})
    result = _run_command(
        _build_list_hosted_applications_command(payload, compartment_id),
        cwd=cwd,
        secrets=secrets,
        step_id="hosted-application",
    )
    output = _load_json_output("hosted-application", result, secrets)
    display_name = str(payload["hosted_application_name"])
    matches = [
        item
        for item in _extract_list_items(output)
        if _first_string(item, "display-name", "displayName", "name") == display_name
        and _first_string(item, "id")
        and not _is_deleted_hosted_application(item)
    ]
    if not matches:
        return None
    hosted_application = matches[0]
    hosted_application_id = _first_string(hosted_application, "id")
    lifecycle_state = _first_string(
        hosted_application,
        "lifecycle-state",
        "lifecycleState",
    ).upper()
    if lifecycle_state and lifecycle_state != "ACTIVE":
        _wait_for_hosted_application(
            payload=payload,
            hosted_application_id=hosted_application_id,
            progress_callback=progress_callback,
            cwd=cwd,
            secrets=secrets,
        )
    progress_callback(
        "hosted-application",
        "succeeded",
        {
            "hosted_application_id": hosted_application_id,
            "reused": True,
            "display_name": display_name,
            "lifecycle_state": "ACTIVE",
        },
    )
    return hosted_application_id


def _wait_for_hosted_application(  # pylint: disable=too-many-arguments
    *,
    payload: dict[str, Any],
    hosted_application_id: str,
    progress_callback: ProgressCallback,
    cwd: Path,
    secrets: list[str],
) -> None:
    """Wait for an existing Hosted Application to become active using OCI CLI.

    Args:
        payload: Normalized deployment payload.
        hosted_application_id: Existing Hosted Application OCID.
        progress_callback: Callback used to update the Hosted Application step.
        cwd: Working directory for OCI CLI execution.
        secrets: Secret values to redact from command output.
    """

    progress_callback(
        "hosted-application",
        "running",
        {
            "action": "wait",
            "hosted_application_id": hosted_application_id,
        },
    )
    _run_json_step(
        "hosted-application",
        [
            "oci",
            "--region",
            str(payload["region"]),
            "--output",
            "json",
            "generative-ai",
            "hosted-application",
            "get",
            "--hosted-application-id",
            hosted_application_id,
            "--wait-for-state",
            "SUCCEEDED",
        ],
        progress_callback,
        cwd=cwd,
        secrets=secrets,
    )


def _build_list_hosted_applications_command(
    payload: dict[str, Any], compartment_id: str
) -> list[str]:
    """Build the OCI CLI command used to find existing Hosted Applications.

    Args:
        payload: Normalized deployment payload.
        compartment_id: Resolved compartment OCID to search.

    Returns:
        list[str]: OCI CLI command arguments.
    """

    return [
        "oci",
        "--region",
        str(payload["region"]),
        "--output",
        "json",
        "generative-ai",
        "hosted-application-collection",
        "list-hosted-applications",
        "--compartment-id",
        compartment_id,
        "--all",
    ]


def _extract_list_items(command_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract OCI CLI list items from common response shapes.

    Args:
        command_output: Parsed OCI CLI JSON response.

    Returns:
        list[dict[str, Any]]: List items found under `data` or `data.items`.
    """

    data = command_output.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _first_string(item: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string value for the given keys.

    Args:
        item: OCI CLI response item.
        keys: Candidate response keys.

    Returns:
        str: First non-empty value, or an empty string.
    """

    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _is_deleted_hosted_application(item: dict[str, Any]) -> bool:
    """Return whether a listed Hosted Application is deleted or deleting.

    Args:
        item: Hosted Application list item.

    Returns:
        bool: True when the item is not reusable.
    """

    lifecycle_state = _first_string(item, "lifecycle-state", "lifecycleState").upper()
    return lifecycle_state in {"DELETED", "DELETING"}


def _run_docker_login(
    payload: dict[str, Any],
    progress_callback: ProgressCallback,
    environment: dict[str, str],
    repo_root: Path,
) -> None:
    """Run Docker login using stdin so the password is not part of argv."""

    step_id = "registry-login"
    progress_callback(step_id, "running", None)
    command = [
        "docker",
        "login",
        build_ocir_registry(payload),
        "--username",
        str(payload["ocir_username"]),
        "--password-stdin",
    ]
    result = _run_command(
        command,
        cwd=repo_root,
        env=environment,
        input_text=f"{payload['ocir_password']}\n",
        secrets=[str(payload["ocir_password"])],
        step_id=step_id,
    )
    progress_callback(
        step_id, "succeeded", _command_outputs(result, [str(payload["ocir_password"])])
    )


def _run_command(  # pylint: disable=too-many-arguments
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    secrets: list[str] | None = None,
    step_id: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command and raise a sanitized error on failure."""

    effective_step_id = step_id or _step_id_from_command(command)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=3600,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandExecutionError(
            effective_step_id,
            f"{effective_step_id} timed out.",
        ) from exc
    except OSError as exc:
        raise CommandExecutionError(
            effective_step_id,
            f"{effective_step_id} could not start: {exc}",
        ) from exc

    if result.returncode != 0:
        detail = _sanitize_text(
            " ".join(part.strip() for part in (result.stderr, result.stdout) if part),
            secrets or [],
        )
        detail = detail or f"command exited with status {result.returncode}"
        raise CommandExecutionError(effective_step_id, detail)

    return result


def _is_existing_registry_repository_error(error_message: str) -> bool:
    """Return whether an OCIR create failure means the repository already exists.

    Args:
        error_message: Sanitized OCI CLI error output.

    Returns:
        bool: True when the registry repository can be reused.
    """

    normalized_error = error_message.lower()
    return (
        "namespace_conflict" in normalized_error
        and "repository already exists" in normalized_error
    )


def _registry_reuse_outputs(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Build non-secret outputs for a reused OCIR repository.

    Args:
        payload: Normalized deployment payload, when available.

    Returns:
        dict[str, Any]: Registry step outputs.
    """

    outputs: dict[str, Any] = {
        "created": False,
        "reused": True,
        "message": "OCI Container Registry repository already exists.",
    }
    if payload is not None:
        outputs["repository"] = str(payload["container_repository_name"])
    return outputs


def _command_outputs(
    result: subprocess.CompletedProcess[str], secrets: list[str]
) -> dict[str, Any]:
    """Return bounded, non-secret command output metadata."""

    output = _sanitize_text((result.stdout or result.stderr or "").strip(), secrets)
    return {"output": output[-2000:]} if output else {}


def _write_artifacts(artifact_dir: Path, artifacts: dict[str, Any]) -> None:
    """Write Hosted Application JSON artifacts to a temporary directory."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in artifacts.items():
        (artifact_dir / filename).write_text(
            json.dumps(content, indent=2),
            encoding="utf-8",
        )


def _resolve_artifact_paths(command: list[str], artifact_dir: Path) -> list[str]:
    """Replace planned artifact file URIs with temporary artifact paths."""

    resolved_command = []
    for argument in command:
        if argument.startswith("file://agent-factory/generated/"):
            filename = argument.rsplit("/", maxsplit=1)[-1]
            resolved_command.append(f"file://{artifact_dir / filename}")
        else:
            resolved_command.append(argument)
    return resolved_command


def _replace_placeholders(
    command: list[str], replacements: dict[str, str]
) -> list[str]:
    """Replace placeholder arguments or embedded placeholder text.

    Args:
        command: Planned command arguments.
        replacements: Placeholder values keyed by placeholder token.

    Returns:
        list[str]: Command arguments with placeholders replaced.
    """

    resolved_command = []
    for argument in command:
        resolved_argument = argument
        for placeholder, replacement in replacements.items():
            resolved_argument = resolved_argument.replace(placeholder, replacement)
        resolved_command.append(resolved_argument)
    return resolved_command


def _command(commands_by_step_id: dict[str, list[str]], step_id: str) -> list[str]:
    """Return the planned command for a step or raise a command error."""

    command = commands_by_step_id.get(step_id)
    if command is None:
        raise CommandExecutionError(step_id, f"No command planned for {step_id}.")
    return list(command)


def _extract_identifier(
    command_output: dict[str, Any], *, entity_type: str | None = None
) -> str | None:
    """Extract a resource identifier from OCI CLI JSON output.

    Args:
        command_output: OCI CLI JSON response.
        entity_type: Optional work-request resource entity type to prefer.

    Returns:
        str | None: Matching OCID, if one can be found.
    """

    if entity_type:
        resource_identifier = _extract_work_request_resource_identifier(
            command_output,
            entity_type=entity_type,
        )
        if resource_identifier:
            return resource_identifier
        prefixed_identifier = _extract_prefixed_identifier(
            command_output,
            prefix=ENTITY_OCID_PREFIXES.get(entity_type.upper()),
        )
        if prefixed_identifier:
            return prefixed_identifier

    for value in _walk_values(command_output):
        if isinstance(value, str) and value.startswith("ocid1."):
            return value
    return None


def _extract_work_request_resource_identifier(
    command_output: dict[str, Any], *, entity_type: str
) -> str | None:
    """Extract a matching resource identifier from OCI work-request output.

    Args:
        command_output: OCI CLI JSON response.
        entity_type: Expected resource entity type.

    Returns:
        str | None: Matching work-request resource identifier, if present.
    """

    resources = command_output.get("data", {}).get("resources", [])
    if not isinstance(resources, list):
        return None

    for resource in resources:
        if not isinstance(resource, dict):
            continue
        if str(resource.get("entity-type", "")).upper() != entity_type:
            continue
        identifier = resource.get("identifier")
        if isinstance(identifier, str) and identifier.startswith("ocid1."):
            return identifier
    return None


def _extract_prefixed_identifier(
    command_output: dict[str, Any], *, prefix: str | None
) -> str | None:
    """Extract the first OCID with the expected resource prefix.

    Args:
        command_output: OCI CLI JSON response.
        prefix: Expected OCI resource OCID prefix.

    Returns:
        str | None: Matching OCID, if present.
    """

    if not prefix:
        return None
    for value in _walk_values(command_output):
        if isinstance(value, str) and value.startswith(prefix):
            return value
    return None


def _find_endpoint_url(command_output: dict[str, Any]) -> str | None:
    """Find an endpoint URL in OCI CLI JSON output when one is present."""

    for key, value in _walk_items(command_output):
        normalized_key = key.lower().replace("-", "_")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            if "endpoint" in normalized_key or normalized_key.endswith("url"):
                return value
    return None


def _deployment_lifecycle_state(command_output: dict[str, Any]) -> str | None:
    """Return the normalized Hosted Deployment lifecycle state.

    Args:
        command_output: Parsed OCI CLI Hosted Deployment output.

    Returns:
        str | None: Upper-case lifecycle state when present.
    """

    data = command_output.get("data")
    if not isinstance(data, dict):
        return None
    state = _first_string(data, "lifecycle-state", "lifecycleState", "status")
    return state.upper() if state else None


def _build_invoke_url(*, region: str, hosted_application_id: str) -> str:
    """Build the deterministic Hosted Application invoke URL.

    Args:
        region: OCI region that hosts the application.
        hosted_application_id: Hosted Application OCID.

    Returns:
        str: Public invoke base URL.
    """

    return (
        f"https://inference.generativeai.{region}.oci.oraclecloud.com/"
        f"{HOSTED_APPLICATION_API_VERSION}/hostedApplications/"
        f"{hosted_application_id}/actions/invoke"
    )


def _deployment_wait_interval_seconds() -> float:
    """Return the Hosted Deployment readiness poll interval."""

    return _positive_float_from_env(
        env_var=DEPLOYMENT_WAIT_INTERVAL_ENV_VAR,
        default=DEFAULT_DEPLOYMENT_WAIT_INTERVAL_SECONDS,
    )


def _deployment_wait_timeout_seconds() -> float:
    """Return the Hosted Deployment readiness timeout."""

    return _positive_float_from_env(
        env_var=DEPLOYMENT_WAIT_TIMEOUT_ENV_VAR,
        default=DEFAULT_DEPLOYMENT_WAIT_TIMEOUT_SECONDS,
    )


def _positive_float_from_env(*, env_var: str, default: float) -> float:
    """Read a positive float environment variable.

    Args:
        env_var: Environment variable name.
        default: Default value when unset or invalid.

    Returns:
        float: Parsed positive value or default.
    """

    raw_value = os.environ.get(env_var)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _walk_values(value: Any) -> list[Any]:
    """Return nested JSON values in depth-first order."""

    if isinstance(value, dict):
        values: list[Any] = []
        for item in value.values():
            values.extend(_walk_values(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_walk_values(item))
        return values
    return [value]


def _walk_items(value: Any) -> list[tuple[str, Any]]:
    """Return nested JSON key-value pairs in depth-first order."""

    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key, item in value.items():
            items.append((str(key), item))
            items.extend(_walk_items(item))
        return items
    if isinstance(value, list):
        items = []
        for item in value:
            items.extend(_walk_items(item))
        return items
    return []


def _require_executable(executable: str, step_id: str) -> None:
    """Ensure a local executable exists before starting live command execution."""

    if shutil.which(executable) is None:
        raise CommandExecutionError(step_id, f"{executable} CLI is required.")


def _ensure_live_identifiers_resolved(resolved_identifiers: dict[str, str]) -> None:
    """Reject live deployments that still contain planning placeholders.

    Args:
        resolved_identifiers: Identifiers used by Hosted Application artifacts.

    Raises:
        CommandExecutionError: If a required live identifier is unresolved.
    """

    unresolved = {
        name: value
        for name, value in resolved_identifiers.items()
        if value.startswith("<") and value.endswith(">")
    }
    if unresolved:
        unresolved_names = ", ".join(sorted(unresolved))
        raise CommandExecutionError(
            "hosted-application",
            f"Live deployment has unresolved identifiers: {unresolved_names}.",
        )


def _repo_root() -> Path:
    """Return the repository root used as Docker build context."""

    return Path(os.environ.get("AGENT_FACTORY_REPO_ROOT", "/workspace")).resolve()


def _sanitize_text(text: str, secrets: list[str]) -> str:
    """Redact secret values from command output."""

    sanitized = text
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "********")
    return sanitized


def _step_id_from_command(command: list[str]) -> str:
    """Best-effort step identifier used when a lower-level command fails."""

    return command[0] if command else "command"
