"""
Author: L. Saetta
Date last modified: 2026-06-23
License: MIT
Description: Helper commands for exported Agent Factory deployment scripts.
"""

from __future__ import annotations

# pylint: disable=protected-access,too-many-return-statements

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_factory_api.app import (
    _build_run_outputs,
    _build_steps,
    _commands_by_step_id,
)
from agent_factory_api.commands import build_deployment_plan, build_ocir_registry
from agent_factory_api.executor import (
    CommandExecutionError,
    _build_invoke_url,
    _deployment_lifecycle_state,
    execute_live_deployment_commands,
    _extract_identifier,
    _extract_list_items,
    _find_endpoint_url,
    _first_string,
    _is_deleted_hosted_application,
    _load_json_output,
)
from agent_factory_api.models import validate_deployment_payload
from agent_factory_api.ready_script import (
    LANGFUSE_SECRET_KEY_MARKER,
    OCIR_PASSWORD_MARKER,
    OPENAI_API_KEY_MARKER,
)
from agent_factory_api.resources import (
    ResourceProvisioningError,
    provision_foundation_resources,
)

SECRET_MARKERS = {
    "openai_api_key": (OPENAI_API_KEY_MARKER, "OPENAI_API_KEY"),
    "ocir_password": (OCIR_PASSWORD_MARKER, "OCIR_PASSWORD"),
    "langfuse_secret_key": (LANGFUSE_SECRET_KEY_MARKER, "LANGFUSE_SECRET_KEY"),
}


def main(argv: list[str] | None = None) -> int:
    """Run a helper command for an exported deployment script.

    Args:
        argv: Optional command-line arguments.

    Returns:
        int: Process exit code.
    """

    args = _parse_args(argv)
    try:
        if args.command == "prepare":
            _prepare_metadata(args.payload, args.metadata)
            return 0
        if args.command == "json-value":
            print(_json_value(args.input, args.path))
            return 0
        if args.command == "extract-id":
            extracted_id = _extract_id(args.input, args.entity_type)
            if extracted_id:
                print(extracted_id)
            return 0
        if args.command == "find-hosted-application":
            hosted_application_id = _find_hosted_application_id(
                args.input,
                args.display_name,
            )
            if hosted_application_id:
                print(hosted_application_id)
            return 0
        if args.command == "lifecycle-state":
            lifecycle_state = _lifecycle_state(args.input)
            if lifecycle_state:
                print(lifecycle_state)
            return 0
        if args.command == "endpoint-url":
            print(
                _endpoint_url(
                    args.input,
                    region=args.region,
                    hosted_application_id=args.hosted_application_id,
                )
            )
            return 0
    except (
        OSError,
        ValueError,
        ResourceProvisioningError,
        CommandExecutionError,
    ) as exc:
        _print_error(str(exc))
        return 1

    _print_error(f"Unsupported command: {args.command}")
    return 2


