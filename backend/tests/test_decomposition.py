from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app, get_llm_gateway
from app.models import Action, Task
from app.schemas import DecompositionResult, DecompositionChild


class FakeGateway:
    def __init__(self, result):
        self.result = result

    def generate_json(self, **kwargs):
        return self.result


def result(*titles):
    return DecompositionResult(children=[DecompositionChild(title=title) for title in titles])


def client_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session_factory


def test_decomposition_is_pending_until_approved():
    client, session_factory = client_fixture()
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Open het dossier", "Verzamel de documenten", "Controleer de gegevens"))
    try:
        parent = client.post("/api/tasks", json={"title": "Aangifte afronden"}).json()
        proposal = client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 3})
        assert proposal.status_code == 200
        assert proposal.json()["status"] == "pending"
        assert len(proposal.json()["items"]) == 3
        assert client.get("/api/tasks").json()[0]["children"] == []

        approved = client.post(f"/api/decompositions/{proposal.json()['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["proposal"]["status"] == "accepted"
        assert len(approved.json()["tasks"]) == 3
        assert all(task["parent_id"] == parent["id"] for task in approved.json()["tasks"])
        assert client.get("/api/actions").json() == []
        with session_factory() as db:
            assert db.scalars(select(Action)).all() == []
    finally:
        app.dependency_overrides.clear()


def test_reject_and_repeat_decision_are_safe():
    client, _ = client_fixture()
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Eerste stap", "Tweede stap"))
    try:
        parent = client.post("/api/tasks", json={"title": "Groot werk"}).json()
        proposal = client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 2}).json()
        assert client.post(f"/api/decompositions/{proposal['id']}/reject").status_code == 200
        assert client.post(f"/api/decompositions/{proposal['id']}/reject").status_code == 409
        assert client.get("/api/tasks").json()[0]["children"] == []
    finally:
        app.dependency_overrides.clear()


def test_only_checked_decomposition_items_are_approved():
    client, _ = client_fixture()
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Eerste stap", "Tweede stap", "Derde stap"))
    try:
        parent = client.post("/api/tasks", json={"title": "Groot werk"}).json()
        proposal = client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 3}).json()
        selected = [proposal["items"][0]["id"], proposal["items"][2]["id"]]
        approved = client.post(f"/api/decompositions/{proposal['id']}/approve", json={"item_ids": selected})
        assert approved.status_code == 200
        assert [task["title"] for task in approved.json()["tasks"]] == ["Eerste stap", "Derde stap"]
    finally:
        app.dependency_overrides.clear()


def test_invalid_count_and_duplicate_llm_output_are_rejected():
    client, _ = client_fixture()
    try:
        parent = client.post("/api/tasks", json={"title": "Groot werk"}).json()
        app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Een", "Twee"))
        assert client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 3}).status_code == 503
        app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Een", "Een"))
        assert client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 2}).status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_existing_child_is_not_proposed_twice():
    client, _ = client_fixture()
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Bestaand", "Nieuw"))
    try:
        parent = client.post("/api/tasks", json={"title": "Parent"}).json()
        existing = client.post("/api/tasks", json={"title": " Bestaand ", "parent_id": parent["id"]}).json()
        proposal = client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 2}).json()
        assert [item["title"] for item in proposal["items"]] == ["Nieuw"]
        approved = client.post(f"/api/decompositions/{proposal['id']}/approve").json()
        assert [task["title"] for task in approved["tasks"]] == ["Nieuw"]
        assert existing["id"] != approved["tasks"][0]["id"]
    finally:
        app.dependency_overrides.clear()


def test_decomposition_backup_round_trip():
    client, _ = client_fixture()
    app.dependency_overrides[get_llm_gateway] = lambda: FakeGateway(result("Eerste", "Tweede"))
    try:
        parent = client.post("/api/tasks", json={"title": "Backup parent"}).json()
        proposal = client.post(f"/api/tasks/{parent['id']}/decompositions", json={"child_count": 2}).json()
        backup = client.get("/api/backup/export").json()
        assert "decompositions" in backup
        assert backup["decompositions"][0]["id"] == proposal["id"]
        assert client.post("/api/backup/restore?confirmed=true", json=backup).status_code == 200
        assert client.get(f"/api/tasks/{parent['id']}/decompositions").json()[0]["id"] == proposal["id"]
    finally:
        app.dependency_overrides.clear()
