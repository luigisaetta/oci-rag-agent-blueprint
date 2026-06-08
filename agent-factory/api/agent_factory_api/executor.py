"""
Author: L. Saetta
Date last modified: 2026-06-08
License: MIT
Description: Live command execution helpers for Agent Factory deployments.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from agent_factory_api.commands import (
    build_agent_runtime_environment,
    build_hosted_application_artifacts,
    build_ocir_registry,
    build_resolved_identifiers,
)

ProgressCallback = Callable[[str, str, dict[str, Any] | None], None]


class CommandExecutionError(RuntimeError):
    """Raised when a live deployment command fails."""

    def __init__(self, step_id: str, message: str) -> None:
        """Initialize the command execution error.

        Args:
            step_id: Workflow step that failed.
            message: Sanitized failure message.
        """

        super().__init__(message)
        self.step_id = step_id


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

        readiness_output = _run_json_step(
            "deployment-readiness",
            _replace_placeholders(
                _command(commands_by_step_id, "deployment-readiness"),
                {"<hosted-deployment-ocid>": hosted_deployment_id},
            ),
            progress_callback,
            cwd=repo_root,
            secrets=[str(payload["ocir_password"]), str(payload["openai_api_key"])],
        )
        endpoint_url = _find_endpoint_url(readiness_output)
        if endpoint_url:
            outputs["endpoint_url"] = endpoint_url
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
        else:
            progress_callback(
                "health",
                "skipped",
                {
                    "reason": "Deployment readiness output did not include an endpoint URL."
                },
            )

    return outputs


def _run_step(  # pylint: disable=too-many-arguments
    step_id: str,
    command: list[str],
    progress_callback: ProgressCallback,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    secrets: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and update progress for one workflow step."""

    progress_callback(step_id, "running", None)
    result = _run_command(command, cwd=cwd, env=env, secrets=secrets)
    progress_callback(step_id, "succeeded", _command_outputs(result, secrets or []))
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
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise CommandExecutionError(
            step_id,
            f"{step_id} did not return valid JSON.",
        ) from exc


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
    """Replace placeholder arguments in a planned command."""

    return [replacements.get(argument, argument) for argument in command]


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


def _find_endpoint_url(command_output: dict[str, Any]) -> str | None:
    """Find an endpoint URL in OCI CLI JSON output when one is present."""

    for key, value in _walk_items(command_output):
        normalized_key = key.lower().replace("-", "_")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            if "endpoint" in normalized_key or normalized_key.endswith("url"):
                return value
    return None


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
