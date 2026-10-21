from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "compose_name",
    ["docker-compose.yml", "docker-compose.coolify.yml", "docker-compose.production.yml"],
)
def test_api_healthcheck_uses_ipv4_loopback_inside_container(compose_name: str):
    compose = (REPO_ROOT / compose_name).read_text()

    assert "http://127.0.0.1:8000/health" in compose
    assert "http://localhost:8000/health" not in compose
