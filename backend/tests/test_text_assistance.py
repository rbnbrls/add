from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import pytest

from app.db import Base, get_db
from app.llm import LLMProviderError, LLMResponseError, LLMTimeoutError
from app.main import app, get_llm_gateway
from app.models import Action, ExecutionSession, Task
from app.schemas import ToneAnalysisResponse, TextRewriteResponse


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
def text_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()


def test_rewrite_formal_uses_gateway_and_returns_typed_result(text_client):
    client, _ = text_client
    gateway = FakeGateway(result=TextRewriteResponse(text="Zou u dit vandaag kunnen bekijken?"))
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = client.post("/api/text/rewrite", json={"text": "Kun je dit vandaag bekijken?", "tone": "formal"})

    assert response.status_code == 200
    assert response.json() == {"text": "Zou u dit vandaag kunnen bekijken?"}
    assert gateway.calls[0]["response_model"] is TextRewriteResponse
    assert "Nederlands" in gateway.calls[0]["system_prompt"]
    assert "betekenis" in gateway.calls[0]["system_prompt"]
    assert "formal" in gateway.calls[0]["user_prompt"]


def test_rewrite_informal_is_supported(text_client):
    client, _ = text_client
    gateway = FakeGateway(result=TextRewriteResponse(text="Kun je dit vandaag bekijken?"))
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = client.post("/api/text/rewrite", json={"text": "Zou u dit vandaag kunnen bekijken?", "tone": "informal"})

    assert response.status_code == 200
    assert response.json()["text"] == "Kun je dit vandaag bekijken?"
    assert "informal" in gateway.calls[0]["user_prompt"]


def test_tone_analysis_returns_all_fields(text_client):
    client, _ = text_client
    gateway = FakeGateway(result=ToneAnalysisResponse(
        tone="ongeduldig maar zakelijk",
        emotion="frustratie",
        directness="direct",
        attention_point="De formulering kan verwijtend overkomen.",
    ))
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = client.post("/api/text/analyze", json={"text": "Ik wacht nu al drie weken op antwoord."})

    assert response.status_code == 200
    assert set(response.json()) == {"tone", "emotion", "directness", "attention_point"}
    assert gateway.calls[0]["response_model"] is ToneAnalysisResponse
    assert "niet-diagnostische" in gateway.calls[0]["system_prompt"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/text/rewrite", {"text": "   ", "tone": "formal"}),
        ("/api/text/rewrite", {"text": "x" * 4001, "tone": "formal"}),
        ("/api/text/rewrite", {"text": "tekst", "tone": "friendly"}),
        ("/api/text/analyze", {"text": "   "}),
        ("/api/text/analyze", {"text": "x" * 4001}),
    ],
)
def test_text_tools_validate_input(text_client, path, payload):
    client, _ = text_client
    assert client.post(path, json=payload).status_code == 422


@pytest.mark.parametrize("error", [LLMProviderError("provider details"), LLMTimeoutError("timeout"), LLMResponseError("raw response")])
def test_text_tools_map_expected_llm_errors_to_safe_503(text_client, error):
    client, _ = text_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(error=error)

    response = client.post("/api/text/analyze", json={"text": "Analyseer deze tekst."})

    assert response.status_code == 503
    assert response.json()["detail"] == "Teksthulp is tijdelijk niet beschikbaar."
    assert "provider" not in response.text
    assert "raw response" not in response.text


def test_text_tools_do_not_write_domain_data(text_client):
    client, session_factory = text_client
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=TextRewriteResponse(text="Resultaat"))

    assert client.post("/api/text/rewrite", json={"text": "Bron", "tone": "formal"}).status_code == 200
    with session_factory() as db:
        assert db.scalars(select(Task)).all() == []
        assert db.scalars(select(Action)).all() == []
        assert db.scalars(select(ExecutionSession)).all() == []


def test_text_tools_use_same_auth_boundary(text_client, monkeypatch):
    from app.main import settings

    client, _ = text_client
    monkeypatch.setattr(settings, "add_api_token", "text-secret")
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result=TextRewriteResponse(text="Resultaat"))

    assert client.post("/api/text/rewrite", json={"text": "Bron", "tone": "formal"}).status_code == 401
    assert client.post(
        "/api/text/rewrite",
        headers={"X-ADD-Token": "text-secret"},
        json={"text": "Bron", "tone": "formal"},
    ).status_code == 200
