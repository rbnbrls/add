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


def test_hermes_suggestion_requires_approval(client):
    payload = {"title": "Belasting", "suggested_next_action": "Open de aangifte", "confidence": 0.9}
    created = client.post("/api/mcp/task-suggestions", json=payload).json()
    assert created["status"] == "pending"
    assert all(t["title"] != "Belasting" for t in client.get("/api/tasks").json())
    approved = client.post(f"/api/mcp/task-suggestions/{created['id']}/approve").json()
    assert approved["title"] == "Belasting"
    assert client.get(f"/api/mcp/task-suggestions?status=accepted").json()[0]["task_id"] == approved["id"]


def test_inbox_decision_sets_urgent_priority(client):
    created = client.post("/api/mcp/task-suggestions", json={"title": "Urgent taak", "suggested_next_action": "Open taak", "confidence": .9}).json()
    approved = client.post(f"/api/mcp/task-suggestions/{created['id']}/approve", json={"urgent": True})
    assert approved.status_code == 200
    assert approved.json()["priority"] == "high"


def test_inbox_now_decision_finds_next_free_slot_and_sets_priority_one(client):
    created = client.post("/api/mcp/task-suggestions", json={"title": "Nu taak", "suggested_next_action": "Begin taak", "confidence": .9}).json()
    planned = client.post(f"/api/inbox/review/{created['id']}/plan", json={"destination": "today", "urgent": True})
    assert planned.status_code == 200
    task = next(item for item in client.get("/api/tasks").json() if item["id"] == planned.json()["task_id"])
    assert task["priority"] == "high"
    assert task["planned_at"] is not None


def test_task_metadata_crud_and_parent_cycle_validation(client):
    parent = client.post("/api/tasks", json={
        "title": "Parent", "planned_at": "2030-01-01T10:00:00Z", "deadline": "2030-01-02T10:00:00Z",
        "tags": [" werk ", "werk", "thuis"], "priority": "high", "next_action": {"text": "Begin"},
    }).json()
    assert parent["tags"] == ["werk", "thuis"]
    assert parent["priority"] == "high"
    child = client.post("/api/tasks", json={"title": "Child", "parent_id": parent["id"]}).json()
    assert child["parent_id"] == parent["id"]
    parent_read = next(item for item in client.get("/api/tasks").json() if item["id"] == parent["id"])
    assert child["id"] in [item["id"] for item in parent_read["children"]]
    cycle = client.patch(f"/api/tasks/{parent['id']}", json={"parent_id": child["id"]})
    assert cycle.status_code == 409
    updated = client.patch(f"/api/tasks/{child['id']}", json={"planned_at": None, "tags": [], "actual_minutes": 4}).json()
    assert updated["planned_at"] is None
    assert updated["actual_minutes"] == 4
    assert client.delete(f"/api/tasks/{parent['id']}").status_code == 409
    assert client.delete(f"/api/tasks/{child['id']}").status_code == 200
    assert client.delete(f"/api/tasks/{parent['id']}").status_code == 200


