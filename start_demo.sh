#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_CMD="docker-compose"
BUILD_FLAG=""

usage() {
  cat <<EOF
Usage: ./start_demo.sh [--build]

Starts the local Docker Compose demo deployment.

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

if [[ ! -f ".env" ]]; then
  echo "Missing .env file in ${SCRIPT_DIR}." >&2
  echo "Create it from .env.sample and fill in the required values." >&2
  exit 1
fi

echo "Starting OCI RAG Agent Blueprint demo..."
if [[ -n "${BUILD_FLAG}" ]]; then
  "${COMPOSE_CMD}" up -d --build
else
  "${COMPOSE_CMD}" up -d
fi

echo
"${COMPOSE_CMD}" ps
echo
echo "Backend: http://localhost:8080"
echo "UI:      http://localhost:3000"
