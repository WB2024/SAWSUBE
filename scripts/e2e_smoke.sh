#!/usr/bin/env bash
# End-to-end smoke test: build the Docker image, start it with an empty data
# directory and exercise the HTTP API. No TV needed.
#   scripts/e2e_smoke.sh             # offline checks
#   E2E_NETWORK=1 scripts/e2e_smoke.sh   # also call external source APIs
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE=${E2E_IMAGE:-sawsube-e2e:local}
NAME=sawsube-e2e-$$
PORT=${E2E_PORT:-18000}
DATA=$(mktemp -d)
fail=0

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$DATA"
}
trap cleanup EXIT

check() {  # check <description> <command...>
  if "${@:2}"; then echo "ok   - $1"; else echo "FAIL - $1"; fail=1; fi
}

echo "# building $IMAGE"
docker build -q -f Dockerfile.backend -t "$IMAGE" . >/dev/null

docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8000" \
  -e DB_PATH=/app/data/sawsube.db -e IMAGE_FOLDER=/app/data/images \
  -e TOKEN_DIR=/app/data/tokens -e POLL_INTERVAL_SECS=3600 \
  -v "$DATA:/app/data" "$IMAGE" >/dev/null

BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 60); do curl -fs "$BASE/api/health" >/dev/null 2>&1 && break; sleep 1; done

check "health endpoint" curl -fs "$BASE/api/health"
check "SPA index served" sh -c "curl -fs '$BASE/' | grep -qi '<html'"
check "SPA deep link falls back to index" sh -c "curl -fs '$BASE/library' | grep -qi '<html'"
check "path traversal blocked (encoded slash)" \
  sh -c "! curl -s --path-as-is '$BASE/..%2f..%2f..%2fetc%2fpasswd' | grep -q 'root:'"
check "path traversal blocked (encoded dots)" \
  sh -c "! curl -s --path-as-is '$BASE/%2e%2e/%2e%2e/%2e%2e/etc/passwd' | grep -q 'root:'"
check "TV list API" sh -c "curl -fs '$BASE/api/tvs' | grep -q '^\[\]$'"
check "samsungframetv importable in image" docker exec "$NAME" python -c "import samsungframetv.async_art"
check "TV library detected by backend" \
  docker exec "$NAME" python -c "from backend.services.tv_manager import HAS_LIB; assert HAS_LIB"
check "frontend built from a clean npm install" \
  docker exec "$NAME" sh -c "test -f /app/frontend/dist/index.html"

if [ "${E2E_NETWORK:-0}" = 1 ]; then
  check "Openverse search (network)" sh -c "curl -fs '$BASE/api/sources/openverse/search?q=landscape' | grep -q '\"url\"'"
fi

if [ "$fail" != 0 ]; then
  echo "# container logs"; docker logs "$NAME" 2>&1 | tail -40
  exit 1
fi
echo "# all checks passed"
