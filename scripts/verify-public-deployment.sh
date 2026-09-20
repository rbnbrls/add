#!/usr/bin/env bash
set -euo pipefail

DEPLOYMENT_URL="${DEPLOYMENT_URL:?DEPLOYMENT_URL is required}"
DEPLOYMENT_URL="${DEPLOYMENT_URL%/}"

last_error=""
for attempt in $(seq 1 "${DEPLOYMENT_ATTEMPTS:-30}"); do
  if health="$(curl --fail --silent --show-error --max-time 15 "$DEPLOYMENT_URL/health" 2>&1)" \
    && ready="$(curl --fail --silent --show-error --max-time 15 "$DEPLOYMENT_URL/ready" 2>&1)" \
    && diagnostics="$(curl --fail --silent --show-error --max-time 15 "$DEPLOYMENT_URL/api/diagnostics" 2>&1)" \
    && manifest="$(curl --fail --silent --show-error --max-time 15 "$DEPLOYMENT_URL/manifest.webmanifest" 2>&1)"; then
    python3 - "$health" "$ready" "$diagnostics" "$manifest" "$DEPLOYMENT_URL" <<'PY'
import json
import sys

health, ready, diagnostics, manifest = map(json.loads, sys.argv[1:5])
url = sys.argv[5]
assert health["status"] == "ok", health
assert ready["status"] == "ready" and ready["database"] == "ok", ready
assert diagnostics["deployment"]["migration_ok"], diagnostics
assert manifest["name"].startswith("ADD"), manifest
assert any(item["url"] == "/intake?quick=1" for item in manifest["shortcuts"]), manifest
print(f"public deployment verified: {url}, migration={diagnostics['deployment']['migration_revision']}")
PY
    exit 0
  else
    last_error="${health:-${ready:-${diagnostics:-${manifest:-unknown error}}}}"
  fi
  if [ "$attempt" -lt "${DEPLOYMENT_ATTEMPTS:-30}" ]; then
    sleep "${DEPLOYMENT_WAIT_SECONDS:-10}"
  fi
done

echo "public deployment verification failed for $DEPLOYMENT_URL: $last_error" >&2
exit 1
