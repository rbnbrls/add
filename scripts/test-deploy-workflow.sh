#!/usr/bin/env bash
set -euo pipefail

workflow="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.github/workflows/deploy.yml"

test "$(grep -cF 'Authorization: Bearer $COOLIFY_TOKEN' "$workflow")" -eq 2
if grep -qF 'Authorization: Bearer ***' "$workflow"; then
  echo "deployment workflow contains a redacted placeholder instead of the Coolify token" >&2
  exit 1
fi

echo "deployment workflow uses the configured Coolify token for both deployment jobs"
