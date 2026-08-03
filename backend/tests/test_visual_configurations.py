from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from unittest.mock import MagicMock

from app.api.deps import get_db_session
from app.core.config import settings
from app.main import create_app
from app.models import VisualConfiguration, VisualConfigurationVersion
from app.schemas.auth import UserCreate
from app.schemas.visual_configuration import VisualConfigurationCreate, VisualDocument
from app.services.visual_configuration_service import VisualConfigurationService
from app.services.user_service import UserService
from tests.conftest import TestingSessionLocal

PASSWORD = "test-password"


@pytest.fixture()
def client():
    app = create_app()
    def db_override():
        db = TestingSessionLocal()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db_session] = db_override
    with TestClient(app, backend_options={"use_uvloop": True}) as value: yield value


def create_user(db, username, pending=False):
    user = UserService(db).create(UserCreate(username=username, password=PASSWORD, role="user"))
    user.must_change_password = pending; db.commit(); db.refresh(user); return user


def login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return {"X-CSRF-Token": client.cookies.get(settings.auth_csrf_cookie_name)}


def document(enabled=False):
    return {"schema_version": 1, "visual_rules": {"enabled": enabled, "selectedSeriesInstanceId": None, "bySeries": {}}}


def test_visual_document_accepts_complete_sidebar_state_and_keeps_old_documents():
    old = VisualDocument.model_validate(document())
    complete_payload = document()
    complete_payload["sidebar_state"] = {
        "filters": {"timePeriod": {"kind": "preset", "preset": "PT1H"}, "timezone": "America/Sao_Paulo"},
        "selectedTagIds": [2, 1],
        "seriesAssignments": [],
        "metricConfiguration": {"kind": "none"},
        "comparison": {"type": "disabled"},
    }
    complete = VisualDocument.model_validate(complete_payload)
    assert old.sidebar_state is None
    assert complete.model_dump()["sidebar_state"]["selectedTagIds"] == [2, 1]


def test_create_rolls_back_if_initial_version_transaction_fails():
    db = MagicMock(); db.commit.side_effect = RuntimeError("commit failed")
    user = MagicMock(id="owner-id")
    payload = VisualConfigurationCreate(name="Atomica", document=VisualDocument.model_validate(document()))
    with pytest.raises(RuntimeError, match="commit failed"):
        VisualConfigurationService(db, user).create(payload)
    assert db.add.call_count == 2
    db.rollback.assert_called_once_with()


def test_create_update_history_restore_and_conflict(client, db_session):
    create_user(db_session, "owner"); headers = login(client, "owner")
    created = client.post("/api/visual-configurations", headers=headers, json={"name": "Minha configuração", "document": document()})
    assert created.status_code == 201 and created.json()["current_version"] == 1
    config_id = created.json()["id"]
    assert "owner_id" not in created.json()
    updated = client.put(f"/api/visual-configurations/{config_id}", headers=headers, json={"expected_version": 1, "document": document(True)})
    assert updated.status_code == 200 and updated.json()["current_version"] == 2
    conflict = client.put(f"/api/visual-configurations/{config_id}", headers=headers, json={"expected_version": 1, "document": document()})
    assert conflict.status_code == 409
    history = client.get(f"/api/visual-configurations/{config_id}/history").json()
    assert [item["version"] for item in history] == [2, 1]
    restored = client.post(f"/api/visual-configurations/{config_id}/restore", headers=headers, json={"expected_version": 2, "version": 1})
    assert restored.status_code == 200 and restored.json()["current_version"] == 3
    assert restored.json()["document"]["visual_rules"]["enabled"] is False


