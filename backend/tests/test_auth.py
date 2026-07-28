from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
import importlib
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.config import settings
from app.core.security import JWT_ALGORITHM, create_access_token, hash_password, verify_password
from app.main import create_app
from app.models import User, UserRole
from app.schemas.auth import UserCreate, UserUpdate
from app.services.user_service import UserService
from tests.conftest import TestingSessionLocal

PASSWORD = "test-password-123"
NEW_PASSWORD = "new-test-password-456"


@pytest.fixture()
def auth_client():
    app = create_app()
    def db_override():
        db = TestingSessionLocal()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db_session] = db_override
    with TestClient(app) as client: yield client


def create_user(db: Session, username="admin", role="admin", active=True, password=PASSWORD, pending=False):
    user = UserService(db).create(UserCreate(username=username, password=password, role=role, is_active=active))
    if not pending:
        user.must_change_password = False; db.commit(); db.refresh(user)
    return user


def login(client: TestClient, username="admin", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def csrf(client: TestClient): return {"X-CSRF-Token": client.cookies.get(settings.auth_csrf_cookie_name)}


def test_password_is_argon2_hash_only(db_session):
    user = create_user(db_session)
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.password_hash)


def test_password_length_boundaries_and_admin_value(db_session):
    user = create_user(db_session, username="five-char-admin", password="admin")
    assert user.password_hash.startswith("$argon2id$")
    assert user.password_hash != "admin"
    assert verify_password("admin", user.password_hash)
    with pytest.raises(ValueError):
        hash_password("1234")
    with pytest.raises(ValueError):
        hash_password("x" * 129)


def test_create_admin_cli_accepts_interactive_five_character_password(monkeypatch, db_session, capsys):
    cli = importlib.import_module("app.cli.__main__")
    answers = iter(["admin", "admin"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))
    assert cli.create_admin("admin") == 0
    user = db_session.query(User).filter(User.normalized_username == "admin").one()
    assert user.password_hash.startswith("$argon2id$") and user.password_hash != "admin"
    assert user.must_change_password is True
    assert "hash" not in capsys.readouterr().out.lower()


def test_password_limits_are_enforced_by_api_schemas(auth_client, db_session):
    create_user(db_session); login(auth_client)
    headers = csrf(auth_client)
    assert auth_client.post("/api/admin/users", headers=headers, json={"username": "short", "password": "1234", "role": "user"}).status_code == 422
    assert auth_client.post("/api/admin/users", headers=headers, json={"username": "long", "password": "x" * 129, "role": "user"}).status_code == 422


def test_first_admin_service_and_no_default_password(db_session):
    user = UserService(db_session).create_first_admin("root", PASSWORD)
    assert user.role == UserRole.ADMIN
    with pytest.raises(Exception): UserService(db_session).create_first_admin("other", PASSWORD)
    with pytest.raises(ValueError): hash_password("")


def test_login_me_logout_and_no_secret_fields(auth_client, db_session):
    create_user(db_session)
    response = login(auth_client)
    assert response.status_code == 200
    assert "password_hash" not in response.json() and "token" not in response.json()
    assert auth_client.cookies.get(settings.auth_cookie_name)
    me = auth_client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "admin"
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401


def test_invalid_credentials_equivalent_and_inactive(auth_client, db_session):
    create_user(db_session, active=False)
    missing = login(auth_client, "missing", "wrong-password")
    inactive = login(auth_client)
    assert (missing.status_code, missing.json()) == (inactive.status_code, inactive.json())


