from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.capture import parse_schedule
from app.llm import LLMConfigurationError, LLMProviderError, LLMTimeoutError
from app.main import app, get_llm_gateway
from app.models import Action, ActionStatus, SuggestionStatus, Task, TaskPriority, TaskStatus, TaskSuggestionRecord
from app.schemas import BrainDumpProposal, BrainDumpResult, NaturalLanguageCaptureResult, SuggestionEstimateResult


class FakeGateway:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def capture_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()


def parsed_result():
    return NaturalLanguageCaptureResult(
        title="Belastingaangifte doen",
        description="De aangifte voor 2025 afronden.",
        planned_at=datetime(2026, 9, 19, 10, tzinfo=timezone.utc),
        tags=["administratie", "werk"],
        suggested_next_action="Open de aangifteomgeving",
        confidence=0.86,
    )


def test_schedule_parser_resolves_dutch_relative_date_time_and_duration():
    parsed = parse_schedule("Plan overleg morgen om 15:00, 30 minuten", datetime(2026, 9, 19, 12, tzinfo=timezone.utc), "Europe/Amsterdam")
    assert parsed["status"] == "parsed"
    assert parsed["planned_at"] == datetime(2026, 9, 20, 13, tzinfo=timezone.utc)
    assert parsed["duration_minutes"] == 30


def test_schedule_parser_resolves_next_weekday_and_marks_conflict():
    parsed = parse_schedule("volgende dinsdag om 15:00", datetime(2026, 9, 21, 12, tzinfo=timezone.utc), "Europe/Amsterdam")
    assert parsed["planned_at"].astimezone(timezone.utc).weekday() == 1
    ambiguous = parse_schedule("morgen om 15:00 en woensdag om 16:00", datetime(2026, 9, 19, 12, tzinfo=timezone.utc), "Europe/Amsterdam")
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["planned_at"] is None
    assert ambiguous["notes"]


def test_schedule_parser_extracts_weekly_recurrence():
    parsed = parse_schedule("elke maandag om 09:00", datetime(2026, 9, 19, 12, tzinfo=timezone.utc), "Europe/Amsterdam")
    assert parsed["status"] == "parsed"
    assert parsed["recurrence"] == "weekly:0"


def test_capture_persists_schedule_metadata_without_creating_task(capture_client):
    client, session_factory = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(error=LLMProviderError("offline"))
    response = client.post("/api/inbox/capture", json={"text": "Plan overleg morgen om 15:00, 30 minuten", "source_type": "voice_transcript", "source_ref": "voice-1", "timezone": "Europe/Amsterdam"})
    assert response.status_code == 200
    suggestion = response.json()["suggestion"]
    assert suggestion["schedule_status"] == "parsed"
    assert suggestion["parsed_duration_minutes"] == 30
    assert suggestion["planned_at"].startswith("2026-")
    assert suggestion["source_type"] == "voice_transcript"
    with session_factory() as db:
        assert db.scalars(select(Task)).all() == []


def test_smart_views_are_bounded_read_only_and_timezone_aware(capture_client):
    client, session_factory = capture_client
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        overdue = Task(title="Overdue source task", status=TaskStatus.ACTIVE, source_type="gmail", priority=TaskPriority.HIGH, deadline=now.replace(microsecond=0))
        today = Task(title="Planned today", status=TaskStatus.ACTIVE, source_type="manual", planned_at=now, priority=TaskPriority.MEDIUM)
        blocked = Task(title="Blocked task", status=TaskStatus.ACTIVE, source_type="manual", priority=TaskPriority.LOW)
        db.add_all([overdue, today, blocked]); db.flush()
        db.add(Action(task_id=blocked.id, text="Resolve blocker", status=ActionStatus.BLOCKED))
        db.commit()

    created = client.post("/api/smart-views", json={"name": "Openstaande mail", "filters": {"overdue": True, "source": "gmail", "timezone": "Europe/Amsterdam"}})
    assert created.status_code == 200
    view = created.json()
    assert [item["title"] for item in client.get(f"/api/smart-views/{view['id']}/tasks").json()] == ["Overdue source task"]
    assert [item["title"] for item in client.get("/api/smart-views/query?blocked=true").json()] == ["Blocked task"]
    assert [item["title"] for item in client.get("/api/smart-views/query?period=today&timezone=Europe%2FAmsterdam").json()] == ["Planned today"]
    assert "Planned today" in [item["title"] for item in client.get("/api/smart-views/query?period=week&timezone=Europe%2FAmsterdam").json()]
    assert [item["title"] for item in client.get("/api/smart-views/query?priority=high").json()] == ["Overdue source task"]
    assert client.get("/api/smart-views/query?timezone=Not/AZone").status_code == 400

    for name in ("Today", "Unplanned"):
        assert client.post("/api/smart-views", json={"name": name, "filters": {"unplanned": True}}).status_code == 200
    assert client.post("/api/smart-views", json={"name": "Fourth", "filters": {}}).status_code == 409
    assert client.get("/api/backup/export").json()["smart_views"][0]["name"] == "Openstaande mail"


