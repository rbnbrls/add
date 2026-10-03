from pathlib import Path


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "deploy.yml"
PRODUCTION_COMPOSE = WORKFLOW.parents[2] / "docker-compose.production.yml"


def test_coolify_deployments_use_the_configured_token() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count('auth_header="Authorization:"') == 2
    assert workflow.count('--header "$auth_header Bearer $COOLIFY_TOKEN"') == 2
    assert 'Bearer ***' not in workflow


def test_production_compose_is_safe_for_coolify_host_networking() -> None:
    compose = PRODUCTION_COMPOSE.read_text(encoding="utf-8")

    assert 'ports:' not in compose
    assert 'add_postgres:/var/lib/postgresql/data' in compose
    assert 'condition: service_healthy' in compose