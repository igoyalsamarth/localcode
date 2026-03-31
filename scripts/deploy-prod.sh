#!/usr/bin/env bash
# Pull latest images from GHCR and recreate app containers.
# Requires: Docker, Compose (docker compose plugin or docker-compose), .env, and GRAGENT_IMAGE
# (e.g. in .env: GRAGENT_IMAGE=ghcr.io/org/gragent-be:latest).
#
# Private GHCR: docker login ghcr.io -u USER -p <PAT with read:packages>

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${GRAGENT_IMAGE:-}" ]] && [[ -f .env ]]; then
  # shellcheck source=/dev/null
  set -a && source .env && set +a
fi

if [[ -z "${GRAGENT_IMAGE:-}" ]]; then
  echo "GRAGENT_IMAGE is not set. Add it to .env or export it before running this script." >&2
  exit 1
fi

run_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Need Docker Compose v2 (docker compose) or docker-compose v1 on PATH." >&2
    exit 1
  fi
}

export GRAGENT_IMAGE
run_compose -f docker-compose.prod.yml pull api-backend worker
run_compose -f docker-compose.prod.yml up -d --remove-orphans