def test_daily_review_exposes_one_next_decision_without_mutating_state(capture_client):
    client, session_factory = capture_client
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        db.add(TaskSuggestionRecord(title="Review voorstel", source_type="shortcut", original_input="Review", suggested_next_action="Open", confidence=0.8, status=SuggestionStatus.PENDING))
        db.add(Task(title="Ongepland werk", status=TaskStatus.INBOX, source_type="manual"))
        db.commit()
    response = client.get("/api/daily-review?timezone=Europe%2FAmsterdam")
    assert response.status_code == 200
    body = response.json()
    assert body["next_decision"] == "review"
    assert body["next_href"] == "/review"
    assert body["open_proposals"][0]["title"] == "Review voorstel"
    assert body["unplanned_inbox"][0]["title"] == "Ongepland werk"
    assert len(client.get("/api/tasks").json()) == 1


def test_widget_read_model_is_read_only_and_points_to_existing_funnels(capture_client):
    client, _ = capture_client
    response = client.get("/api/widget")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["capture_url"] == "/intake?quick=1"
    assert body["review_url"] == "/review"
    assert body["execute_url"] == "/execute"
    assert client.get("/api/tasks").json() == []


def test_natural_language_capture_stores_parsed_pending_proposal(capture_client):
    client, session_factory = capture_client
    gateway = FakeGateway(result=parsed_result())
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = client.post("/api/inbox/capture", json={"text": "  Belasting morgen doen #werk  "})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "parsed"
    assert body["suggestion"]["status"] == "pending"
    assert body["suggestion"]["original_input"] == "Belasting morgen doen #werk"
    assert body["suggestion"]["tags"] == ["administratie", "werk"]
    assert len(gateway.calls) == 1
    with session_factory() as db:
        assert len(db.scalars(select(Task)).all()) == 0


def test_approval_copies_f3_metadata_to_task_and_action(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=parsed_result())
    created = client.post("/api/inbox/capture", json={"text": "Aangifte doen"}).json()["suggestion"]

    approved = client.post(f"/api/mcp/task-suggestions/{created['id']}/approve")

    assert approved.status_code == 200
    task = approved.json()
    assert task["planned_at"].startswith("2026-09-19T10:00:00")
    assert task["tags"] == ["administratie", "werk"]
    assert task["source_type"] == "natural_language"
    assert task["children"] == []
    assert client.get("/api/actions").json()[0]["text"] == "Open de aangifteomgeving"


def test_reject_does_not_create_task_or_action(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=parsed_result())
    created = client.post("/api/inbox/capture", json={"text": "Niet doen"}).json()["suggestion"]

    assert client.post(f"/api/mcp/task-suggestions/{created['id']}/reject").status_code == 200
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/actions").json() == []
    assert client.post(f"/api/mcp/task-suggestions/{created['id']}/reject").status_code == 409


@pytest.mark.parametrize("error", [LLMConfigurationError("missing"), LLMTimeoutError("timeout"), LLMProviderError("offline")])
def test_capture_falls_back_to_plain_text_for_known_llm_failure(capture_client, error):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(error=error)

    response = client.post("/api/inbox/capture", json={"text": "  Belangrijk document openen en lezen  "})

    body = response.json()
    assert body["mode"] == "plain_text"
    assert body["suggestion"]["original_input"] == "Belangrijk document openen en lezen"
    assert body["suggestion"]["title"] == "Belangrijk document openen en lezen"
    assert body["suggestion"]["confidence"] == 0
    assert body["suggestion"]["tags"] == []


