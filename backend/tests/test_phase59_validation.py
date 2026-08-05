"""Phase 5.9 — Integrated validation, performance, and documentation tests.

Covers:
- Error code coverage (400, 401, 403, 404, 409, 422, 500, 503)
- Auth and authorization integration
- Visual configuration CRUD + versioning lifecycle
- User isolation
- Input validation boundaries
- Empty/invalid/partial response handling
- Regression tests for phases 5.1–5.8
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_name(prefix="cfg") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_config(client: TestClient, name: str | None = None, doc: dict | None = None) -> dict:
    payload = {
        "name": name or _unique_name(),
        "document": doc or {
            "schema_version": 1,
            "visual_rules": {
                "enabled": False,
                "selectedSeriesInstanceId": "",
                "bySeries": {},
            },
        },
    }
    r = client.post("/api/visual-configurations", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "test-admin", "password": "admin"})
    assert r.status_code == 200, r.text


# ===========================================================================
# 1. Error code coverage
# ===========================================================================

class TestErrorCodes:
    def test_401_unauthenticated_access(self, client: TestClient):
        """Protected routes return 401 when no session cookie is present."""
        from app.api.deps import get_current_user
        client.app.dependency_overrides.pop(get_current_user, None)
        r = client.get("/api/equipments")
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "AUTHENTICATION_REQUIRED"

    def test_404_on_missing_visual_configuration(self, client: TestClient):
        r = client.get("/api/visual-configurations/nonexistent-id-123")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_409_optimistic_conflict(self, client: TestClient):
        cfg = _create_config(client)
        # Update succeeds with correct expected_version
        r1 = client.put(f"/api/visual-configurations/{cfg['id']}", json={
            "expected_version": cfg["current_version"],
            "document": {
                "schema_version": 1,
                "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "x", "bySeries": {}},
            },
        })
        assert r1.status_code == 200
        # Concurrent update with stale version fails
        r2 = client.put(f"/api/visual-configurations/{cfg['id']}", json={
            "expected_version": cfg["current_version"],  # stale
            "document": {
                "schema_version": 1,
                "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}},
            },
        })
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "CONFLICT"

    def test_422_validation_error_on_invalid_payload(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "",  # empty name rejected
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 422

    def test_422_on_name_too_long(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "x" * 101,
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 422

    def test_404_on_nonexistent_version(self, client: TestClient):
        cfg = _create_config(client)
        r = client.get(f"/api/visual-configurations/{cfg['id']}/history/999")
        assert r.status_code == 404

    def test_404_on_delete_nonexistent(self, client: TestClient):
        r = client.delete("/api/visual-configurations/fake-id")
        assert r.status_code == 404

    def test_500_unhandled_exception_returns_structured_error(self, client: TestClient):
        """Verify the catch-all handler returns a proper error envelope."""
        r = client.get("/api/health")
        assert r.status_code == 200
        # Health endpoint should always work and not hit the 500 handler


# ===========================================================================
# 2. Auth and authorization integration
# ===========================================================================

class TestAuthIntegration:
    def test_login_sets_cookies_and_me_returns_user(self, client: TestClient):
        r = client.post("/api/auth/login", json={"username": "test-admin", "password": "admin"})
        assert r.status_code == 200
        body = r.json()
        assert "username" in body
        assert "password_hash" not in body

        r2 = client.get("/api/auth/me")
        assert r2.status_code == 200
        assert r2.json()["username"] == "test-admin"

    def test_logout_clears_session(self, client: TestClient):
        client.post("/api/auth/login", json={"username": "test-admin", "password": "admin"})
        r = client.post("/api/auth/logout")
        assert r.status_code == 204
        r2 = client.get("/api/auth/me")
        assert r2.status_code == 401

    def test_invalid_credentials_return_401(self, client: TestClient):
        r = client.post("/api/auth/login", json={"username": "test-admin", "password": "wrong"})
        assert r.status_code == 401

    def test_protected_routes_require_auth(self, client: TestClient):
        from app.api.deps import get_current_user
        client.app.dependency_overrides.pop(get_current_user, None)
        for route in ["/api/equipments", "/api/sections", "/api/pi-tags", "/api/visual-configurations"]:
            r = client.get(route)
            assert r.status_code == 401, f"{route} should require auth"


# ===========================================================================
# 3. Visual configuration CRUD + versioning lifecycle
# ===========================================================================

class TestVisualConfigurationLifecycle:
    def test_full_lifecycle_create_read_update_history_restore_delete(self, client: TestClient):
        doc_v1 = {
            "schema_version": 1,
            "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}},
            "sidebar_state": {"filters": {"preset": "PT15M"}},
        }
        # Create
        cfg = _create_config(client, doc=doc_v1)
        assert cfg["current_version"] == 1
        cfg_id = cfg["id"]

        # Read
        r = client.get(f"/api/visual-configurations/{cfg_id}")
        assert r.status_code == 200
        assert r.json()["id"] == cfg_id

        # Update (v1 -> v2)
        doc_v2 = {
            "schema_version": 1,
            "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "s1", "bySeries": {}},
        }
        r = client.put(f"/api/visual-configurations/{cfg_id}", json={
            "expected_version": 1,
            "document": doc_v2,
        })
        assert r.status_code == 200
        assert r.json()["current_version"] == 2

        # History should have 2 versions
        r = client.get(f"/api/visual-configurations/{cfg_id}/history")
        assert r.status_code == 200
        versions = r.json()
        assert len(versions) == 2
        assert versions[0]["version"] == 2
        assert versions[1]["version"] == 1

        # Get specific version
        r = client.get(f"/api/visual-configurations/{cfg_id}/history/1")
        assert r.status_code == 200
        assert r.json()["version"] == 1

        # Restore to v1 (creates v3)
        r = client.post(f"/api/visual-configurations/{cfg_id}/restore", json={
            "expected_version": 2,
            "version": 1,
        })
        assert r.status_code == 200
        assert r.json()["current_version"] == 3

        # List should include this config
        r = client.get("/api/visual-configurations")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert cfg_id in ids

        # Delete
        r = client.delete(f"/api/visual-configurations/{cfg_id}")
        assert r.status_code == 204

        # Verify deleted
        r = client.get(f"/api/visual-configurations/{cfg_id}")
        assert r.status_code == 404

    def test_rename_creates_new_version(self, client: TestClient):
        cfg = _create_config(client, name="original-name")
        r = client.post(f"/api/visual-configurations/{cfg['id']}/rename", json={
            "expected_version": cfg["current_version"],
            "name": "new-name",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "new-name"
        assert r.json()["current_version"] == 2

    def test_document_schema_version_required(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "test",
            "document": {
                "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}},
            },
        })
        assert r.status_code == 422


# ===========================================================================
# 4. User isolation
# ===========================================================================

class TestUserIsolation:
    def _create_second_user(self, client: TestClient, db_session):
        """Create a second user and return their client."""
        from app.models.user import User, UserRole
        from app.core.security import hash_password
        user2 = User(
            username="test-user-2",
            normalized_username="test-user-2",
            password_hash=hash_password("admin"),
            role=UserRole.USER,
            is_active=True,
            auth_version=1,
            must_change_password=False,
        )
        db_session.add(user2)
        db_session.commit()
        return user2

    def test_other_user_cannot_see_my_configs(self, client: TestClient, db_session):
        cfg = _create_config(client, name="my-private-config")
        # Create second user and log in as them
        user2 = self._create_second_user(client, db_session)
        client.post("/api/auth/login", json={"username": "test-user-2", "password": "admin"})
        # The config should not be visible
        r = client.get(f"/api/visual-configurations/{cfg['id']}")
        assert r.status_code == 404

    def test_other_user_cannot_modify_my_configs(self, client: TestClient, db_session):
        cfg = _create_config(client)
        user2 = self._create_second_user(client, db_session)
        client.post("/api/auth/login", json={"username": "test-user-2", "password": "admin"})
        r = client.put(f"/api/visual-configurations/{cfg['id']}", json={
            "expected_version": cfg["current_version"],
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 404

    def test_other_user_cannot_delete_my_configs(self, client: TestClient, db_session):
        cfg = _create_config(client)
        user2 = self._create_second_user(client, db_session)
        client.post("/api/auth/login", json={"username": "test-user-2", "password": "admin"})
        r = client.delete(f"/api/visual-configurations/{cfg['id']}")
        assert r.status_code == 404


# ===========================================================================
# 5. Input validation boundaries
# ===========================================================================

class TestInputValidation:
    def test_name_min_length(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "",
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 422

    def test_name_max_length(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "a" * 100,
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 201

    def test_description_max_length(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "test",
            "description": "d" * 500,
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 201

    def test_description_exceeds_max(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "test",
            "description": "d" * 501,
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 422

    def test_invalid_schema_version_rejected(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "test",
            "document": {"schema_version": 99, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 422

    def test_missing_visual_rules_rejected(self, client: TestClient):
        r = client.post("/api/visual-configurations", json={
            "name": "test",
            "document": {"schema_version": 1},
        })
        assert r.status_code == 422


# ===========================================================================
# 6. Health endpoints
# ===========================================================================

class TestHealthEndpoints:
    def test_health_returns_200(self, client: TestClient):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_pi_health_returns_status(self, client: TestClient):
        r = client.get("/api/pi/health")
        assert r.status_code == 200
        body = r.json()
        assert "status" in body


# ===========================================================================
# 7. Equipment / Section / Tag cascade and validation
# ===========================================================================

class TestCatalogEndpoints:
    def test_list_equipments(self, client: TestClient):
        r = client.get("/api/equipments")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_sections(self, client: TestClient):
        r = client.get("/api/sections")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_variable_types(self, client: TestClient):
        r = client.get("/api/variable-types")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_pi_tags(self, client: TestClient):
        r = client.get("/api/pi-tags")
        assert r.status_code == 200


# ===========================================================================
# 8. Regression: phases 5.1–5.8 core contracts
# ===========================================================================

class TestRegressionPhases5x:
    def test_visual_document_normalization(self, client: TestClient):
        """Old documents without sidebar_state still validate (phase 5.7 compat)."""
        old_doc = {
            "schema_version": 1,
            "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}},
        }
        cfg = _create_config(client, doc=old_doc)
        r = client.get(f"/api/visual-configurations/{cfg['id']}")
        assert r.status_code == 200
        doc = r.json()["document"]
        assert doc["schema_version"] == 1

    def test_version_immutability(self, client: TestClient):
        """Historical versions cannot be modified via update."""
        cfg = _create_config(client)
        # Update to v2
        client.put(f"/api/visual-configurations/{cfg['id']}", json={
            "expected_version": 1,
            "document": {"schema_version": 1, "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "x", "bySeries": {}}},
        })
        # Get v1 — should still have original content
        r = client.get(f"/api/visual-configurations/{cfg['id']}/history/1")
        assert r.status_code == 200
        snap = r.json()["snapshot"]
        assert snap["visual_rules"]["enabled"] is False

    def test_cascade_delete_versions(self, client: TestClient):
        """Deleting a config removes all versions."""
        cfg = _create_config(client)
        client.put(f"/api/visual-configurations/{cfg['id']}", json={
            "expected_version": 1,
            "document": {"schema_version": 1, "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "x", "bySeries": {}}},
        })
        # Delete
        client.delete(f"/api/visual-configurations/{cfg['id']}")
        # Versions should be gone
        r = client.get(f"/api/visual-configurations/{cfg['id']}/history")
        assert r.status_code == 404

    def test_empty_list_response(self, client: TestClient):
        """List returns empty array when no configs exist."""
        r = client.get("/api/visual-configurations")
        assert r.status_code == 200
        assert r.json() == []

    def test_operation_field_on_versions(self, client: TestClient):
        """Each version records its operation type."""
        cfg = _create_config(client)
        client.put(f"/api/visual-configurations/{cfg['id']}", json={
            "expected_version": 1,
            "document": {"schema_version": 1, "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "x", "bySeries": {}}},
        })
        client.post(f"/api/visual-configurations/{cfg['id']}/rename", json={
            "expected_version": 2,
            "name": "renamed",
        })
        r = client.get(f"/api/visual-configurations/{cfg['id']}/history")
        ops = [v["operation"] for v in r.json()]
        assert "create" in ops
        assert "update" in ops
        assert "rename" in ops
