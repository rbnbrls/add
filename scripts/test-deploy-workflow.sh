#!/usr/bin/env bash
set -euo pipefail

workflow=".github/workflows/deploy.yml"

if [ ! -f "$workflow" ]; then
  echo "deployment workflow test: missing $workflow" >&2
  exit 1
fi

count="$(grep -F '            --header "$auth_header Bearer $COOLIFY_TOKEN"' "$workflow" | wc -l)"
if [ "$count" -ne 2 ]; then
  echo "deployment workflow test: expected two token-bearing Coolify requests, found $count" >&2
  exit 1
fi

if grep -Fq 'Bearer ***' "$workflow"; then
  echo "deployment workflow test: literal redacted authorization header remains" >&2
  exit 1
fi

if [ "$(grep -F 'auth_header="Authorization:"' "$workflow" | wc -l)" -ne 2 ]; then
  echo "deployment workflow test: expected two explicit authorization header definitions" >&2
  exit 1
fi

echo "deployment workflow authentication verified"