def test_capture_does_not_hide_unexpected_errors(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(error=RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        client.post("/api/inbox/capture", json={"text": "Onverwachte fout"})


def test_capture_rejects_blank_and_oversized_input(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=parsed_result())
    assert client.post("/api/inbox/capture", json={"text": "   "}).status_code == 422
    assert client.post("/api/inbox/capture", json={"text": "x" * 4001}).status_code == 422


def test_shortcut_capture_is_idempotent_and_keeps_source(capture_client):
    client, session_factory = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(error=LLMProviderError("offline"))

    first = client.post("/api/inbox/capture", json={"text": "Bel de tandarts", "source_type": "shortcut"})
    second = client.post("/api/inbox/capture", json={"text": "Bel de tandarts", "source_type": "shortcut"})

    assert first.status_code == second.status_code == 200
    assert first.json()["suggestion"]["id"] == second.json()["suggestion"]["id"]
    assert first.json()["suggestion"]["source_type"] == "shortcut"
    with session_factory() as db:
        assert len(db.scalars(select(TaskSuggestionRecord)).all()) == 1


def test_web_link_capture_validates_and_deduplicates_url(capture_client):
    client, _ = capture_client
    payload = {"text": "Lees het artikel", "source_type": "web_link", "source_ref": "https://example.com/article"}

    first = client.post("/api/inbox/capture", json=payload)
    second = client.post("/api/inbox/capture", json=payload)
    invalid = client.post("/api/inbox/capture", json={**payload, "source_ref": "javascript:alert(1)"})

    assert first.status_code == second.status_code == 200
    assert first.json()["suggestion"]["id"] == second.json()["suggestion"]["id"]
    assert first.json()["suggestion"]["source_ref"] == payload["source_ref"]
    assert "Open de link" in first.json()["suggestion"]["suggested_next_action"]
    assert invalid.status_code == 422


def test_capture_preserves_old_suggestion_backup_shape(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=parsed_result())
    client.post("/api/inbox/capture", json={"text": "Backup deze capture"})
    backup = client.get("/api/backup/export").json()
    assert backup["suggestions"][0]["original_input"] == "Backup deze capture"
    assert backup["suggestions"][0]["tags"] == ["administratie", "werk"]


def test_capture_backup_restore_round_trips_f3_fields(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=parsed_result())
    client.post("/api/inbox/capture", json={"text": "Herstel deze capture"})
    backup = client.get("/api/backup/export").json()

    restored = client.post("/api/backup/restore?confirmed=true", json=backup)

    assert restored.status_code == 200
    suggestion = client.get("/api/mcp/task-suggestions?status=pending").json()[0]
    assert suggestion["original_input"] == "Herstel deze capture"
    assert suggestion["planned_at"].startswith("2026-09-19T10:00:00")
    assert suggestion["tags"] == ["administratie", "werk"]


def test_brain_dump_creates_independent_batched_pending_proposals(capture_client):
    client, session_factory = capture_client
    gateway = FakeGateway(result=BrainDumpResult(proposals=[
        BrainDumpProposal(title="Bel de klant", suggested_next_action="Open de telefoon", confidence=.9),
        BrainDumpProposal(title="Stuur verslag", suggested_next_action="Open het verslag", confidence=.8),
    ]))
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = client.post("/api/inbox/brain-dump", json={"text": "Klant bellen en verslag sturen"})

    assert response.status_code == 200
    proposals = response.json()
    assert len(proposals) == 2
    assert len({proposal["batch_id"] for proposal in proposals}) == 1
    assert all(proposal["original_input"] == "Klant bellen en verslag sturen" for proposal in proposals)
    assert client.get("/api/inbox/review").json()["id"] == proposals[0]["id"]
    with session_factory() as db:
        assert db.scalars(select(Task)).all() == []


def test_brain_dump_proposals_are_decided_independently(capture_client):
    client, _ = capture_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=BrainDumpResult(proposals=[
        BrainDumpProposal(title="Eerste", suggested_next_action="Doe eerste", confidence=.9),
        BrainDumpProposal(title="Tweede", suggested_next_action="Doe tweede", confidence=.8),
    ]))
    created = client.post("/api/inbox/brain-dump", json={"text": "Twee punten"}).json()

    approved = client.post(f"/api/mcp/task-suggestions/{created[0]['id']}/approve", json={"estimated_minutes": 25})
    rejected = client.post(f"/api/mcp/task-suggestions/{created[1]['id']}/reject")

    assert approved.status_code == 200
    assert rejected.status_code == 200
    assert client.get("/api/inbox/review").status_code == 404
    assert client.get("/api/actions").json()[0]["estimated_minutes"] == 25


def test_estimate_is_advisory_until_approval_and_can_be_overwritten(capture_client):
    client, _ = capture_client
    gateway = FakeGateway(result=SuggestionEstimateResult(estimated_minutes=40))
    app.dependency_overrides[get_llm_gateway] = lambda: gateway
    created = client.post("/api/mcp/task-suggestions", json={"title": "Werk", "suggested_next_action": "Open dossier", "confidence": .7}).json()

    estimated = client.post(f"/api/inbox/review/{created['id']}/estimate")
    assert estimated.status_code == 200
    assert estimated.json()["suggested_estimated_minutes"] == 40
    assert client.get("/api/actions").json() == []

    approved = client.post(f"/api/mcp/task-suggestions/{created['id']}/approve", json={"estimated_minutes": 15})
    assert approved.status_code == 200
    assert client.get("/api/actions").json()[0]["estimated_minutes"] == 15
