#!/usr/bin/env bash
set -euo pipefail

PROJECT="add-deployment-verify"
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.verify.yml)
API_URL="http://localhost:18000"
WEB_URL="http://localhost:13000"

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${COMPOSE[@]}" up -d --build

for attempt in $(seq 1 30); do
  if curl --fail --silent "$API_URL/ready" >/tmp/add-deployment-ready.json; then break; fi
  if [ "$attempt" = 30 ]; then
    echo "deployment verification: API did not become ready" >&2
    exit 1
  fi
  sleep 2
done

for attempt in $(seq 1 30); do
  if curl --fail --silent "$WEB_URL/" >/tmp/add-deployment-web.json; then break; fi
  if [ "$attempt" = 30 ]; then
    echo "deployment verification: web did not become ready" >&2
    exit 1
  fi
  sleep 2
done

curl --fail --silent "$API_URL/health" >/tmp/add-deployment-health.json
curl --fail --silent "$API_URL/api/diagnostics" >/tmp/add-deployment-diagnostics.json
curl --fail --silent "$WEB_URL/manifest.webmanifest" >/tmp/add-deployment-manifest.json

sentinel="deployment-verification-$(date +%s)"
curl --fail --silent -X POST "$API_URL/api/tasks" \
  -H 'Content-Type: application/json' \
  -d "{\"title\":\"$sentinel\",\"next_action\":{\"text\":\"Verify deployment persistence\",\"estimated_minutes\":30,\"energy\":\"low\"}}" \
  >/tmp/add-deployment-sentinel.json

# A restart is the smallest safe upgrade rehearsal: the same volume and
# entrypoint rerun migrations before the API becomes ready again.
"${COMPOSE[@]}" restart api >/dev/null
for attempt in $(seq 1 30); do
  if curl --fail --silent "$API_URL/ready" >/tmp/add-deployment-ready-after-restart.json; then break; fi
  if [ "$attempt" = 30 ]; then
    echo "deployment verification: API did not recover after restart" >&2
    exit 1
  fi
  sleep 2
done

curl --fail --silent "$API_URL/api/tasks" >/tmp/add-deployment-tasks.json
python3 - <<'PY'
import json

health = json.load(open('/tmp/add-deployment-health.json'))
ready = json.load(open('/tmp/add-deployment-ready.json'))
ready_after = json.load(open('/tmp/add-deployment-ready-after-restart.json'))
diagnostics = json.load(open('/tmp/add-deployment-diagnostics.json'))
manifest = json.load(open('/tmp/add-deployment-manifest.json'))
sentinel = json.load(open('/tmp/add-deployment-sentinel.json'))
tasks = json.load(open('/tmp/add-deployment-tasks.json'))

assert health['status'] == 'ok'
assert ready['status'] == 'ready' and ready['database'] == 'ok'
assert ready_after['status'] == 'ready' and ready_after['database'] == 'ok'
assert diagnostics['deployment']['migration_ok']
assert manifest['name'].startswith('ADD')
assert sentinel['title'].startswith('deployment-verification-')
assert any(task['id'] == sentinel['id'] for task in tasks)
print(f"fresh/upgrade verified: migration={diagnostics['deployment']['migration_revision']}, persisted_task={sentinel['id']}")
PY
