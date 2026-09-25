from pathlib import Path


COMPOSE = Path(__file__).parents[2] / "docker-compose.yml"


def test_api_healthcheck_uses_ipv4_loopback_inside_container():
    compose = COMPOSE.read_text()

    assert "http://127.0.0.1:8000/health" in compose
    assert "http://localhost:8000/health" not in compose