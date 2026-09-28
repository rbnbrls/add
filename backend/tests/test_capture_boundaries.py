"""Inbox capture boundaries: provider-independent fallbacks and provider dedup."""

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.llm import LLMProviderError
from app.main import app, get_llm_gateway


class FailingGateway:
    """Provider double: the LLM is unavailable, so capture must degrade safely."""

    def generate_json(self, **kwargs):
        raise LLMProviderError("provider unavailable")


@pytest.fixture
def capture_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # Every route that would call the LLM gets the failing double: these tests
    # describe the offline behaviour and must never reach a provider.
    app.dependency_overrides[get_llm_gateway] = lambda: FailingGateway()
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()


def test_web_link_capture_rejects_a_missing_or_invalid_url(capture_client):
    client, _ = capture_client
    for source_ref in (None, "example.com/zonder-schema", "   ", "mailto:iemand@example.com"):
        payload = {"text": "Lees dit artikel", "source_type": "web_link", "source_ref": source_ref}
        assert client.post("/api/inbox/capture", json=payload).status_code == 422

    accepted = client.post("/api/inbox/capture", json={"text": "Lees dit artikel", "source_type": "web_link", "source_ref": "  https://example.com/probe  "})
    assert accepted.status_code == 200
    suggestion = accepted.json()["suggestion"]
    assert accepted.json()["mode"] == "parsed"
    assert suggestion["source_ref"] == "https://example.com/probe"
    assert suggestion["description"] == "Weblink: https://example.com/probe"


def test_brain_dump_falls_back_to_one_plain_text_proposal(capture_client):
    client, _ = capture_client

    response = client.post("/api/inbox/brain-dump", json={"text": "Bel de klant"})

    assert response.status_code == 200
    proposals = response.json()
    assert len(proposals) == 1
    assert proposals[0]["title"] == "Bel de klant"
    assert proposals[0]["suggested_next_action"] == "Bel de klant"
    assert proposals[0]["status"] == "pending" and proposals[0]["batch_id"]
    assert client.get("/api/mcp/task-suggestions?status=pending").json()[0]["id"] == proposals[0]["id"]


def test_capture_falls_back_to_plain_text_when_the_provider_is_down(capture_client):
    client, _ = capture_client

    response = client.post("/api/inbox/capture", json={"text": "Reken de declaratie in"})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "plain_text"
    assert body["suggestion"]["title"] == "Reken de declaratie in"
    assert body["suggestion"]["confidence"] == 0


def test_shortcut_capture_is_idempotent_without_an_idempotency_key(capture_client):
    client, _ = capture_client
    payload = {"text": "Boodschappen doen", "source_type": "shortcut"}

    first = client.post("/api/inbox/capture", json=payload)
    second = client.post("/api/inbox/capture", json=payload)

    digest = hashlib.sha256("Boodschappen doen".encode("utf-8")).hexdigest()
    assert first.status_code == 200 and first.json()["suggestion"]["source_ref"] == digest
    assert second.json()["suggestion"]["id"] == first.json()["suggestion"]["id"]
    assert len(client.get("/api/mcp/task-suggestions").json()) == 1

    explicit = client.post("/api/inbox/capture", json={**payload, "idempotency_key": "shortcut-abc"})
    assert explicit.json()["suggestion"]["source_ref"] == "shortcut-abc"


def test_voice_capture_is_deduplicated_on_the_provider_reference(capture_client):
    client, _ = capture_client
    payload = {"text": "Herhaal de oefening", "source_type": "voice_transcript", "source_ref": "voice-1"}

    first = client.post("/api/inbox/capture", json=payload)
    second = client.post("/api/inbox/capture", json={**payload, "text": "Herhaal de oefening nog eens"})

    assert first.status_code == 200
    assert second.json()["suggestion"]["id"] == first.json()["suggestion"]["id"]
    assert second.json()["suggestion"]["original_input"] == "Herhaal de oefening"
