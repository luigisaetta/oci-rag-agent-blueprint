"""
Author: L. Saetta
Date last modified: 2026-06-22
License: MIT
Description: Ready-to-run deployment script generation for Agent Factory.
"""

from __future__ import annotations

import json
from typing import Any

OPENAI_API_KEY_MARKER = "__AGENT_FACTORY_OPENAI_API_KEY__"
OCIR_PASSWORD_MARKER = "__AGENT_FACTORY_OCIR_PASSWORD__"


def build_ready_to_run_script(payload: dict[str, Any]) -> str:
    """Build a Linux-first Bash script for a live Agent Factory deployment.

    Args:
        payload: Validated Agent Factory deployment payload.

    Returns:
        str: Bash script that invokes the internal Python live deployment
        runner.
    """

    script_payload = _script_payload(payload)
    payload_json = json.dumps(script_payload, indent=2, sort_keys=True)
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
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
            'PAYLOAD_FILE="$(mktemp "${TMPDIR:-/tmp}/agent-factory-payload.XXXXXX.json")"',
            'cleanup() { rm -f "${PAYLOAD_FILE}"; }',
            "trap cleanup EXIT",
            "",
            "cat > \"${PAYLOAD_FILE}\" <<'JSON'",
            payload_json,
            "JSON",
            "",
            'PYTHONPATH="${REPO_ROOT}/agent-factory/api${PYTHONPATH:+:${PYTHONPATH}}" \\',
            'OPENAI_API_KEY="${OPENAI_API_KEY}" \\',
            'OCIR_PASSWORD="${OCIR_PASSWORD}" \\',
            '"${PYTHON_EXECUTABLE}" -m agent_factory_api.ready_script_runner \\',
            '  --payload "${PAYLOAD_FILE}"',
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
    script_payload["confidential_application_secret"] = ""
    return script_payload
