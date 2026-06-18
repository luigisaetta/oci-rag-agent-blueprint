#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Edit these values before running the script.
HOSTED_APPLICATION_RESPONSES_URL="https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke/responses"
AUTH_MODE="idcs"
ENV_FILE=".env"
CREATE_CONVERSATION="true"
CONVERSATION_ID=""
STREAM="true"
USER_REQUEST="Explain the documents in the vector store."

# Optional: override the Python executable from the shell, for example:
# PYTHON_BIN=python3 ./test_hosted_application.sh
PYTHON_BIN="${PYTHON_BIN:-python}"

usage() {
  cat <<EOF
Usage: ./test_hosted_application.sh

Edit the variables near the top of this file, then run it from the repository
root. The script calls the full Python CLI client and, when AUTH_MODE is idcs or
auto with IDCS variables present, sends the acquired JWT as a Bearer token.

Required .env values for AUTH_MODE=idcs:
  IDENTITY_DOMAIN_URL
  CONFIDENTIAL_APPLICATION_ID
  CONFIDENTIAL_APPLICATION_SECRET
  IDCS_SCOPE
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

cd "${SCRIPT_DIR}"

if [[ "${HOSTED_APPLICATION_RESPONSES_URL}" == *"<"* || "${HOSTED_APPLICATION_RESPONSES_URL}" == *">"* ]]; then
  echo "HOSTED_APPLICATION_RESPONSES_URL still contains placeholder values." >&2
  echo "Edit test_hosted_application.sh and set the real /actions/invoke/responses URL." >&2
  exit 1
fi

if [[ "${AUTH_MODE}" != "none" && ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE} file in ${SCRIPT_DIR}." >&2
  echo "Create it from .env.sample and fill in the IDCS client values." >&2
  exit 1
fi

if [[ "${CREATE_CONVERSATION}" == "false" && -z "${CONVERSATION_ID}" ]]; then
  echo "CONVERSATION_ID is required when CREATE_CONVERSATION=false." >&2
  exit 1
fi

COMMAND=(
  "${PYTHON_BIN}"
  -m
  clients.agent_cli
  --endpoint
  "${HOSTED_APPLICATION_RESPONSES_URL}"
  --auth
  "${AUTH_MODE}"
  --env-file
  "${ENV_FILE}"
  --create-conversation
  "${CREATE_CONVERSATION}"
  --stream
  "${STREAM}"
)

if [[ "${CREATE_CONVERSATION}" == "false" ]]; then
  COMMAND+=(--conversation-id "${CONVERSATION_ID}")
fi

COMMAND+=("${USER_REQUEST}")

echo "Testing Hosted Application endpoint:"
echo "${HOSTED_APPLICATION_RESPONSES_URL}"
echo

"${COMMAND[@]}"
