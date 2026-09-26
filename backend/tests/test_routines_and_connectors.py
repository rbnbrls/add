"""Routine scheduling rules and connector intake deduplication."""

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


def create_routine(client, **overrides):
    payload = {"title": "Weekstart", "action_text": "Open het weekoverzicht", "recurrence": "weekly", "weekday": 0, "local_time": "09:00", "timezone": "Europe/Amsterdam"}
    return client.post("/api/routines", json={**payload, **overrides})


def test_routine_schedule_validation(client):
    assert create_routine(client, recurrence="weekly", weekday=None).status_code == 422
    assert create_routine(client, recurrence="specific_day", weekday=None).status_code == 422
    assert create_routine(client, timezone="Not/AZone").status_code == 422
    assert create_routine(client, local_time="9:00").status_code == 422

    routine = create_routine(client).json()
    assert [item["id"] for item in client.get("/api/routines").json()] == [routine["id"]]


def test_weekly_routine_materializes_once_on_its_weekday(client):
    routine = create_routine(client).json()

    # 2027-03-01 is a Monday, 2027-03-02 is not.
    assert client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2027-03-02").json() == {"status": "not_due", "task": None}
    assert client.post("/api/routines/missing/materialize").status_code == 404

    materialized = client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2027-03-01").json()
    assert materialized["status"] == "materialized"
    task = next(item for item in client.get("/api/tasks").json() if item["id"] == materialized["task_id"])
    assert task["source_type"] == "routine" and task["planned_at"] is not None
    assert task["source_ref"] == f"{routine['id']}:2027-03-01"

    again = client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2027-03-01").json()
    assert again == {"status": "already_materialized", "task_id": task["id"]}


def test_specific_day_routine_only_materializes_on_its_date(client):
    routine = create_routine(client, recurrence="specific_day", weekday=None, specific_date="2027-03-01").json()

    assert client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2027-03-02").json()["status"] == "not_due"
    assert client.post(f"/api/routines/{routine['id']}/materialize?occurrence_date=2027-03-01").json()["status"] == "materialized"


def test_reminder_settings_round_trip_and_validate_timezone(client):
    assert client.get("/api/reminder-settings").json()["provider"] == "none"
    assert client.put("/api/reminder-settings", json={"timezone": "Not/AZone"}).status_code == 422

    saved = client.put("/api/reminder-settings", json={"provider": "ha", "enabled": True, "quiet_start": "23:00", "quiet_end": "06:30", "timezone": "Europe/Amsterdam"})
    assert saved.status_code == 200 and saved.json()["provider"] == "ha"
    assert client.get("/api/reminder-settings").json()["quiet_start"] == "23:00"


def test_calendar_and_whatsapp_intake_deduplicate_provider_identifiers(client):
    event = {"event_id": "evt-1", "title": "Overleg", "start": "2027-03-01T09:00:00+00:00", "location": "Kantoor"}
    first = client.post("/api/connectors/calendar/intake", json=event)
    retry = client.post("/api/connectors/calendar/intake", json={**event, "title": "Gewijzigde retry"})

    assert first.status_code == 200
    assert retry.json()["id"] == first.json()["id"] and retry.json()["title"] == "Overleg"
    assert first.json()["source_type"] == "calendar" and first.json()["deadline"] is not None

    message = {"message_id": "wamid-1", "sender": "Ruben", "message": "Bel mij terug"}
    whatsapp = client.post("/api/connectors/whatsapp/intake", json=message)
    whatsapp_retry = client.post("/api/connectors/whatsapp/intake", json={**message, "message": "retry"})

    assert whatsapp.json()["title"] == "WhatsApp van Ruben"
    assert whatsapp_retry.json()["id"] == whatsapp.json()["id"]
    # A provider payload without an identifier stays an independent proposal.
    anonymous = client.post("/api/connectors/whatsapp/intake", json={"sender": "Ruben", "message": "Bel mij terug"})
    assert anonymous.json()["id"] != whatsapp.json()["id"]
