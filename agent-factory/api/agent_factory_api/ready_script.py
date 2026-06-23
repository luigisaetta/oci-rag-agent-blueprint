"""
Author: L. Saetta
Date last modified: 2026-06-23
License: MIT
Description: Reviewable ready-to-run deployment script generation for Agent Factory.
"""

from __future__ import annotations

# pylint: disable=line-too-long

import json
from typing import Any

from agent_factory_api.commands import build_ocir_registry

OPENAI_API_KEY_MARKER = "__AGENT_FACTORY_OPENAI_API_KEY__"
OCIR_PASSWORD_MARKER = "__AGENT_FACTORY_OCIR_PASSWORD__"
LANGFUSE_SECRET_KEY_MARKER = "__AGENT_FACTORY_LANGFUSE_SECRET_KEY__"


def build_ready_to_run_script(payload: dict[str, Any]) -> str:
    """Build a Linux-first Bash script for a live Agent Factory deployment.

    The generated script keeps Docker commands, OCI CLI commands, and OCI CLI
    JSON artifacts visible for administrator review. Python helpers are used
    only for SDK-based foundation provisioning and tested OCI response parsing.

    Args:
        payload: Validated Agent Factory deployment payload.

    Returns:
        str: Bash script that runs the live deployment workflow.
    """

    script_payload = _script_payload(payload)
    payload_json = json.dumps(script_payload, indent=2, sort_keys=True)
    inbound_auth_config = json.dumps(_build_inbound_auth_config(payload), indent=2)
    networking_config = json.dumps(_build_networking_config(), indent=2)
    ocir_registry = build_ocir_registry(payload)

    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "# Agent Factory ready-to-run deployment script.",
            "# This script creates OCI resources when executed.",
            "# Target platform: Linux. macOS Bash is supported on a best-effort basis.",
            "",
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'if [ -n "${AGENT_FACTORY_REPO_ROOT:-}" ]; then',
            '  REPO_ROOT="${AGENT_FACTORY_REPO_ROOT}"',
            'elif [ -d "${PWD}/agent-factory/api/agent_factory_api" ]; then',
            '  REPO_ROOT="${PWD}"',
            "else",
            '  REPO_ROOT="${SCRIPT_DIR}"',
            "fi",
            "",
            'if [ ! -d "${REPO_ROOT}/agent-factory/api/agent_factory_api" ]; then',
            '  echo "Unable to find Agent Factory sources under ${REPO_ROOT}." >&2',
            '  echo "Set AGENT_FACTORY_REPO_ROOT to the repository root and retry." >&2',
            "  exit 2",
            "fi",
            "",
            'if [ -n "${PYTHON_BIN:-}" ]; then',
            '  PYTHON_EXECUTABLE="${PYTHON_BIN}"',
            "elif command -v python3 >/dev/null 2>&1; then",
            '  PYTHON_EXECUTABLE="$(command -v python3)"',
            "elif command -v python >/dev/null 2>&1; then",
            '  PYTHON_EXECUTABLE="$(command -v python)"',
            "else",
            '  echo "python3 or python is required." >&2',
            "  exit 2",
            "fi",
            "",
            'if [ -z "${OPENAI_API_KEY:-}" ]; then',
            '  printf "OPENAI_API_KEY: " >&2',
            "  read -r -s OPENAI_API_KEY",
            '  printf "\\n" >&2',
            "fi",
            "",
            'if [ -z "${OCIR_PASSWORD:-}" ]; then',
            '  printf "OCIR_PASSWORD: " >&2',
            "  read -r -s OCIR_PASSWORD",
            '  printf "\\n" >&2',
            "fi",
            "",
            'WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-factory-deploy.XXXXXX")"',
            'cleanup() { rm -rf "${WORK_DIR}"; }',
            "trap cleanup EXIT",
            "",
            'PAYLOAD_FILE="${WORK_DIR}/payload.json"',
            'METADATA_FILE="${WORK_DIR}/metadata.json"',
            'ARTIFACT_DIR="${WORK_DIR}/artifacts"',
            'mkdir -p "${ARTIFACT_DIR}"',
            "",
            "cat > \"${PAYLOAD_FILE}\" <<'JSON'",
            payload_json,
            "JSON",
            "",
            'export PYTHONPATH="${REPO_ROOT}/agent-factory/api${PYTHONPATH:+:${PYTHONPATH}}"',
            "",
            "json_value() {",
            '  "${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner json-value \\',
            '    --input "${METADATA_FILE}" --path "$1"',
            "}",
            "",
            "json_string() {",
            '  "${PYTHON_EXECUTABLE}" -c \'import json, sys; print(json.dumps(sys.argv[1]))\' "$1"',
            "}",
            "",
            "extract_id() {",
            '  "${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner extract-id \\',
            '    --input "$1" --entity-type "$2"',
            "}",
            "",
            "run_command() {",
            '  printf "+ "',
            '  printf "%q " "$@"',
            '  printf "\\n"',
            '  "$@"',
            "}",
            "",
            "run_json_command() {",
            '  output_file="$1"',
            "  shift",
            '  printf "+ "',
            '  printf "%q " "$@"',
            '  printf "\\n"',
            '  "$@" | tee "${output_file}"',
            "}",
            "",
            "# Step 1: provision or resolve SDK-managed foundation resources.",
            "# Docker and OCI CLI commands remain explicit below.",
            'OPENAI_API_KEY="${OPENAI_API_KEY}" \\',
            'OCIR_PASSWORD="${OCIR_PASSWORD}" \\',
            'LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}" \\',
            '"${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner prepare \\',
            '  --payload "${PAYLOAD_FILE}" \\',
            '  --metadata "${METADATA_FILE}"',
            "",
            'REGION="$(json_value region)"',
            'COMPARTMENT_ID="$(json_value compartment_id)"',
            'PROJECT_ID="$(json_value genai_project_id)"',
            'VECTOR_STORE_ID="$(json_value vector_store_id)"',
            f'OCIR_REGISTRY="{ocir_registry}"',
            'OCIR_USERNAME="$(json_value ocir_username)"',
            'IMAGE_REFERENCE="$(json_value image_reference)"',
            'CONTAINER_REPOSITORY_NAME="$(json_value container_repository_name)"',
            'HOSTED_APPLICATION_NAME="$(json_value hosted_application_name)"',
            'DEPLOYMENT_NAME="$(json_value deployment_name)"',
            'ACTIVE_ARTIFACT_CONTAINER_URI="$(json_value active_artifact_container_uri)"',
            'ACTIVE_ARTIFACT_TAG="$(json_value active_artifact_tag)"',
            'FILE_SEARCH_MAX_NUM_RESULTS="$(json_value file_search_max_num_results)"',
            'RESPONSES_TIMEOUT_SECONDS="$(json_value responses_timeout_seconds)"',
            'STREAM_FINALIZATION_MODE="$(json_value stream_finalization_mode)"',
            'LANGFUSE_ENABLED="$(json_value langfuse_enabled)"',
            'LANGFUSE_BASE_URL="$(json_value langfuse_base_url)"',
            'LANGFUSE_PUBLIC_KEY="$(json_value langfuse_public_key)"',
            'LANGFUSE_SECRET_KEY_VALUE="${LANGFUSE_SECRET_KEY:-}"',
            'MODEL_ID="$(json_value model_id)"',
            "",
            'INBOUND_AUTH_CONFIG="${ARTIFACT_DIR}/hosted-application-inbound-auth-config.json"',
            'NETWORKING_CONFIG="${ARTIFACT_DIR}/hosted-application-networking-config.json"',
            'ENVIRONMENT_VARIABLES="${ARTIFACT_DIR}/hosted-application-environment-variables.json"',
            'ACTIVE_ARTIFACT="${ARTIFACT_DIR}/hosted-deployment-active-artifact.json"',
            "",
            "# JSON artifact: Hosted Application inbound authentication config.",
            "cat > \"${INBOUND_AUTH_CONFIG}\" <<'JSON'",
            inbound_auth_config,
            "JSON",
            "",
            "# JSON artifact: Hosted Application networking config.",
            "cat > \"${NETWORKING_CONFIG}\" <<'JSON'",
            networking_config,
            "JSON",
            "",
            "# JSON artifact: Hosted Application runtime environment variables.",
            "# OPENAI_API_KEY and optional LANGFUSE_SECRET_KEY are inserted from the runtime environment.",
            'cat > "${ENVIRONMENT_VARIABLES}" <<JSON',
            "[",
            '  {"name": "OCI_REGION", "type": "PLAINTEXT", "value": $(json_string "${REGION}")},',
            '  {"name": "OCI_COMPARTMENT_ID", "type": "PLAINTEXT", "value": $(json_string "${COMPARTMENT_ID}")},',
            '  {"name": "OCI_PROJECT_ID", "type": "PLAINTEXT", "value": $(json_string "${PROJECT_ID}")},',
            '  {"name": "OCI_MODEL_ID", "type": "PLAINTEXT", "value": $(json_string "${MODEL_ID}")},',
            '  {"name": "OCI_VECTOR_STORE_ID", "type": "PLAINTEXT", "value": $(json_string "${VECTOR_STORE_ID}")},',
            '  {"name": "OPENAI_API_KEY", "type": "PLAINTEXT", "value": $(json_string "${OPENAI_API_KEY}")},',
            '  {"name": "FILE_SEARCH_MAX_NUM_RESULTS", "type": "PLAINTEXT", "value": $(json_string "${FILE_SEARCH_MAX_NUM_RESULTS}")},',
            '  {"name": "RESPONSES_TIMEOUT_SECONDS", "type": "PLAINTEXT", "value": $(json_string "${RESPONSES_TIMEOUT_SECONDS}")},',
            '  {"name": "STREAM_FINALIZATION_MODE", "type": "PLAINTEXT", "value": $(json_string "${STREAM_FINALIZATION_MODE}")}',
            "]",
            "JSON",
            'if [ "${LANGFUSE_ENABLED}" = "True" ] || [ "${LANGFUSE_ENABLED}" = "true" ]; then',
            '  "${PYTHON_EXECUTABLE}" - "${ENVIRONMENT_VARIABLES}" "${LANGFUSE_BASE_URL}" "${LANGFUSE_PUBLIC_KEY}" "${LANGFUSE_SECRET_KEY_VALUE}" <<\'PY\'',
            "import json",
            "import sys",
            "",
            "path = sys.argv[1]",
            "with open(path, encoding='utf-8') as handle:",
            "    data = json.load(handle)",
            "data.extend(",
            "    [",
            "        {'name': 'LANGFUSE_ENABLED', 'type': 'PLAINTEXT', 'value': 'true'},",
            "        {'name': 'LANGFUSE_BASE_URL', 'type': 'PLAINTEXT', 'value': sys.argv[2]},",
            "        {'name': 'LANGFUSE_PUBLIC_KEY', 'type': 'PLAINTEXT', 'value': sys.argv[3]},",
            "        {'name': 'LANGFUSE_SECRET_KEY', 'type': 'PLAINTEXT', 'value': sys.argv[4]},",
            "    ]",
            ")",
            "with open(path, 'w', encoding='utf-8') as handle:",
            "    json.dump(data, handle, indent=2)",
            "PY",
            "fi",
            "",
            "# JSON artifact: Hosted Deployment active Docker artifact.",
            'cat > "${ACTIVE_ARTIFACT}" <<JSON',
            "{",
            '  "artifactType": "SIMPLE_DOCKER_ARTIFACT",',
            '  "containerUri": $(json_string "${ACTIVE_ARTIFACT_CONTAINER_URI}"),',
            '  "tag": $(json_string "${ACTIVE_ARTIFACT_TAG}")',
            "}",
            "JSON",
            "",
            "# Docker command: build the RAG agent backend image.",
            'cd "${REPO_ROOT}"',
            'run_command docker build --platform linux/amd64 -t "${IMAGE_REFERENCE}" -f Dockerfile .',
            "",
            "# OCI CLI command: create or reuse the OCIR repository.",
            'REGISTRY_OUTPUT="${WORK_DIR}/registry-create.json"',
            'REGISTRY_ERROR="${WORK_DIR}/registry-create.err"',
            'printf "+ oci --region %q --output json artifacts container repository create --display-name %q --compartment-id %q\\n" "${REGION}" "${CONTAINER_REPOSITORY_NAME}" "${COMPARTMENT_ID}"',
            "set +e",
            'oci --region "${REGION}" --output json artifacts container repository create \\',
            '  --display-name "${CONTAINER_REPOSITORY_NAME}" \\',
            '  --compartment-id "${COMPARTMENT_ID}" \\',
            '  >"${REGISTRY_OUTPUT}" 2>"${REGISTRY_ERROR}"',
            "REGISTRY_STATUS=$?",
            "set -e",
            'if [ "${REGISTRY_STATUS}" -ne 0 ]; then',
            '  if grep -qi "repository already exists" "${REGISTRY_ERROR}" || grep -qi "namespace_conflict" "${REGISTRY_ERROR}"; then',
            '    echo "OCI Container Registry repository already exists; reusing it."',
            "  else",
            '    cat "${REGISTRY_ERROR}" >&2',
            "    exit ${REGISTRY_STATUS}",
            "  fi",
            "fi",
            "",
            "# Docker command: authenticate to OCIR without putting the password in argv.",
            'printf "+ docker login %q --username %q --password-stdin\\n" "${OCIR_REGISTRY}" "${OCIR_USERNAME}"',
            'printf "%s\\n" "${OCIR_PASSWORD}" | docker login "${OCIR_REGISTRY}" --username "${OCIR_USERNAME}" --password-stdin',
            "",
            "# Docker command: push the image to OCIR.",
            'run_command docker push "${IMAGE_REFERENCE}"',
            "",
            "# OCI CLI command: list Hosted Applications for reuse by display name.",
            'HOSTED_APPLICATION_LIST_OUTPUT="${WORK_DIR}/hosted-applications.json"',
            'run_json_command "${HOSTED_APPLICATION_LIST_OUTPUT}" \\',
            '  oci --region "${REGION}" --output json generative-ai hosted-application-collection list-hosted-applications \\',
            '    --compartment-id "${COMPARTMENT_ID}" --all',
            'HOSTED_APPLICATION_ID="$("${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner find-hosted-application \\',
            '  --input "${HOSTED_APPLICATION_LIST_OUTPUT}" --display-name "${HOSTED_APPLICATION_NAME}")"',
            "",
            'if [ -n "${HOSTED_APPLICATION_ID}" ]; then',
            '  echo "Reusing Hosted Application ${HOSTED_APPLICATION_ID}"',
            "else",
            "  # OCI CLI command: create the Hosted Application with JSON artifact files.",
            '  HOSTED_APPLICATION_OUTPUT="${WORK_DIR}/hosted-application-create.json"',
            '  run_json_command "${HOSTED_APPLICATION_OUTPUT}" \\',
            '    oci --region "${REGION}" --output json generative-ai hosted-application create \\',
            '      --display-name "${HOSTED_APPLICATION_NAME}" \\',
            '      --compartment-id "${COMPARTMENT_ID}" \\',
            '      --inbound-auth-config "file://${INBOUND_AUTH_CONFIG}" \\',
            '      --networking-config "file://${NETWORKING_CONFIG}" \\',
            '      --environment-variables "file://${ENVIRONMENT_VARIABLES}" \\',
            "      --wait-for-state SUCCEEDED",
            '  HOSTED_APPLICATION_ID="$(extract_id "${HOSTED_APPLICATION_OUTPUT}" HOSTED_APPLICATION)"',
            "fi",
            "",
            'if [ -z "${HOSTED_APPLICATION_ID}" ]; then',
            '  echo "Unable to determine Hosted Application OCID." >&2',
            "  exit 1",
            "fi",
            "",
            "# OCI CLI command: create the Hosted Deployment from the Docker artifact.",
            'HOSTED_DEPLOYMENT_OUTPUT="${WORK_DIR}/hosted-deployment-create.json"',
            'run_json_command "${HOSTED_DEPLOYMENT_OUTPUT}" \\',
            '  oci --region "${REGION}" --output json generative-ai hosted-deployment create-hosted-deployment-single-docker-artifact \\',
            '    --hosted-application-id "${HOSTED_APPLICATION_ID}" \\',
            '    --active-artifact-container-uri "${ACTIVE_ARTIFACT_CONTAINER_URI}" \\',
            '    --active-artifact-tag "${ACTIVE_ARTIFACT_TAG}" \\',
            '    --display-name "${DEPLOYMENT_NAME}" \\',
            '    --compartment-id "${COMPARTMENT_ID}" \\',
            "    --wait-for-state SUCCEEDED",
            'HOSTED_DEPLOYMENT_ID="$(extract_id "${HOSTED_DEPLOYMENT_OUTPUT}" HOSTED_DEPLOYMENT)"',
            "",
            'if [ -z "${HOSTED_DEPLOYMENT_ID}" ]; then',
            '  echo "Unable to determine Hosted Deployment OCID." >&2',
            "  exit 1",
            "fi",
            "",
            "# OCI CLI command: poll Hosted Deployment readiness.",
            'READINESS_OUTPUT="${WORK_DIR}/hosted-deployment-readiness.json"',
            'DEPLOYMENT_WAIT_TIMEOUT_SECONDS="${AGENT_FACTORY_DEPLOYMENT_WAIT_TIMEOUT_SECONDS:-900}"',
            'DEPLOYMENT_WAIT_INTERVAL_SECONDS="${AGENT_FACTORY_DEPLOYMENT_WAIT_INTERVAL_SECONDS:-15}"',
            'DEADLINE="$(( $(date +%s) + DEPLOYMENT_WAIT_TIMEOUT_SECONDS ))"',
            "while true; do",
            '  run_json_command "${READINESS_OUTPUT}" \\',
            '    oci --region "${REGION}" --output json generative-ai hosted-deployment get \\',
            '      --hosted-deployment-id "${HOSTED_DEPLOYMENT_ID}"',
            '  DEPLOYMENT_STATE="$("${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner lifecycle-state --input "${READINESS_OUTPUT}")"',
            '  ENDPOINT_URL="$("${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner endpoint-url \\',
            '    --input "${READINESS_OUTPUT}" --region "${REGION}" --hosted-application-id "${HOSTED_APPLICATION_ID}")"',
            '  if [ "${DEPLOYMENT_STATE}" = "ACTIVE" ] || [ "${DEPLOYMENT_STATE}" = "SUCCEEDED" ] || [ -n "${ENDPOINT_URL}" ]; then',
            "    break",
            "  fi",
            '  if [ "${DEPLOYMENT_STATE}" = "FAILED" ] || [ "${DEPLOYMENT_STATE}" = "CANCELED" ] || [ "${DEPLOYMENT_STATE}" = "DELETED" ]; then',
            '    echo "Hosted Deployment entered failed state ${DEPLOYMENT_STATE}." >&2',
            "    exit 1",
            "  fi",
            '  if [ "$(date +%s)" -ge "${DEADLINE}" ]; then',
            '    echo "Hosted Deployment was not ready before timeout. Last state: ${DEPLOYMENT_STATE:-UNKNOWN}." >&2',
            "    exit 1",
            "  fi",
            '  sleep "${DEPLOYMENT_WAIT_INTERVAL_SECONDS}"',
            "done",
            "",
            "# Health command: validate the deployed /health endpoint.",
            'run_command "${PYTHON_EXECUTABLE}" -c \\',
            "  'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=30).read()' \\",
            '  "${ENDPOINT_URL%/}/health"',
            "",
            "cat <<SUMMARY",
            "Deployment completed.",
            "Hosted Application ID: ${HOSTED_APPLICATION_ID}",
            "Hosted Deployment ID: ${HOSTED_DEPLOYMENT_ID}",
            "Invoke URL: ${ENDPOINT_URL}",
            "Health URL: ${ENDPOINT_URL%/}/health",
            "Responses URL: ${ENDPOINT_URL%/}/responses",
            "Artifact directory used during execution: ${ARTIFACT_DIR}",
            "SUMMARY",
            "",
        ]
    )


