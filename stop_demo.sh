#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_CMD="docker-compose"

cd "${SCRIPT_DIR}"

echo "Stopping OCI RAG Agent Blueprint demo..."
"${COMPOSE_CMD}" down
