"""Execution sessions: start, pause, resume, finish, offline replay and the MCP bridge."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def begin_task(client, title="Werk", text="Open het dossier"):
    """Create a task with one ready next action and start a 90 second session."""
    client.post("/api/tasks", json={"title": title, "next_action": {"text": text}})
    action = client.get("/api/now").json()
    session = client.post(f"/api/actions/{action['id']}/start?duration_seconds=90").json()
    return action, session


def mcp(client, tool, arguments, request_id=1):
    return client.post("/api/mcp", json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})


def test_session_pause_resume_and_finish_are_single_flight(client):
    action, session = begin_task(client)
    assert session["duration_seconds"] == 90 and session["paused_at"] is None
    assert client.get("/api/sessions/active").json()["session_id"] == session["session_id"]

    paused = client.post(f"/api/sessions/{session['session_id']}/pause")
    assert paused.status_code == 200 and paused.json()["paused_at"] is not None
    assert client.post(f"/api/sessions/{session['session_id']}/pause").status_code == 409

    resumed = client.post(f"/api/sessions/{session['session_id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused_at"] is None and resumed.json()["paused_seconds"] >= 0
    assert client.post(f"/api/sessions/{session['session_id']}/resume").status_code == 409

    finished = client.post(f"/api/sessions/{session['session_id']}/finish", json={"outcome": "done"})
    assert finished.status_code == 200 and finished.json()["outcome"] == "done"
    assert client.get("/api/sessions/active").json() is None
    assert [(row["action_id"], row["outcome"]) for row in client.get("/api/completions").json()] == [(action["id"], "done")]
    assert client.post(f"/api/sessions/{session['session_id']}/finish", json={"outcome": "done"}).status_code == 409
    assert client.post(f"/api/actions/{action['id']}/start").status_code == 409
    assert client.get("/api/now").json() is None

    assert client.post("/api/sessions/missing/pause").status_code == 404
    assert client.post("/api/sessions/missing/resume").status_code == 404
    assert client.post("/api/sessions/missing/finish", json={"outcome": "done"}).status_code == 404


def test_offline_completion_is_replay_safe(client):
    client.post("/api/tasks", json={"title": "Offline", "next_action": {"text": "Doe de stap"}})
    action = client.get("/api/now").json()
    payload = {"action_id": action["id"], "outcome": "done", "started_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()}

    first = client.post("/api/offline/complete", json=payload)
    synced = first.json()
    assert first.status_code == 200
    assert synced["status"] == "synced" and synced["action_id"] == action["id"] and synced["session_id"]

    replay = client.post("/api/offline/complete", json=payload)
    assert replay.status_code == 409 and replay.json()["detail"] == "offline conflict: action is no longer ready"
    unknown = client.post("/api/offline/complete", json={**payload, "action_id": "missing"})
    assert unknown.status_code == 409 and unknown.json()["detail"] == "offline conflict: action no longer exists"


def test_accountability_session_requires_a_running_execution_session(client):
    _, session = begin_task(client)
    session_id = session["session_id"]

    assert client.post("/api/accountability/start", json={"execution_session_id": "missing"}).status_code == 404
    started = client.post("/api/accountability/start", json={"execution_session_id": session_id, "participant_label": "Ruben"})
    assert started.status_code == 200 and started.json()["status"] == "running"
    assert client.post("/api/accountability/start", json={"execution_session_id": session_id}).status_code == 409
    accountability_id = started.json()["id"]

    finished = client.post(f"/api/accountability/{accountability_id}/finish", json={"status": "completed"})
    assert finished.status_code == 200 and finished.json()["status"] == "completed"
    assert client.post(f"/api/accountability/{accountability_id}/finish", json={"status": "stopped"}).status_code == 409
    assert client.post("/api/accountability/missing/finish", json={"status": "completed"}).status_code == 404
    assert client.post(f"/api/accountability/{accountability_id}/finish", json={"status": "later"}).status_code == 422

    # A finished accountability session frees the execution session for a new buddy.
    assert client.post("/api/accountability/start", json={"execution_session_id": session_id}).status_code == 200


def test_mcp_tool_calls_drive_the_session_lifecycle(client):
    _, session = begin_task(client)
    completed = mcp(client, "execution_complete_action", {"session_id": session["session_id"], "outcome": "done"})
    assert completed.json()["result"]["content"][0]["json"]["outcome"] == "done"
    assert client.get("/api/sessions/active").json() is None

    invalid = mcp(client, "execution_complete_action", {"session_id": session["session_id"], "outcome": "nonsense"}, request_id=2)
    assert invalid.json()["error"]["code"] == -32602
    missing_session = mcp(client, "execution_complete_action", {"session_id": "missing", "outcome": "done"}, request_id=3)
    assert missing_session.status_code == 404

    _, second = begin_task(client, title="Tweede", text="Open het tweede dossier")
    stuck = mcp(client, "execution_mark_stuck", {"session_id": second["session_id"], "stuck_reason": "te vaag"}, request_id=4)
    assert stuck.json()["result"]["content"][0]["json"]["outcome"] == "stuck"
    blocked = client.get("/api/actions?status=blocked").json()
    assert len(blocked) == 1 and blocked[0]["text"] == "Open het tweede dossier"
