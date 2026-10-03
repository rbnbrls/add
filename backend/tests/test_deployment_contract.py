"""Contract tests for the deployment workflow and the production compose file.

The Coolify authorisation contract itself lives in
``scripts/deployment_contract.py`` so that this suite and the CI shell gate
(``scripts/test-deploy-workflow.sh``) cannot drift apart: the two used to hold
separate copies of the same literal, and CI run #30 failed when a workflow
refactor updated one shape and not the other. The module asserts the invariant,
not one spelling of it, and the tests below pin that tolerance.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
PRODUCTION_COMPOSE = REPO_ROOT / "docker-compose.production.yml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from deployment_contract import violations  # noqa: E402

#: The two spellings the workflow is allowed to use for its auth header: inline,
#: and composed from a shell variable (the shape that broke CI run #30). Both
#: must satisfy the contract; a guard that accepts only one is the defect.
INLINE_REQUEST = (
    'curl --request POST "$COOLIFY_WEBHOOK" \\\n'
    '  --header "Authorization: Bearer $COOLIFY_TOKEN"\n'
)
COMPOSED_REQUEST = (
    'auth_header="Authorization:"\n'
    'curl --request POST "$COOLIFY_WEBHOOK" \\\n'
    '  --header "$auth_header Bearer $COOLIFY_TOKEN"\n'
)


def test_coolify_deployments_use_the_configured_token() -> None:
    assert violations(WORKFLOW.read_text(encoding="utf-8")) == []


def test_the_contract_accepts_either_header_composition() -> None:
    """A workflow refactor must not turn CI red on its own."""
    assert violations(INLINE_REQUEST * 2) == []
    assert violations(COMPOSED_REQUEST * 2) == []


def test_the_contract_rejects_a_request_without_the_token() -> None:
    workflow = INLINE_REQUEST + 'curl --request POST "$COOLIFY_WEBHOOK"\n'
    assert violations(workflow)


def test_the_contract_rejects_a_redacted_placeholder() -> None:
    workflow = INLINE_REQUEST * 2 + 'echo "Bearer ***"\n'
    assert violations(workflow)


def test_production_compose_is_safe_for_coolify_host_networking() -> None:
    compose = PRODUCTION_COMPOSE.read_text(encoding="utf-8")

    assert 'ports:' not in compose
    assert 'add_postgres:/var/lib/postgresql/data' in compose
    assert 'condition: service_healthy' in compose