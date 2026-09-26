from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Action, ActionStatus, SuggestionStatus, Task, TaskStatus, TaskSuggestionRecord

# The workflow summary buckets "planned today" by the local day of the *requested*
# timezone, while these fixtures were built from the wall clock in UTC. CI run
# #35546118800 ran at 2026-09-20T23:57Z — 01:57 in Europe/Amsterdam — so `now - 2h`
# landed on the previous local day and only one of the two planned tasks was counted as
# today. Pinning the clock to the instant that failed keeps the local-day boundary this
# test exercises deterministic, whatever time of day the suite runs at.
FROZEN_NOW = datetime(2026, 9, 20, 23, 57, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    """``datetime`` stand-in for the endpoint under test, pinned to FROZEN_NOW."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr("app.main.datetime", FrozenDatetime)
    return FROZEN_NOW


@pytest.fixture
def workflow_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), factory
    app.dependency_overrides.clear()


def test_workflow_summary_counts_stages_sources_and_deduplicates_review(workflow_client, frozen_clock):
    client, factory = workflow_client
    now = frozen_clock
    with factory() as db:
        db.add_all([
            Task(title="Inbox manual", status=TaskStatus.INBOX, source_type="manual"),
            Task(title="Later", status=TaskStatus.ACTIVE, source_type="manual"),
            # Later the same local day (02:57 in Europe/Amsterdam).
            Task(title="Today", status=TaskStatus.ACTIVE, planned_at=now + timedelta(hours=1), source_type="calendar"),
            # Earlier the same local day (00:57) and already past, so missed as well.
            Task(title="Overdue and missed", status=TaskStatus.ACTIVE, planned_at=now - timedelta(hours=1), deadline=now - timedelta(minutes=30), source_type="gmail"),
        ])
        blocked = Task(title="Blocked", status=TaskStatus.ACTIVE, source_type="ha")
        db.add(blocked)
        db.flush()
        db.add(Action(task_id=blocked.id, text="Unblock", status=ActionStatus.BLOCKED))
        db.add(TaskSuggestionRecord(title="Suggestion", source_type="hermes", suggested_next_action="Review", status=SuggestionStatus.PENDING))
        db.commit()
    response = client.get("/api/workflow-summary?timezone=Europe%2FAmsterdam")
    assert response.status_code == 200
    body = response.json()
    assert body["inbox"]["count"] == 2
    assert body["later"]["count"] == 2
    assert body["planned"]["today_count"] == 2
    assert body["planned"]["missed_count"] == 1
    assert body["review"]["count"] == 3
    assert body["review"]["breakdown"] == {"open_proposals": 1, "overdue": 1, "missed_commitments": 1, "blocked": 1}
    assert body["next"]["key"] == "review"


def test_workflow_summary_rejects_unknown_timezone(workflow_client):
    client, _ = workflow_client
    assert client.get("/api/workflow-summary?timezone=Not/AZone").status_code == 400


def test_preferences_default_and_update(workflow_client):
    client, _ = workflow_client
    assert client.get("/api/preferences").json()["workflow_badge_mode"] == "dot"
    response = client.patch("/api/preferences", json={"workflow_badge_mode": "hidden"})
    assert response.status_code == 200
    assert client.get("/api/preferences").json()["workflow_badge_mode"] == "hidden"
    assert client.patch("/api/preferences", json={"workflow_badge_mode": "loud"}).status_code == 422


def test_mail_polling_preference_is_persistent_and_gui_controlled(workflow_client):
    client, _ = workflow_client
    assert client.get("/api/preferences").json()["mail_poll_enabled"] is False
    enabled = client.patch("/api/preferences", json={"workflow_badge_mode": "dot", "mail_poll_enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["mail_poll_enabled"] is True
    assert client.get("/api/preferences").json()["mail_poll_enabled"] is True
    disabled = client.patch("/api/preferences", json={"workflow_badge_mode": "dot", "mail_poll_enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["mail_poll_enabled"] is False


def test_runtime_settings_are_saved_without_returning_secrets(workflow_client):
    client, _ = workflow_client
    response = client.patch("/api/preferences", json={
        "workflow_badge_mode": "dot",
        "api_cors_origins": "https://add.example, http://localhost:3000",
        "secure_cookies": True,
        "mail_poll_interval_seconds": 600,
        "mail_sync_batch_size": 10,
        "mail_auto_cleanup_confidence": .995,
        "github_repo": "owner/project",
        "api_token": "runtime-secret",
        "github_token": "github-secret",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["secure_cookies"] is True
    assert body["mail_poll_interval_seconds"] == 600
    assert "runtime-secret" not in response.text
    assert "github-secret" not in response.text


def test_first_start_requires_local_password_before_setup_is_complete(workflow_client):
    client, _ = workflow_client
    initial = client.get("/api/auth/status")
    assert initial.status_code == 200
    assert initial.json()["first_start_required"] is True

    setup = client.post("/api/auth/setup", json={"password": "a-safe-local-password"})
    assert setup.status_code == 200
    configured = client.get("/api/auth/status").json()
    assert configured["first_start_required"] is False
    assert configured["enabled"] is True

    login = client.post("/api/auth/login", json={"password": "a-safe-local-password"})
    assert login.status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True
