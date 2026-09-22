"""Tests for Database Health (Saúde do Banco) endpoint and service."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.config import settings
from app.main import create_app
from app.models import User, UserRole
from app.schemas.auth import UserCreate
from app.schemas.database_health import (
    ConnectionsInfo,
    DatabaseConnectionInfo,
    DatabaseHealthResponse,
    DatabaseHealthStatus,
    FreshnessInfo,
    HealthCheckItem,
    LocksInfo,
    StorageInfo,
    TimescaleInfo,
)
from app.services.database_health_service import (
    DatabaseHealthCollector,
    format_bytes,
    get_database_health,
)
from app.services.user_service import UserService
from tests.conftest import TestingSessionLocal


@pytest.fixture()
def auth_client():
    app = create_app()

    def db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = db_override
    with TestClient(app, backend_options={"use_uvloop": True}) as client:
        yield client


def _create_user(db: Session, username: str, role: str) -> User:
    user = UserService(db).create(
        UserCreate(username=username, password="password-123", role=role, is_active=True)
    )
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, username: str) -> None:
    res = client.post("/api/auth/login", json={"username": username, "password": "password-123"})
    assert res.status_code == 200


def test_database_health_requires_auth(auth_client):
    """Ensure 401 is returned when unauthenticated."""
    res = auth_client.get("/api/database/health")
    assert res.status_code == 401


def test_database_health_requires_admin_role(auth_client, db_session):
    """Ensure 403 is returned for standard non-admin users."""
    _create_user(db_session, username="regular_user", role="user")
    _login(auth_client, "regular_user")

    res = auth_client.get("/api/database/health")
    assert res.status_code == 403


def test_database_health_admin_success(auth_client, db_session):
    """Ensure 200 is returned for administrators."""
    _create_user(db_session, username="admin_health", role="admin")
    _login(auth_client, "admin_health")

    res = auth_client.get("/api/database/health")
    assert res.status_code == 200
    data = res.json()

    assert "status" in data
    assert "checked_at" in data
    assert "duration_ms" in data
    assert "cached" in data
    assert "database" in data
    assert "storage" in data
    assert "connections" in data
    assert "locks" in data
    assert "timescale" in data
    assert "freshness" in data
    assert "checks" in data
    assert "unavailable_metrics" in data


def test_database_health_sanitization(auth_client, db_session):
    """Ensure sensitive credentials, tokens and host details are never leaked."""
    _create_user(db_session, username="admin_sanitize", role="admin")
    _login(auth_client, "admin_sanitize")

    res = auth_client.get("/api/database/health")
    assert res.status_code == 200
    text_payload = res.text.lower()

    # Never expose passwords, connection strings, secrets, or internal IPs
    assert "password" not in text_payload or '"password":' not in text_payload
    assert "secret" not in text_payload
    assert "token" not in text_payload or "csrf" in text_payload  # csrf header token is normal, auth tokens forbidden
    assert "pads_session" not in text_payload
    assert "postgresql://" not in text_payload
    assert "sqlite:///" not in text_payload


@pytest.mark.asyncio
async def test_database_health_caching_and_refresh():
    """Verify that cached response is returned when within TTL and force_refresh bypasses cache."""
    # First call with force_refresh
    r1 = await get_database_health(session_factory=TestingSessionLocal, force_refresh=True)
    assert r1.cached is False

    # Second call should return cached copy
    r2 = await get_database_health(session_factory=TestingSessionLocal, force_refresh=False)
    assert r2.cached is True
    assert r2.status == r1.status

    # Third call with force_refresh=True should bypass cache
    r3 = await get_database_health(session_factory=TestingSessionLocal, force_refresh=True)
    assert r3.cached is False


def test_format_bytes_utility():
    """Verify format_bytes helper with different byte ranges."""
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1048576) == "1.00 MB"
    assert format_bytes(1073741824) == "1.00 GB"
    assert format_bytes(1099511627776) == "1.00 TB"
    assert format_bytes(None) == "0 B"
    assert format_bytes(-10) == "0 B"


def test_evaluate_checks_status_healthy():
    """Test collector evaluation returns HEALTHY when all metrics are within normal bounds."""
    collector = DatabaseHealthCollector(None)

    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=5.0, name="test_db")
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(current=10, maximum=100, usage_percent=10.0, active=2, idle=8)
    locks_info = LocksInfo(total=5, granted=5, waiting=0, blocked_sessions=0)
    timescale_info = TimescaleInfo(available=True, version="2.27.1", failed_jobs=0)
    freshness_info = FreshnessInfo(lag_seconds=30.0, tags_in_backoff=0, expired_backfill_leases=0)

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )
    assert status == DatabaseHealthStatus.HEALTHY
    assert all(c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)


def test_evaluate_checks_status_warning_cases():
    """Test collector evaluation generates WARNING status for elevated connections, lag, or jobs."""
    # High connection warning
    collector = DatabaseHealthCollector(None)
    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=5.0)
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(current=85, maximum=100, usage_percent=85.0)  # > 80%
    locks_info = LocksInfo()
    timescale_info = TimescaleInfo(available=True, failed_jobs=0)
    freshness_info = FreshnessInfo(lag_seconds=60.0)

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )
    assert status == DatabaseHealthStatus.WARNING
    assert any(c.name == "conexoes" and c.status == DatabaseHealthStatus.WARNING for c in collector.checks)

    # Failed timescale jobs warning
    collector2 = DatabaseHealthCollector(None)
    conn_stats2 = ConnectionsInfo(current=10, maximum=100, usage_percent=10.0)
    timescale_info2 = TimescaleInfo(available=True, failed_jobs=2)
    status2 = collector2._evaluate_checks(
        conn_info, storage_info, conn_stats2, locks_info, timescale_info2, freshness_info
    )
    assert status2 == DatabaseHealthStatus.WARNING
    assert any(c.name == "timescaledb_jobs" and c.status == DatabaseHealthStatus.WARNING for c in collector2.checks)


def test_evaluate_checks_status_critical_cases():
    """Test collector evaluation generates CRITICAL status for critical connections or blocked sessions."""
    collector = DatabaseHealthCollector(None)
    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=5.0)
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(current=95, maximum=100, usage_percent=95.0)  # >= 90%
    locks_info = LocksInfo()
    timescale_info = TimescaleInfo(available=True, failed_jobs=0)
    freshness_info = FreshnessInfo(lag_seconds=60.0)

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )
    assert status == DatabaseHealthStatus.CRITICAL

    # Prolonged blocked session critical
    collector2 = DatabaseHealthCollector(None)
    conn_stats2 = ConnectionsInfo(current=10, maximum=100, usage_percent=10.0)
    locks_info2 = LocksInfo(blocked_sessions=2, oldest_wait_seconds=25.0)  # > 15s
    status2 = collector2._evaluate_checks(
        conn_info, storage_info, conn_stats2, locks_info2, timescale_info, freshness_info
    )
    assert status2 == DatabaseHealthStatus.CRITICAL
    assert any(c.name == "bloqueios" and c.status == DatabaseHealthStatus.CRITICAL for c in collector2.checks)


@pytest.mark.asyncio
async def test_database_health_timeout_handling(monkeypatch):
    """Test that timeout in collection produces UNAVAILABLE response with timeout check."""
    from app.services import database_health_service

    monkeypatch.setattr(settings, "db_health_timeout_seconds", 0.05)

    def _hang(*args, **kwargs):
        import time
        time.sleep(0.2)
        raise RuntimeError("Should not be reached")

    monkeypatch.setattr(database_health_service.DatabaseHealthCollector, "collect", _hang)

    res = await database_health_service.get_database_health(session_factory=TestingSessionLocal, force_refresh=True)
    assert res.status == DatabaseHealthStatus.UNAVAILABLE
    assert res.database.reachable is False
    assert any(c.name == "timeout" for c in res.checks)
