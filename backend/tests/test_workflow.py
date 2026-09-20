from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Action, ActionStatus, SuggestionStatus, Task, TaskStatus, TaskSuggestionRecord


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


def test_workflow_summary_counts_stages_sources_and_deduplicates_review(workflow_client):
    client, factory = workflow_client
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with factory() as db:
        db.add_all([
            Task(title="Inbox manual", status=TaskStatus.INBOX, source_type="manual"),
            Task(title="Later", status=TaskStatus.ACTIVE, source_type="manual"),
            Task(title="Today", status=TaskStatus.ACTIVE, planned_at=now + timedelta(hours=1), source_type="calendar"),
            Task(title="Overdue and missed", status=TaskStatus.ACTIVE, planned_at=now - timedelta(hours=2), deadline=now - timedelta(hours=1), source_type="gmail"),
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
