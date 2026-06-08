#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/agent-factory/docker-compose.yml"
COMPOSE_CMD="docker-compose"
COMPOSE_PROJECT_NAME="agent-factory"

cd "${SCRIPT_DIR}"

echo "Stopping Agent Factory..."
"${COMPOSE_CMD}" -p "${COMPOSE_PROJECT_NAME}" -f "${COMPOSE_FILE}" down
