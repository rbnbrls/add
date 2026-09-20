#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"

health="$(curl --fail --silent --show-error "$API_URL/health")"
ready="$(curl --fail --silent --show-error "$API_URL/ready")"
diagnostics="$(curl --fail --silent --show-error "$API_URL/api/diagnostics")"
manifest="$(curl --fail --silent --show-error "$WEB_URL/manifest.webmanifest")"

python3 - "$health" "$ready" "$diagnostics" "$manifest" <<'PY'
import json
import sys

health, ready, diagnostics, manifest = map(json.loads, sys.argv[1:])
assert health["status"] == "ok"
assert ready["status"] == "ready" and ready["database"] == "ok"
assert diagnostics["deployment"]["migration_ok"]
assert manifest["name"].startswith("ADD")
assert any(item["url"] == "/intake?quick=1" for item in manifest["shortcuts"])
print(f"deployment verified: migration={diagnostics['deployment']['migration_revision']}")
PY