def test_provider_intake_is_idempotent_for_external_message_id(client):
    payload = {
        "subject": "Dubbele factuur",
        "snippet": "Controleer deze factuur",
        "message_id": "gmail-message-42",
    }
    first = client.post("/api/connectors/gmail/intake", json=payload)
    second = client.post("/api/connectors/gmail/intake", json={**payload, "subject": "Gewijzigde retry"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["title"] == "Dubbele factuur"
    assert len(client.get("/api/mcp/task-suggestions?status=pending").json()) == 1


def test_reviewed_suggestion_can_be_planned_and_undone(client):
    created = client.post("/api/mcp/task-suggestions", json={"title": "Planbare taak", "suggested_next_action": "Open dossier", "confidence": .8}).json()
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(second=0, microsecond=0)
    planned = client.post(f"/api/inbox/review/{created['id']}/plan", json={"destination": "at", "start_at": start.isoformat(), "duration_minutes": 30})
    assert planned.status_code == 200
    body = planned.json()
    assert body["destination"] == "at"
    assert body["block"]["task_title"] == "Planbare taak"
    assert client.get(f"/api/mcp/task-suggestions?status=accepted").json()[0]["task_id"] == body["task_id"]
    assert client.post(f"/api/inbox/review/{created['id']}/plan", json={"destination": "inbox"}).status_code == 409
    undone = client.post("/api/planning/undo")
    assert undone.status_code == 200
    assert undone.json()["destination"] == "undone"
    assert client.get(f"/api/mcp/task-suggestions?status=pending").json()[0]["id"] == created["id"]
    assert all(item["id"] != body["task_id"] for item in client.get("/api/tasks").json())


def test_replan_is_explicit_idempotent_and_rejects_past_or_overlap(client):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(second=0, microsecond=0)
    task = client.post("/api/tasks", json={"title": "Replanbare taak", "next_action": {"text": "Open dossier"}}).json()
    block = client.post("/api/plan-blocks", json={"task_id": task["id"], "start_at": start.isoformat(), "end_at": (start + timedelta(minutes=30)).isoformat()}).json()
    same = client.post(f"/api/tasks/{task['id']}/replan", json={"destination": "at", "start_at": start.isoformat(), "duration_minutes": 30})
    assert same.status_code == 200 and same.json()["idempotent"] is True
    assert client.post(f"/api/tasks/{task['id']}/replan", json={"destination": "at", "start_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "duration_minutes": 30}).status_code == 422
    other = client.post("/api/tasks", json={"title": "Overlap", "next_action": {"text": "Blokkeer tijd"}}).json()
    client.post("/api/plan-blocks", json={"task_id": other["id"], "start_at": (start + timedelta(hours=1)).isoformat(), "end_at": (start + timedelta(hours=2)).isoformat()})
    assert client.post(f"/api/tasks/{task['id']}/replan", json={"destination": "at", "start_at": (start + timedelta(hours=1, minutes=15)).isoformat(), "duration_minutes": 30}).status_code == 409
    moved = client.post(f"/api/tasks/{task['id']}/replan", json={"destination": "inbox"})
    assert moved.status_code == 200 and moved.json()["block"] is None
    assert client.post(f"/api/tasks/{task['id']}/replan", json={"destination": "inbox"}).json()["idempotent"] is True
    assert client.post("/api/planning/undo").status_code == 200


def test_home_assistant_event_is_pending_and_mirror_is_limited(client):
    event = client.post("/api/ha/events", json={"title": "Afval", "action": "Zet de container buiten"}).json()
    assert event["status"] == "pending"
    mirror = client.get("/api/ha/todo-mirror").json()
    assert all(set(item) == {"task_id", "title", "status", "deadline", "current_action"} for item in mirror)
    ignored = client.post("/api/ha/events", json={"title": "Loop", "action": "Ignore me", "origin": "add"})
    assert ignored.status_code == 409


def test_home_assistant_event_is_idempotent_by_source_reference(client):
    payload = {"title": "Afval", "action": "Zet de container buiten", "source_ref": "ha-event-42"}
    first = client.post("/api/ha/events", json=payload)
    second = client.post("/api/ha/events", json={**payload, "title": "Gewijzigde retry"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["title"] == "Afval"
    assert len(client.get("/api/mcp/task-suggestions?status=pending").json()) == 1


def test_json_rpc_lists_tools_and_creates_pending_suggestion(client):
    listed = client.post("/api/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
    assert "execution_create_task_suggestion" in [tool["name"] for tool in listed["result"]["tools"]]
    assert "execution_start_action" in [tool["name"] for tool in listed["result"]["tools"]]
    created = client.post("/api/mcp/rpc", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "execution_create_task_suggestion", "arguments": {
            "title": "RPC taak", "suggested_next_action": "Open het document", "confidence": 0.7,
        }},
    }).json()
    assert created["result"]["content"][0]["json"]["status"] == "pending"


def test_mcp_endpoint_supports_execution_lifecycle(client):
    task = client.post("/api/tasks", json={"title": "RPC lifecycle", "next_action": {"text": "Do the step"}}).json()
    action = client.get("/api/now").json()
    started = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "execution_start_action", "arguments": {"action_id": action["id"]}}}).json()
    session_id = started["result"]["content"][0]["json"]["session_id"]
    finished = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "execution_complete_action", "arguments": {"session_id": session_id, "outcome": "done"}}}).json()
    assert finished["result"]["content"][0]["json"]["outcome"] == "done"


def test_mcp_invalid_tool_arguments_return_json_rpc_error(client):
    response = client.post("/api/mcp", json={
        "jsonrpc": "2.0", "id": 18, "method": "tools/call",
        "params": {"name": "execution_complete_action", "arguments": {"session_id": "missing-outcome"}},
    })
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


