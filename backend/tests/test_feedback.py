from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.github_issue import GitHubIssueResult
from app.main import app
from app.config import settings


@pytest.fixture
def feedback_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "github_token", "test-token")
    monkeypatch.setattr(settings, "github_repo", "rbnbrls/add")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_feedback_creates_labelled_github_issue(feedback_client, monkeypatch):
    create_issue = AsyncMock(return_value=GitHubIssueResult(True, "https://github.com/rbnbrls/add/issues/12", 12))
    monkeypatch.setattr("app.main.create_github_issue", create_issue)

    response = feedback_client.post("/api/feedback", json={"type": "bug", "title": "Knop werkt niet", "description": "De knop reageert niet."})

    assert response.status_code == 200
    assert response.json()["issue_number"] == 12
    assert create_issue.await_args.kwargs["title"] == "[BUG] Knop werkt niet"
    assert create_issue.await_args.kwargs["labels"] == ["bug", "feedback"]


def test_feedback_requires_title_and_description(feedback_client):
    response = feedback_client.post("/api/feedback", json={"type": "feature", "title": "", "description": ""})
    assert response.status_code == 422


def test_feedback_reports_missing_configuration(feedback_client, monkeypatch):
    monkeypatch.setattr(settings, "github_token", "")
    response = feedback_client.post("/api/feedback", json={"title": "Idee", "description": "Beschrijving"})
    assert response.status_code == 503
