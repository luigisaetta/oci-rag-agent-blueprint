#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/agent-factory/docker-compose.yml"
COMPOSE_PROJECT_NAME="agent-factory"
BUILD_FLAG=""

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

usage() {
  cat <<EOF
Usage: ./start_factory.sh [--build]

Starts the local Docker Compose Agent Factory deployment.

Options:
  --build    Build Docker images before starting the deployment.
  -h, --help Show this help message.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)
      BUILD_FLAG="--build"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "${SCRIPT_DIR}"

echo "Starting Agent Factory..."
if [[ -n "${BUILD_FLAG}" ]]; then
  compose build --no-cache factory-api
  compose up -d --build --force-recreate
else
  compose up -d
fi

echo
compose ps
echo
echo "Agent Factory API: http://localhost:8081/factory/health"
echo "Agent Factory UI:  http://localhost:3100"