def test_active_session_can_be_restored_after_reload(client):
    client.post("/api/tasks", json={"title": "Herstelbare taak", "next_action": {"text": "Ga verder"}})
    action = client.get("/api/now").json()
    started = client.post(f"/api/actions/{action['id']}/start").json()
    assert started["started_at"]
    active = client.get("/api/sessions/active")
    assert active.status_code == 200
    assert active.json()["session_id"] == started["session_id"]
    assert active.json()["action"]["text"] == "Ga verder"


def test_mcp_handshake(client):
    initialized = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}}).json()
    assert initialized["result"]["serverInfo"]["name"] == "add-execution"
    assert set(initialized["result"]["capabilities"]) == {"tools", "resources", "prompts"}
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 19, "method": "ping"}).json()["result"] == {}
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 11, "method": "ping"}).json()["result"] == {}
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    schemas = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 14, "method": "tools/list"}).json()["result"]["tools"]
    search = next(tool for tool in schemas if tool["name"] == "execution_search_tasks")
    assert "q" in search["inputSchema"]["required"]
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 15, "method": "resources/list"}).json()["result"]["resources"] == []
    prompts = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 16, "method": "prompts/list"}).json()["result"]["prompts"]
    assert {prompt["name"] for prompt in prompts} == {"decompose_task", "draft_message", "resolve_stuck"}
    prompt = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 17, "method": "prompts/get", "params": {"name": "resolve_stuck", "arguments": {"action": "Open de brief"}}}).json()
    assert "Open de brief" in prompt["result"]["messages"][0]["content"]["text"]
    assert "{action}" not in prompt["result"]["messages"][0]["content"]["text"]


def test_mcp_authentication_when_token_is_configured(client, monkeypatch):
    from app.main import settings
    monkeypatch.setattr(settings, "add_api_token", "test-secret")
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 12, "method": "ping"}).status_code == 401
    assert client.post("/api/mcp", headers={"X-ADD-Token": "test-secret"}, json={"jsonrpc": "2.0", "id": 13, "method": "ping"}).status_code == 200


def test_home_assistant_sync_is_safe_when_not_configured(client):
    response = client.post("/api/ha/sync")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert client.get("/api/ha/outbox").json()[0]["status"] == "pending"


def test_home_assistant_context_is_query_based(client):
    client.post("/api/tasks", json={"title": "Korte actie", "next_action": {"text": "Open de brief", "estimated_minutes": 3, "energy": "low"}})
    response = client.get("/api/ha/now?is_home=true&energy=low&computer_available=true&max_minutes=5")
    assert response.status_code == 200
    assert response.json()["text"] == "Open de brief"


def test_home_assistant_poll_is_disabled_without_context_url(client):
    assert client.post("/api/ha/poll").json() == {"status": "disabled"}


def test_home_assistant_setup_rejects_invalid_endpoint(client):
    webhook = client.put("/api/ha/setup", json={"mode": "webhook", "webhook_url": "not-a-url"})
    poll = client.put("/api/ha/setup", json={"mode": "poll", "context_url": "ftp://ha.example/context"})
    assert webhook.status_code == 400
    assert poll.status_code == 400


def test_home_assistant_config_is_safe_and_describes_runtime_mode(client, monkeypatch):
    from app.main import settings
    monkeypatch.setattr(settings, "ha_webhook_url", "https://ha.example/webhook")
    monkeypatch.setattr(settings, "ha_context_url", "https://ha.example/context")
    monkeypatch.setattr(settings, "ha_webhook_token", "secret")
    response = client.get("/api/ha/config")
    assert response.json() == {
        "webhook_configured": True,
        "context_configured": True,
        "webhook_token_configured": True,
        "delivery_mode": "webhook",
        "poll_mode": "live",
    }
    assert "secret" not in response.text


def test_home_assistant_outbox_retry_delivers_stored_payload(client, monkeypatch):
    from app.main import settings
    client.post("/api/tasks", json={"title": "Mirror taak", "next_action": {"text": "Doe de stap"}})
    monkeypatch.setattr(settings, "ha_webhook_url", "https://ha.example/webhook")
    calls = []

    class Response:
        def raise_for_status(self): pass

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("content", kwargs.get("json"))))
        return Response()

    monkeypatch.setattr("app.main.httpx.post", fake_post)
    event = client.post("/api/ha/sync").json()
    assert event["status"] == "sent"
    listed = client.get("/api/ha/outbox").json()
    assert listed[0]["status"] == "delivered"
    assert client.post(f"/api/ha/outbox/{listed[0]['id']}/retry").status_code == 409
    assert len(calls) == 1