def test_ownership_is_derived_and_other_users_see_not_found(client, db_session):
    create_user(db_session, "alice"); create_user(db_session, "bob")
    headers = login(client, "alice")
    assert client.post("/api/visual-configurations", headers=headers, json={"name": "bad", "owner_id": "forged", "document": document()}).status_code == 422
    created = client.post("/api/visual-configurations", headers=headers, json={"name": "Alice", "document": document()}).json()
    headers = login(client, "bob")
    assert client.get("/api/visual-configurations").json() == []
    assert client.get(f"/api/visual-configurations/{created['id']}").status_code == 404
    assert client.put(f"/api/visual-configurations/{created['id']}", headers=headers, json={"expected_version": 1, "document": document(True)}).status_code == 404
    assert client.get(f"/api/visual-configurations/{created['id']}/history").status_code == 404
    assert client.get(f"/api/visual-configurations/{created['id']}/history/1").status_code == 404
    assert client.post(f"/api/visual-configurations/{created['id']}/rename", headers=headers, json={"expected_version": 1, "name": "Invadida"}).status_code == 404
    assert client.post(f"/api/visual-configurations/{created['id']}/restore", headers=headers, json={"expected_version": 1, "version": 1}).status_code == 404
    assert client.delete(f"/api/visual-configurations/{created['id']}", headers=headers).status_code == 404


def test_limits_rename_and_pending_password_block(client, db_session):
    create_user(db_session, "owner"); headers = login(client, "owner")
    assert client.post("/api/visual-configurations", headers=headers, json={"name": "x" * 101, "document": document()}).status_code == 422
    created = client.post("/api/visual-configurations", headers=headers, json={"name": "Original", "document": document()}).json()
    renamed = client.post(f"/api/visual-configurations/{created['id']}/rename", headers=headers, json={"expected_version": 1, "name": "Renomeada"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renomeada" and renamed.json()["current_version"] == 2
    create_user(db_session, "pending", pending=True); login(client, "pending")
    blocked = client.get("/api/visual-configurations")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_owner_deletes_configuration_and_all_versions(client, db_session):
    create_user(db_session, "owner-delete"); headers = login(client, "owner-delete")
    deleted = client.post("/api/visual-configurations", headers=headers, json={"name": "Excluir", "document": document()}).json()
    kept = client.post("/api/visual-configurations", headers=headers, json={"name": "Manter", "document": document()}).json()
    client.put(f"/api/visual-configurations/{deleted['id']}", headers=headers, json={"expected_version": 1, "document": document(True)})

    response = client.delete(f"/api/visual-configurations/{deleted['id']}", headers=headers)

    assert response.status_code == 204 and response.content == b""
    assert client.get(f"/api/visual-configurations/{deleted['id']}").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(VisualConfiguration).where(VisualConfiguration.id == deleted["id"])) == 0
    assert db_session.scalar(select(func.count()).select_from(VisualConfigurationVersion).where(VisualConfigurationVersion.configuration_id == deleted["id"])) == 0
    assert db_session.scalar(select(func.count()).select_from(VisualConfiguration).where(VisualConfiguration.id == kept["id"])) == 1
    assert db_session.scalar(select(func.count()).select_from(VisualConfigurationVersion).where(VisualConfigurationVersion.configuration_id == kept["id"])) == 1


def test_other_user_and_missing_configuration_return_not_found_on_delete(client, db_session):
    assert client.delete("/api/visual-configurations/qualquer-id").status_code == 401
    create_user(db_session, "delete-alice"); create_user(db_session, "delete-bob")
    headers = login(client, "delete-alice")
    created = client.post("/api/visual-configurations", headers=headers, json={"name": "Alice", "document": document()}).json()
    headers = login(client, "delete-bob")

    assert client.delete(f"/api/visual-configurations/{created['id']}", headers=headers).status_code == 404
    assert client.delete("/api/visual-configurations/nao-existe", headers=headers).status_code == 404
    assert db_session.scalar(select(func.count()).select_from(VisualConfiguration).where(VisualConfiguration.id == created["id"])) == 1
    assert db_session.scalar(select(func.count()).select_from(VisualConfigurationVersion).where(VisualConfigurationVersion.configuration_id == created["id"])) == 1