def run_ready_deployment(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute the live deployment workflow used by exported scripts.

    Args:
        payload: Validated live deployment payload.

    Returns:
        dict[str, Any]: Non-secret deployment outputs.

    Raises:
        ResourceProvisioningError: If foundation resource provisioning fails.
        CommandExecutionError: If a Docker, OCIR, or Hosted Application command
            fails.
    """

    resource_result = provision_foundation_resources(
        payload,
        progress_callback=_print_progress,
    )
    plan_payload = dict(payload)
    plan_payload["compartment"] = resource_result.compartment_id
    plan_payload["genai_project"] = resource_result.project.project_id
    plan_payload["object_storage_namespace"] = resource_result.bucket.namespace_name
    plan_payload["vector_store_name"] = resource_result.vector_store.vector_store_id
    if resource_result.connector is not None:
        plan_payload["connector_name"] = resource_result.connector.connector_id

    plan = build_deployment_plan(plan_payload, dry_run=False)
    steps = _build_steps(plan_payload, plan["commands"])
    execution_outputs = execute_live_deployment_commands(
        plan_payload,
        _commands_by_step_id(steps),
        _print_progress,
    )
    return _build_run_outputs(
        plan_payload=plan_payload,
        plan=plan,
        resource_result=resource_result,
        dry_run=False,
        execution_outputs=execution_outputs,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments.
    """

    parser = argparse.ArgumentParser(
        description="Helper commands for exported Agent Factory deployment scripts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Provision foundation resources and write resolved deployment metadata.",
    )
    prepare_parser.add_argument(
        "--payload",
        required=True,
        help="Path to the JSON deployment payload generated by the shell script.",
    )
    prepare_parser.add_argument(
        "--metadata",
        required=True,
        help="Path where resolved non-secret deployment metadata will be written.",
    )

    json_value_parser = subparsers.add_parser(
        "json-value",
        help="Print a top-level scalar value from a JSON file.",
    )
    json_value_parser.add_argument("--input", required=True, help="Input JSON file.")
    json_value_parser.add_argument("--path", required=True, help="Top-level key.")

    extract_parser = subparsers.add_parser(
        "extract-id",
        help="Extract a Hosted Application or Hosted Deployment OCID from OCI output.",
    )
    extract_parser.add_argument("--input", required=True, help="Input OCI JSON file.")
    extract_parser.add_argument(
        "--entity-type",
        required=True,
        choices=["HOSTED_APPLICATION", "HOSTED_DEPLOYMENT"],
        help="OCI work-request entity type to prefer.",
    )

    find_parser = subparsers.add_parser(
        "find-hosted-application",
        help="Find a reusable Hosted Application OCID by display name.",
    )
    find_parser.add_argument("--input", required=True, help="Hosted Application list.")
    find_parser.add_argument("--display-name", required=True, help="Display name.")

    lifecycle_parser = subparsers.add_parser(
        "lifecycle-state",
        help="Print a Hosted Deployment lifecycle state from OCI output.",
    )
    lifecycle_parser.add_argument("--input", required=True, help="Input OCI JSON file.")

    endpoint_parser = subparsers.add_parser(
        "endpoint-url",
        help="Print the deployment endpoint URL or deterministic invoke URL.",
    )
    endpoint_parser.add_argument("--input", required=True, help="Input OCI JSON file.")
    endpoint_parser.add_argument("--region", required=True, help="OCI region.")
    endpoint_parser.add_argument(
        "--hosted-application-id",
        required=True,
        help="Hosted Application OCID.",
    )
    return parser.parse_args(argv)


def _prepare_metadata(payload_path: str, metadata_path: str) -> None:
    """Provision foundation resources and write deployment metadata.

    Args:
        payload_path: Generated payload JSON path.
        metadata_path: Metadata output JSON path.

    Raises:
        ValueError: If deployment input validation fails.
        ResourceProvisioningError: If foundation provisioning fails.
    """

    raw_payload = _load_payload(payload_path)
    resolved_payload = _resolve_secret_markers(raw_payload)
    validation = validate_deployment_payload(resolved_payload)
    if validation.errors:
        raise ValueError(
            "Deployment input validation failed: "
            f"{json.dumps(validation.errors, sort_keys=True)}"
        )

    assert validation.payload is not None
    payload = dict(validation.payload)
    payload["dry_run"] = False

    resource_result = provision_foundation_resources(
        payload,
        progress_callback=_print_progress,
    )
    plan_payload = dict(payload)
    plan_payload["compartment"] = resource_result.compartment_id
    plan_payload["genai_project"] = resource_result.project.project_id
    plan_payload["object_storage_namespace"] = resource_result.bucket.namespace_name
    plan_payload["vector_store_name"] = resource_result.vector_store.vector_store_id
    if resource_result.connector is not None:
        plan_payload["connector_name"] = resource_result.connector.connector_id

    plan = build_deployment_plan(plan_payload, dry_run=False)
    deployment_artifact = plan["artifacts"]["create-hosted-deployment.json"]
    metadata = {
        "region": plan_payload["region"],
        "compartment_id": resource_result.compartment_id,
        "genai_project_id": resource_result.project.project_id,
        "vector_store_id": resource_result.vector_store.vector_store_id,
        "model_id": plan_payload["model_id"],
        "file_search_max_num_results": str(plan_payload["file_search_max_num_results"]),
        "responses_timeout_seconds": str(plan_payload["responses_timeout_seconds"]),
        "stream_finalization_mode": plan_payload["stream_finalization_mode"],
        "langfuse_enabled": bool(plan_payload["langfuse_enabled"]),
        "langfuse_base_url": plan_payload["langfuse_base_url"],
        "langfuse_public_key": plan_payload["langfuse_public_key"],
        "image_reference": plan["image_reference"],
        "ocir_registry": build_ocir_registry(plan_payload),
        "ocir_username": plan_payload["ocir_username"],
        "container_repository_name": plan_payload["container_repository_name"],
        "hosted_application_name": plan_payload["hosted_application_name"],
        "deployment_name": plan_payload["deployment_name"],
        "active_artifact_container_uri": deployment_artifact["containerUri"],
        "active_artifact_tag": deployment_artifact["artifactTag"],
        "foundation_resources": {
            "bucket": {
                "bucket_name": resource_result.bucket.bucket_name,
                "namespace_name": resource_result.bucket.namespace_name,
                "created": resource_result.bucket.created,
            },
            "vector_store": {
                "vector_store_id": resource_result.vector_store.vector_store_id,
                "name": resource_result.vector_store.name,
                "created": resource_result.vector_store.created,
            },
            "connector": (
                None
                if resource_result.connector is None
                else {
                    "connector_id": resource_result.connector.connector_id,
                    "name": resource_result.connector.name,
                    "created": resource_result.connector.created,
                    "skipped": resource_result.connector.skipped,
                }
            ),
        },
    }
    Path(metadata_path).write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_payload(payload_path: str) -> dict[str, Any]:
    """Load a deployment payload from disk.

    Args:
        payload_path: JSON payload file path.

    Returns:
        dict[str, Any]: Loaded payload.

    Raises:
        ValueError: If the payload is not a JSON object.
    """

    with Path(payload_path).open("r", encoding="utf-8") as payload_file:
        payload = json.load(payload_file)
    if not isinstance(payload, dict):
        raise ValueError("Deployment payload must be a JSON object.")
    return payload


def _json_value(input_path: str, path: str) -> str:
    """Return a top-level JSON scalar as text.

    Args:
        input_path: JSON file path.
        path: Top-level key to read.

    Returns:
        str: Scalar value converted to text.

    Raises:
        ValueError: If the value is missing or not scalar.
    """

    content = _load_json_file(input_path)
    value = content.get(path)
    if value is None or isinstance(value, (dict, list)):
        raise ValueError(f"Metadata value is not a scalar: {path}")
    return str(value)


def _extract_id(input_path: str, entity_type: str) -> str:
    """Extract an OCID from OCI CLI JSON output.

    Args:
        input_path: OCI CLI output file path.
        entity_type: Work-request entity type to prefer.

    Returns:
        str: Extracted OCID or an empty string.
    """

    return (
        _extract_identifier(
            _load_json_file(input_path),
            entity_type=entity_type,
        )
        or ""
    )


def _find_hosted_application_id(input_path: str, display_name: str) -> str:
    """Find a reusable Hosted Application OCID in list output.

    Args:
        input_path: Hosted Application list output file path.
        display_name: Requested Hosted Application display name.

    Returns:
        str: Hosted Application OCID or an empty string.
    """

    output = _load_json_file(input_path)
    matches = [
        item
        for item in _extract_list_items(output)
        if _first_string(item, "display-name", "displayName", "name") == display_name
        and _first_string(item, "id")
        and not _is_deleted_hosted_application(item)
    ]
    if not matches:
        return ""
    return _first_string(matches[0], "id")


def _lifecycle_state(input_path: str) -> str:
    """Return a Hosted Deployment lifecycle state.

    Args:
        input_path: Hosted Deployment get output file path.

    Returns:
        str: Lifecycle state or an empty string.
    """

    return _deployment_lifecycle_state(_load_json_file(input_path)) or ""


def _endpoint_url(input_path: str, *, region: str, hosted_application_id: str) -> str:
    """Return the endpoint URL from OCI output or deterministic invoke URL.

    Args:
        input_path: Hosted Deployment get output file path.
        region: OCI region.
        hosted_application_id: Hosted Application OCID.

    Returns:
        str: Endpoint URL.
    """

    output = _load_json_file(input_path)
    return _find_endpoint_url(output) or _build_invoke_url(
        region=region,
        hosted_application_id=hosted_application_id,
    )


def _load_json_file(input_path: str) -> dict[str, Any]:
    """Load an OCI CLI JSON object from a file.

    Args:
        input_path: JSON file path.

    Returns:
        dict[str, Any]: Parsed JSON object.

    Raises:
        CommandExecutionError: If the file does not contain a JSON object.
    """

    text = Path(input_path).read_text(encoding="utf-8")
    result = subprocess.CompletedProcess(["read-json-file"], 0, stdout=text, stderr="")
    return _load_json_output("read-json-file", result, secrets=[])


def _resolve_secret_markers(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace generated secret markers with runtime environment values.

    Args:
        payload: Payload loaded from the generated script.

    Returns:
        dict[str, Any]: Payload with secrets restored from environment values.

    Raises:
        ValueError: If a required secret environment variable is missing.
    """

    resolved_payload = dict(payload)
    for field_name, (marker, environment_name) in SECRET_MARKERS.items():
        if resolved_payload.get(field_name) != marker:
            continue
        secret_value = os.environ.get(environment_name)
        if not secret_value:
            raise ValueError(f"{environment_name} is required.")
        resolved_payload[field_name] = secret_value
    return resolved_payload


def _print_progress(
    step_id: str, status: str, outputs: dict[str, Any] | None = None
) -> None:
    """Print a human-readable progress line to standard error.

    Args:
        step_id: Workflow step identifier.
        status: Step status.
        outputs: Optional non-secret step outputs.
    """

    suffix = f" {json.dumps(outputs, sort_keys=True)}" if outputs else ""
    print(f"[{step_id}] {status}{suffix}", file=sys.stderr)


def _print_error(message: str, details: dict[str, str] | None = None) -> None:
    """Print an error message to standard error.

    Args:
        message: Error message.
        details: Optional field-level validation details.
    """

    print(f"ERROR: {message}", file=sys.stderr)
    if details:
        print(json.dumps(details, indent=2, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
