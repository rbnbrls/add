#!/usr/bin/env bash
set -euo pipefail

workflow=".github/workflows/deploy.yml"

if [ ! -f "$workflow" ]; then
  echo "deployment workflow test: missing $workflow" >&2
  exit 1
fi

count="$(grep -F 'Authorization: Bearer' "$workflow" | wc -l)"
if [ "$count" -ne 2 ]; then
  echo "deployment workflow test: expected two token-bearing Coolify requests, found $count" >&2
  exit 1
fi

if grep -Fq 'Authorization: Bearer ***' "$workflow"; then
  echo "deployment workflow test: literal redacted authorization header remains" >&2
  exit 1
fi

echo "deployment workflow authentication verified"