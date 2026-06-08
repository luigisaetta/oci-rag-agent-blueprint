#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/agent-factory/docker-compose.yml"
COMPOSE_PROJECT_NAME="agent-factory"

export OCI_PROFILE="${OCI_PROFILE:-DEFAULT}"
export OCI_AUTH_MODE="${OCI_AUTH_MODE:-user_principal}"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is required. Install docker-compose or Docker Compose v2." >&2
  exit 1
fi

compose() {
  "${COMPOSE_CMD[@]}" -p "${COMPOSE_PROJECT_NAME}" -f "${COMPOSE_FILE}" "$@"
}

cd "${SCRIPT_DIR}"

echo "Stopping Agent Factory..."
compose down
