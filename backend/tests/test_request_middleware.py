"""Request-level behaviour of the operational middleware."""

import logging
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.routing import Route

from app.db import Base, get_db
from app.main import _rate_buckets, app


class _CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def capture_api_logs(logger_name="add.api"):
    """Collect this logger's records without depending on process log state.

    ``alembic.env`` calls ``fileConfig``, which disables every logger that
    already exists at that moment, so the application logger is switched off for
    the rest of the test session. pytest's ``caplog`` fixture inherits that state
    and sees nothing; this helper re-enables the logger for the duration of one
    test and restores it afterwards.
    """
    logger = logging.getLogger(logger_name)
    handler = _CollectingHandler()
    previous = (logger.disabled, logger.level)
    logger.disabled, logger.level = False, logging.INFO
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled, logger.level = previous


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # The buckets are process state; a bucket left behind by another test would
    # make this file order-dependent.
    _rate_buckets.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    _rate_buckets.clear()


def test_request_id_is_generated_honoured_and_logged(client):
    with capture_api_logs() as records:
        generated = client.get("/health")
        echoed = client.get("/health", headers={"X-Request-ID": "probe-request-id"})

    request_id = generated.headers["X-Request-ID"]
    assert generated.status_code == 200
    assert request_id and request_id != "probe-request-id"
    assert echoed.headers["X-Request-ID"] == "probe-request-id"
    completed = [record for record in records if record.getMessage() == "request_complete"]
    assert [record.request_id for record in completed] == [request_id, "probe-request-id"]


def test_connector_rate_limit_is_per_path_and_reports_retry_after(client):
    intake = {"message_id": "rate-limit-probe", "subject": "Probe", "snippet": "Probe"}
    allowed = [client.post("/api/connectors/gmail/intake", json=intake).status_code for _ in range(30)]
    limited = client.post("/api/connectors/gmail/intake", json=intake)

    assert set(allowed) == {200}
    assert limited.status_code == 429
    assert limited.json()["detail"] == "rate limit exceeded"
    assert limited.headers["Retry-After"] == "60"
    assert limited.headers["X-Request-ID"]
    # Another limited prefix keeps its own budget, and unprotected routes are untouched.
    suggestion = {"title": "Na de limiet", "suggested_next_action": "Open het dossier", "confidence": .5}
    assert client.post("/api/mcp/task-suggestions", json=suggestion).status_code == 200
    assert client.get("/health").status_code == 200


def test_unhandled_errors_are_logged_and_still_reach_the_client():
    async def explode(request):
        raise RuntimeError("probe failure")

    route = Route("/__middleware_probe", explode)
    app.router.routes.append(route)
    try:
        with TestClient(app, raise_server_exceptions=False) as probe:
            with capture_api_logs() as records:
                response = probe.get("/__middleware_probe", headers={"X-Request-ID": "probe-boom"})
    finally:
        app.router.routes.remove(route)

    assert response.status_code == 500
    failed = [record for record in records if record.getMessage() == "request_failed"]
    assert [record.request_id for record in failed] == ["probe-boom"]