def _script_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a payload copy safe to embed in a generated shell script.

    Args:
        payload: Validated Agent Factory deployment payload.

    Returns:
        dict[str, Any]: Payload with runtime secret markers.
    """

    script_payload = dict(payload)
    script_payload["dry_run"] = False
    script_payload["openai_api_key"] = OPENAI_API_KEY_MARKER
    script_payload["ocir_password"] = OCIR_PASSWORD_MARKER
    if script_payload.get("langfuse_enabled"):
        script_payload["langfuse_secret_key"] = LANGFUSE_SECRET_KEY_MARKER
    script_payload["confidential_application_secret"] = ""
    return script_payload


def _build_inbound_auth_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the Hosted Application inbound authentication config.

    Args:
        payload: Validated deployment payload.

    Returns:
        dict[str, Any]: Hosted Application inbound auth JSON content.
    """

    if not payload.get("jwt_protection_enabled"):
        return {"inboundAuthConfigType": "NO_AUTH_CONFIG"}
    return {
        "inboundAuthConfigType": "IDCS_AUTH_CONFIG",
        "idcsConfig": {
            "domainUrl": str(payload["identity_domain_url"]).rstrip("/"),
            "scope": str(payload["auth_scope"]),
            "audience": str(payload["auth_audience"]),
        },
    }


def _build_networking_config() -> dict[str, Any]:
    """Return the first implementation's public managed networking config.

    Returns:
        dict[str, Any]: Hosted Application networking JSON content.
    """

    return {
        "inboundNetworkingConfig": {
            "endpointMode": "PUBLIC",
        },
        "outboundNetworkingConfig": {
            "networkMode": "MANAGED",
        },
    }