def test_blocked_action_resolver_can_create_prerequisite(client):
    client.post("/api/tasks", json={"title": "Te groot", "next_action": {"text": "Begin ermee"}})
    action = client.get("/api/now").json()
    session = client.post(f"/api/actions/{action['id']}/start").json()
    client.post(f"/api/sessions/{session['session_id']}/finish", json={"outcome": "stuck", "stuck_reason": "too_big"})
    response = client.post(f"/api/actions/{action['id']}/resolve", json={"resolution": "create_prerequisite", "prerequisite_title": "Kleinere voorbereiding", "prerequisite_action": "Open het dossier"})
    assert response.status_code == 200
    assert response.json()["prerequisite"]["title"] == "Kleinere voorbereiding"
    assert client.get("/api/actions?status=blocked").json()[0]["id"] == action["id"]


def test_message_draft_requires_explicit_send_confirmation(client):
    payload = {"recipient": "mijzelf", "body": "Ik pak dit vandaag op."}
    draft = client.post("/api/mcp/create-message-draft", json=payload)
    assert draft.json()["send_required"] is True
    assert client.post("/api/mcp/send-message", json=payload).status_code == 409
    sent = client.post("/api/mcp/send-message", json={**payload, "confirmed": True})
    assert sent.json()["status"] == "sent"


def test_diagnostics_exposes_safe_operational_status(client):
    response = client.get("/api/diagnostics")
    assert response.status_code == 200
    data = response.json()
    assert data["api"] == "ok"
    assert "today" in data and "integrations" in data
    assert "api_token_configured" in data["integrations"]


def test_credential_vault_check_never_returns_secret(client):
    saved = client.put("/api/security/credentials/gmail", json={"value": "top-secret"})
    assert saved.status_code == 200
    checked = client.get("/api/security/credentials/check")
    assert checked.json() == {"ok": True, "stored": 1, "readable": 1}
    assert "top-secret" not in checked.text


def test_quiet_reminder_preview_uses_context_selection(client):
    client.post("/api/tasks", json={"title": "Rustige taak", "next_action": {"text": "Open één document", "estimated_minutes": 3, "energy": "low"}})
    response = client.get("/api/reminders/preview?energy=low&max_minutes=5")
    assert response.json()["status"] == "ready"
    assert response.json()["action"]["text"] == "Open één document"


def test_reminder_provider_disabled_and_quiet_hours_are_visible(client):
    disabled = client.put("/api/reminder-settings", json={"provider": "browser", "enabled": False, "quiet_start": "22:00", "quiet_end": "07:00", "timezone": "Europe/Amsterdam"})
    assert disabled.status_code == 200
    assert client.get("/api/reminders/preview").json()["status"] == "provider_disabled"
    quiet = client.put("/api/reminder-settings", json={"provider": "browser", "enabled": True, "quiet_start": "00:00", "quiet_end": "23:59", "timezone": "Europe/Amsterdam"})
    assert quiet.status_code == 200
    assert client.get("/api/reminders/preview?at=2026-09-19T12:00:00Z").json()["status"] == "quiet_hours"


def test_routine_materialization_is_idempotent_and_keeps_provenance(client):
    routine = client.post("/api/routines", json={"title": "Dagstart", "action_text": "Open dagoverzicht", "recurrence": "daily", "local_time": "09:00", "timezone": "Europe/Amsterdam", "estimated_minutes": 10}).json()
    first = client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2030-01-02")
    second = client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2030-01-02")
    assert first.json()["status"] == "materialized"
    assert second.json()["status"] == "already_materialized"
    task = next(item for item in client.get("/api/tasks").json() if item["id"] == first.json()["task_id"])
    assert task["source_type"] == "routine"
    assert task["source_ref"].endswith(":2030-01-02")


def test_backup_export_contains_domain_collections(client):
    client.post("/api/tasks", json={"title": "Export taak", "planned_at": "2030-01-01T10:00:00Z", "tags": ["backup"], "priority": "high", "next_action": {"text": "Eerste stap"}})
    backup = client.get("/api/backup/export")
    assert backup.status_code == 200
    assert backup.json()["format"] == "add-backup"
    assert backup.json()["tasks"][0]["title"] == "Export taak"
    assert backup.json()["tasks"][0]["tags"] == ["backup"]
    assert backup.json()["tasks"][0]["priority"] == "high"
    assert set(backup.json()) == {"format", "version", "tasks", "actions", "sessions", "accountability", "completions", "suggestions", "outbox", "plan_blocks", "planning_decisions", "routines", "routine_occurrences", "reminder_preferences", "app_preferences", "smart_views"}


