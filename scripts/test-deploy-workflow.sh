#!/usr/bin/env bash
# The Coolify authorisation contract is owned by scripts/deployment_contract.py,
# which is also what backend/tests/test_deployment_contract.py asserts against,
# so the CI gate and the suite cannot disagree about it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workflow="${here}/../.github/workflows/deploy.yml"

if [ ! -f "${workflow}" ]; then
  echo "deployment workflow test: missing ${workflow}" >&2
  exit 1
fi

python3 "${here}/deployment_contract.py" "${workflow}"