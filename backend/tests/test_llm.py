import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base
from app.llm import (
    LLMConfigurationError,
    LLMGateway,
    LLMProviderError,
    LLMResponseError,
    LLMTimeoutError,
    OpenAICompatibleProvider,
)
from app.models import IntegrationCredential, Task
from app.security import credential_box


class Answer(BaseModel):
    answer: str
    score: int


class FakeProvider:
    def __init__(self, content: str = '{"answer":"ok","score":3}'):
        self.content = content
        self.calls = []

    def complete(self, *, model, messages, api_key):
        self.calls.append({"model": model, "messages": messages, "api_key": api_key})
        return self.content


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def config():
    return Settings(llm_base_url="http://localhost:11434/v1", llm_model="test-model", llm_timeout_seconds=2)


def store_key(db, value="secret-key"):
    db.add(IntegrationCredential(provider="llm", encrypted_value=credential_box().encrypt(value.encode()).decode()))
    db.commit()


def test_gateway_validates_json_and_builds_provider_request(db):
    store_key(db)
    provider = FakeProvider()
    result = LLMGateway(db, config(), provider).generate_json(
        system_prompt="Help with a task.", user_prompt="Say hello.", response_model=Answer
    )
    assert result == Answer(answer="ok", score=3)
    assert provider.calls[0]["model"] == "test-model"
    assert provider.calls[0]["api_key"] == "secret-key"
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert "JSON Schema" in provider.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("field", ["llm_base_url", "llm_model"])
def test_gateway_requires_configuration(db, field):
    store_key(db)
    values = {"llm_base_url": "http://localhost/v1", "llm_model": "model"}
    values[field] = ""
    with pytest.raises(LLMConfigurationError):
        LLMGateway(db, Settings(**values), FakeProvider()).generate_json(
            system_prompt="x", user_prompt="y", response_model=Answer
        )


def test_gateway_requires_credential_before_provider_call(db):
    provider = FakeProvider()
    with pytest.raises(LLMConfigurationError):
        LLMGateway(db, config(), provider).generate_json(system_prompt="x", user_prompt="y", response_model=Answer)
    assert provider.calls == []


@pytest.mark.parametrize("content", ["", "```json\n{\"answer\":\"ok\",\"score\":3}\n```", "not json"])
def test_gateway_rejects_non_plain_json(db, content):
    store_key(db)
    with pytest.raises(LLMResponseError):
        LLMGateway(db, config(), FakeProvider(content)).generate_json(
            system_prompt="x", user_prompt="y", response_model=Answer
        )


def test_gateway_rejects_schema_mismatch(db):
    store_key(db)
    with pytest.raises(LLMResponseError):
        LLMGateway(db, config(), FakeProvider('{"answer":"ok"}')).generate_json(
            system_prompt="x", user_prompt="y", response_model=Answer
        )


def test_gateway_does_not_write_domain_data(db):
    store_key(db)
    LLMGateway(db, config(), FakeProvider()).generate_json(system_prompt="x", user_prompt="y", response_model=Answer)
    assert db.scalars(select(Task)).all() == []


def test_provider_sends_openai_compatible_request(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok","score":3}'}}]})

    monkeypatch.setattr(httpx, "post", post)
    assert OpenAICompatibleProvider("http://localhost/v1", 5).complete(
        model="model", messages=[{"role": "user", "content": "x"}], api_key="secret"
    )
    assert captured["url"] == "http://localhost/v1/chat/completions"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer secret"
    assert captured["kwargs"]["json"]["temperature"] == 0


@pytest.mark.parametrize("exception", [httpx.TimeoutException("timeout"), httpx.ConnectError("offline")])
def test_provider_maps_network_failures(monkeypatch, exception):
    def post(*args, **kwargs):
        raise exception

    monkeypatch.setattr(httpx, "post", post)
    provider = OpenAICompatibleProvider("http://localhost/v1", 5)
    error = LLMTimeoutError if isinstance(exception, httpx.TimeoutException) else LLMProviderError
    with pytest.raises(error) as raised:
        provider.complete(model="model", messages=[], api_key="secret")
    assert "secret" not in str(raised.value)


def test_provider_hides_http_error_body(monkeypatch):
    def post(*args, **kwargs):
        return httpx.Response(500, text="top-secret provider response")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(LLMProviderError) as raised:
        OpenAICompatibleProvider("http://localhost/v1", 5).complete(model="model", messages=[], api_key="secret")
    assert "top-secret" not in str(raised.value)
    assert "secret" not in str(raised.value)