def test_backup_validation_is_non_mutating(client):
    response = client.post("/api/backup/validate", json={"format": "add-backup", "version": "0.1.0", "tasks": [], "actions": [], "sessions": [], "accountability": [], "completions": [], "suggestions": [], "outbox": []})
    assert response.json()["valid"] is True
    invalid = client.post("/api/backup/validate", json={"format": "other"})
    assert invalid.json()["valid"] is False


def test_backup_preview_is_explicitly_non_mutating(client):
    payload = {"format": "add-backup", "version": "0.1.0", "tasks": [{"id": "one"}], "actions": [], "sessions": [], "accountability": [], "completions": [], "suggestions": [], "outbox": []}
    response = client.post("/api/backup/preview", json=payload)
    assert response.json()["valid"] is True
    assert response.json()["will_mutate"] is False
    assert client.get("/api/tasks").json() == []


def test_backup_restore_requires_confirmation_and_replaces_data(client):
    client.post("/api/tasks", json={"title": "Oude taak", "next_action": {"text": "Oude stap"}})
    payload = {"format": "add-backup", "version": "0.1.0", "tasks": [], "actions": [], "sessions": [], "accountability": [], "completions": [], "suggestions": [], "outbox": []}
    assert client.post("/api/backup/restore", json=payload).status_code == 409
    restored = client.post("/api/backup/restore?confirmed=true", json=payload)
    assert restored.status_code == 200
    assert restored.json()["status"] == "restored"
    assert client.get("/api/tasks").json() == []


def test_completion_log_is_readable_for_audit(client):
    client.post("/api/tasks", json={"title": "Audit taak", "next_action": {"text": "Eerste stap"}})
    action = client.get("/api/now").json()
    session = client.post(f"/api/actions/{action['id']}/start").json()
    client.post(f"/api/sessions/{session['session_id']}/finish", json={"outcome": "done"})
    entries = client.get("/api/completions").json()
    assert entries[0]["outcome"] == "done"
    assert entries[0]["session_id"] == session["session_id"]
    assert entries[0]["task_title"] == "Audit taak"
    assert entries[0]["action_text"] == "Eerste stap"


def test_today_summary_reports_outcomes_and_open_work(client):
    client.post("/api/tasks", json={"title": "Samenvatting", "next_action": {"text": "Eerste stap"}})
    response = client.get("/api/today-summary")
    assert response.status_code == 200
    assert response.json()["headline"] == "Elke start telt."
    assert response.json()["ready"] == 1
    assert response.json()["done"] == 0


def test_today_summary_surfaces_next_open_deadline(client):
    client.post("/api/tasks", json={"title": "Deadline taak", "deadline": "2030-01-02T12:00:00Z", "next_action": {"text": "Open het dossier"}})
    response = client.get("/api/today-summary")
    assert response.json()["next_deadline_title"] == "Deadline taak"
    assert response.json()["next_deadline"].startswith("2030-01-02T12:00:00")


def test_today_summary_exposes_daily_limit_progress(client):
    client.post("/api/tasks", json={"title": "Belangrijk", "next_action": {"text": "Doe belangrijk werk", "estimated_minutes": 30}})
    action = client.get("/api/now").json()
    session = client.post(f"/api/actions/{action['id']}/start").json()
    client.post(f"/api/sessions/{session['session_id']}/finish", json={"outcome": "done"})
    summary = client.get("/api/today-summary").json()
    assert summary["important_done"] == 1
    assert summary["small_done"] == 0


def test_offline_completion_reports_conflict_without_overwriting_server_state(client):
    client.post("/api/tasks", json={"title": "Conflict taak", "next_action": {"text": "Serveractie"}})
    action = client.get("/api/actions?status=ready").json()[0]
    started = client.post(f"/api/actions/{action['id']}/start")
    assert started.status_code == 200
    conflict = client.post("/api/offline/complete", json={"action_id": action["id"], "outcome": "done", "started_at": datetime.now(timezone.utc).isoformat()})
    assert conflict.status_code == 409
    assert "offline conflict" in conflict.json()["detail"]
