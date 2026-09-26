"""Local account and credential-store access control."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import IntegrationCredential

PASSWORD = "een-lang-genoeg-wachtwoord"


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
        yield test_client, session_factory
    app.dependency_overrides.clear()


def test_local_login_gates_the_credential_store(client):
    http, session_factory = client
    status = http.get("/api/auth/status").json()
    assert status["enabled"] is False and status["authenticated"] is True

    assert http.post("/api/auth/setup", json={"password": "te-kort"}).status_code == 400
    assert http.post("/api/auth/setup", json={"password": PASSWORD}).json() == {"configured": True}
    assert http.post("/api/auth/setup", json={"password": PASSWORD}).status_code == 409

    assert http.get("/api/auth/status").json() == {
        "enabled": True, "login_configured": True,
        "encryption_configured": bool(settings.credential_encryption_key), "authenticated": False,
    }
    assert http.get("/api/security/credentials").status_code == 401
    assert http.post("/api/auth/login", json={"password": "verkeerd-wachtwoord"}).status_code == 401
    assert http.post("/api/auth/login", json={"password": PASSWORD}).json() == {"authenticated": True, "enabled": True}

    assert http.get("/api/security/credentials").json() == []
    saved = http.put("/api/security/credentials/llm", json={"value": "sk-probe-value"})
    assert saved.status_code == 200
    assert saved.json()["stored"] is True and saved.json()["masked"] == "••••••••"
    assert [item["provider"] for item in http.get("/api/security/credentials").json()] == ["llm"]
    assert http.get("/api/security/credentials/check").json() == {"ok": True, "stored": 1, "readable": 1}
    with session_factory() as db:
        stored = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == "llm"))
        assert stored is not None and stored.encrypted_value != "sk-probe-value"

    assert http.put("/api/security/credentials/llm", json={"value": ""}).status_code == 400
    assert http.post("/api/auth/logout").json() == {"authenticated": False}
    assert http.get("/api/security/credentials").status_code == 401
    assert http.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
    assert http.delete("/api/security/credentials/llm").json() == {"provider": "llm", "deleted": True}
    assert http.delete("/api/security/credentials/llm").status_code == 404


def test_credentials_that_cannot_be_decrypted_are_reported_as_not_ok(client):
    http, session_factory = client
    with session_factory() as db:
        db.add(IntegrationCredential(provider="broken", encrypted_value="not-a-fernet-token"))
        db.commit()

    assert http.get("/api/security/credentials/check").json() == {"ok": False, "stored": 1, "readable": 0}
    assert [item["provider"] for item in http.get("/api/security/credentials").json()] == ["broken"]


def test_api_token_path_is_enforced_when_a_token_is_configured(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(settings, "add_api_token", "probe-api-token")

    assert http.get("/api/security/credentials").status_code == 401
    authorised = http.get("/api/security/credentials", headers={"X-Add-Token": "probe-api-token"})
    assert authorised.status_code == 200 and authorised.json() == []
