#!/usr/bin/env bash
# Pull latest images from GHCR and recreate app containers.
# Requires: `docker compose` (Compose v2+ as a CLI plugin). Legacy `docker-compose` 1.x is unsupported.
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
    return
  fi
  echo "Missing \`docker compose\` (Compose v2+ plugin). Install e.g. from Docker's apt repo" >&2
  echo "or https://github.com/docker/compose/releases (docker-compose-linux-\$(uname -m) → cli-plugins)." >&2
  exit 1
}

export GRAGENT_IMAGE
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-greagent}"

docker_rm_matching() {
  local ids
  ids=$(docker ps -aq --filter "$1" 2>/dev/null || true)
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086
    docker rm -f $ids
  fi
}

# Pull, then replace app containers without relying on in-place "recreate" (avoids name conflicts).
run_compose -f docker-compose.prod.yml pull api-backend worker
run_compose -f docker-compose.prod.yml stop -t 30 api-backend worker 2>/dev/null || true
run_compose -f docker-compose.prod.yml rm -f api-backend worker 2>/dev/null || true
docker_rm_matching "name=greagent-api-backend"
docker_rm_matching "name=greagent-worker"
docker_rm_matching "name=app_worker"

run_compose -f docker-compose.prod.yml up -d --remove-orphans