def test_missing_invalid_expired_unknown_and_old_tokens_return_401(auth_client, db_session):
    user = create_user(db_session)
    assert auth_client.get("/api/auth/me").status_code == 401
    auth_client.cookies.set(settings.auth_cookie_name, "invalid", path="/api")
    assert auth_client.get("/api/auth/me").status_code == 401
    secret = settings.auth_jwt_secret.get_secret_value()
    now = datetime.now(timezone.utc)
    for claims in [
        {"sub": user.id, "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1), "jti": "x", "auth_version": 1},
        {"sub": "missing", "iat": now, "exp": now + timedelta(hours=1), "jti": "x", "auth_version": 1},
        {"sub": user.id, "iat": now, "exp": now + timedelta(hours=1), "jti": "x", "auth_version": 999},
    ]:
        auth_client.cookies.set(settings.auth_cookie_name, jwt.encode(claims, secret, algorithm=JWT_ALGORITHM), path="/api")
        assert auth_client.get("/api/auth/me").status_code == 401


def test_business_routes_require_auth(auth_client):
    assert auth_client.get("/api/equipments").status_code == 401
    assert auth_client.get("/api/time-series", params={"tag_ids": 1, "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-01T01:00:00Z"}).status_code == 401
    assert auth_client.get("/api/health").status_code == 200


def test_admin_crud_authorization_and_casefold_conflict(auth_client, db_session):
    create_user(db_session); create_user(db_session, "common", "user")
    assert login(auth_client, "common").status_code == 200
    assert auth_client.get("/api/admin/users").status_code == 403
    login(auth_client)
    headers = csrf(auth_client)
    created = auth_client.post("/api/admin/users", headers=headers, json={"username": "NewUser", "password": PASSWORD, "role": "user", "is_active": True})
    assert created.status_code == 201
    assert auth_client.post("/api/admin/users", headers=headers, json={"username": "newuser", "password": PASSWORD, "role": "user"}).status_code == 409
    user_id = created.json()["id"]
    assert auth_client.put(f"/api/admin/users/{user_id}", headers=headers, json={"username": "renamed", "role": "admin"}).status_code == 200
    assert auth_client.post(f"/api/admin/users/{user_id}/deactivate", headers=headers).status_code == 200
    assert auth_client.post(f"/api/admin/users/{user_id}/activate", headers=headers).status_code == 200
    assert auth_client.post(f"/api/admin/users/{user_id}/reset-password", headers=headers, json={"new_password": NEW_PASSWORD}).status_code == 200


def test_payload_forbids_security_fields(auth_client, db_session):
    create_user(db_session); login(auth_client)
    payload = {"username": "bad", "password": PASSWORD, "role": "user", "password_hash": "x", "auth_version": 1}
    assert auth_client.post("/api/admin/users", headers=csrf(auth_client), json=payload).status_code == 422


def test_change_password_invalidates_previous_token(auth_client, db_session):
    create_user(db_session); login(auth_client)
    old = auth_client.cookies.get(settings.auth_cookie_name)
    assert auth_client.put("/api/auth/change-password", headers=csrf(auth_client), json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}).status_code == 200
    auth_client.cookies.set(settings.auth_cookie_name, old, path="/api")
    assert auth_client.get("/api/auth/me").status_code == 401
    assert login(auth_client, password=NEW_PASSWORD).status_code == 200


def test_deactivation_invalidates_token_and_reactivation_allows_login(auth_client, db_session):
    admin = create_user(db_session); target = create_user(db_session, "target", "user")
    login(auth_client, "target"); target_token = auth_client.cookies.get(settings.auth_cookie_name)
    login(auth_client); headers = csrf(auth_client)
    auth_client.post(f"/api/admin/users/{target.id}/deactivate", headers=headers)
    auth_client.cookies.set(settings.auth_cookie_name, target_token, path="/api")
    assert auth_client.get("/api/auth/me").status_code == 401
    auth_client.cookies.delete(settings.auth_cookie_name, path="/api")
    assert login(auth_client).status_code == 200
    assert auth_client.post(f"/api/admin/users/{target.id}/activate", headers=csrf(auth_client)).status_code == 200
    assert login(auth_client, "target").status_code == 200


def test_last_active_admin_is_protected(auth_client, db_session):
    admin = create_user(db_session); login(auth_client)
    headers = csrf(auth_client)
    assert auth_client.post(f"/api/admin/users/{admin.id}/deactivate", headers=headers).status_code == 409
    assert auth_client.put(f"/api/admin/users/{admin.id}", headers=headers, json={"role": "user"}).status_code == 409


def test_csrf_required_for_mutation(auth_client, db_session):
    create_user(db_session); login(auth_client)
    assert auth_client.post("/api/admin/users", json={"username": "x", "password": PASSWORD, "role": "user"}).status_code == 403


def test_pending_password_change_restricts_access_and_clears_after_change(auth_client, db_session):
    user = create_user(db_session, pending=True)
    assert user.must_change_password is True
    assert login(auth_client).status_code == 200
    assert auth_client.get("/api/auth/me").json()["must_change_password"] is True
    blocked = auth_client.get("/api/equipments")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    before = user.auth_version
    changed = auth_client.put("/api/auth/change-password", headers=csrf(auth_client), json={"current_password": PASSWORD, "new_password": "admin"})
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    db_session.refresh(user)
    assert user.auth_version == before + 1 and user.must_change_password is False
    assert user.password_hash.startswith("$argon2id$") and user.password_hash != "admin"
    assert auth_client.get("/api/equipments").status_code == 200
    assert auth_client.post("/api/auth/logout").status_code == 204


def test_admin_reset_restores_password_change_requirement(auth_client, db_session):
    create_user(db_session); target = create_user(db_session, "target", "user")
    login(auth_client); before = target.auth_version
    response = auth_client.post(f"/api/admin/users/{target.id}/reset-password", headers=csrf(auth_client), json={"new_password": "admin"})
    assert response.status_code == 200 and response.json()["must_change_password"] is True
    db_session.refresh(target)
    assert target.must_change_password is True and target.auth_version == before + 1
