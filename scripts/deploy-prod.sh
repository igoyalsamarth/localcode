#!/usr/bin/env bash
# Pull latest images from GHCR and recreate app containers.
# Requires: Docker, docker compose plugin, .env with app secrets, and GRAGENT_IMAGE set
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

export GRAGENT_IMAGE
docker compose -f docker-compose.prod.yml pull api-backend worker
docker compose -f docker-compose.prod.yml up -d --remove-orphans
