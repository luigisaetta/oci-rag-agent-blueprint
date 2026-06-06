#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/agent-factory/docker-compose.yml"
COMPOSE_CMD="docker-compose"
BUILD_FLAG=""

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
  "${COMPOSE_CMD}" -f "${COMPOSE_FILE}" up -d --build
else
  "${COMPOSE_CMD}" -f "${COMPOSE_FILE}" up -d
fi

echo
"${COMPOSE_CMD}" -f "${COMPOSE_FILE}" ps
echo
echo "Agent Factory API: http://localhost:8081/factory/health"
echo "Agent Factory UI:  http://localhost:3100"
