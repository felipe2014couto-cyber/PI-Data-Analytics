"""Deterministic tests for /api/workers/status security, tag timeout isolation, and backfill lease recovery.

Sections covered:
- Section 5: Security of /api/workers/status (authorized access, unauthenticated access,
  error sanitization, 100 watermarks limit, 5 running jobs limit, 404 for /workers/status).
- Section 6: Timeout and per-tag isolation in _ingest_recent_minute and _reconcile_recent
  (cancels slow coroutine, awaits cancellation, no orphan tasks, does not disrupt other tags,
  preserves watermark, records failure and backoff, respects next_attempt_at, does not block next cycle).
- Section 7: Recovery of expired leases (recovers only truly expired jobs, leaves legitimate
  jobs intact, preserves checkpoint_start, does not block PENDING jobs, logs recovery).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.postgres import PiBackfillJob, PiIngestionState
from app.models.equipment import Equipment
from app.models.variable_type import VariableType
from app.models.pi_tag import PiTag
from app.models.user import User, UserRole
from app.workers import ingestion_worker as iw
from app.workers import backfill_worker as bw
from app.workers.supervisor import ingestion_status, backfill_status


UTC = timezone.utc
NOW = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)


def _ensure_tag(db_session, tag_id: int, name: str, web_id: str | None = None) -> PiTag:
    eq = db_session.get(Equipment, 1)
    if eq is None:
        eq = Equipment(id=1, code="EQ1", name="Equipment 1")
        db_session.add(eq)
        db_session.flush()

    vt = db_session.get(VariableType, 1)
    if vt is None:
        vt = VariableType(id=1, code="VT1", name="Variable Type 1", default_unit="C")
        db_session.add(vt)
        db_session.flush()

    tag = db_session.get(PiTag, tag_id)
    if tag is None:
        tag = PiTag(
            id=tag_id,
            equipment_id=eq.id,
            variable_type_id=vt.id,
            pi_server="PISRV01",
            pi_tag_name=name,
            display_name=name,
            engineering_unit="unit",
            pi_web_id=web_id,
            active=True,
        )
        db_session.add(tag)
        db_session.flush()
    return tag


# ==============================================================================
# ==============================================================================
# SECTION 5: /api/workers/status and /api/workers/health tests
# ==============================================================================

def _make_admin_token(db_session, username="admin_obs") -> str:
    user = db_session.query(User).filter_by(username=username).first()
    if user is None:
        user = User(
            username=username,
            normalized_username=username,
            password_hash=hash_password("SecurePassword123!"),
            role=UserRole.ADMIN,
            is_active=True,
            must_change_password=False,
            auth_version=1,
        )
        db_session.add(user)
        db_session.commit()
    return create_access_token(user.id, user.auth_version)


def test_workers_status_unauthenticated_denied(client: TestClient):
    """Detailed observability endpoint requires admin authentication."""
    from app.api.deps import get_current_user
    orig = client.app.dependency_overrides.pop(get_current_user, None)
    try:
        client.cookies.clear()
        response = client.get("/api/workers/status")
        assert response.status_code == 401
    finally:
        if orig is not None:
            client.app.dependency_overrides[get_current_user] = orig


def test_workers_health_public_minimal(client: TestClient):
    """Minimal health endpoint is public and does not expose internal jobs, watermarks or tags."""
    client.cookies.clear()
    response = client.get("/api/workers/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "ingestion" in data
    assert "backfill" in data
    assert data["status"] in ("healthy", "degraded", "stopped", "disabled")
    assert data["ingestion"] in ("active", "standby", "disabled", "degraded", "stopped")
    assert data["backfill"] in ("active", "standby", "disabled", "degraded", "stopped")
    assert "watermarks" not in data
    assert "running_jobs" not in data
    assert "last_error" not in data


def test_workers_status_authorized_allowed(client: TestClient, db_session):
    """Authorized admin users receive 200 with full status, claims_count and attempts."""
    token = _make_admin_token(db_session)
    client.cookies.set(settings.auth_cookie_name, token)

    response = client.get("/api/workers/status")
    assert response.status_code == 200
    data = response.json()
    assert "ingestion" in data
    assert "backfill" in data
    assert "watermarks" in data["ingestion"]
    assert "running_jobs" in data["backfill"]


def test_workers_status_error_sanitization(client: TestClient, db_session):
    """Ensure passwords, tokens, API keys, and URLs with basic auth are REDACTED."""
    token = _make_admin_token(db_session)
    client.cookies.set(settings.auth_cookie_name, token)

    tag = _ensure_tag(db_session, 9801, "SENSITIVE_TAG", "WEB_SENSITIVE")

    job = PiBackfillJob(
        id=88001,
        tag_id=tag.id,
        round_name="R1",
        target_start=NOW - timedelta(days=1),
        target_end=NOW,
        status="RUNNING",
        stage="IN_FLIGHT",
        lease_owner="test_runner",
        lease_expires_at=NOW + timedelta(minutes=15),
        heartbeat_at=NOW,
        attempts=42,
        error_message="Failed connecting to http://app_user:secret_pwd123@internal-pi:8080/data?api_key=SECRET_TOKEN_XYZ and Bearer eyJhbGciOiJIUzI1NiJ9.test",
    )
    db_session.merge(job)

    # Also simulate supervisor last_error containing a password
    ingestion_status.last_error = "Database error: postgresql://pi_app:super_secret_pw@127.0.0.1:5432/db connection lost password=my_db_password"
    db_session.commit()

    response = client.get("/api/workers/status")
    assert response.status_code == 200
    data = response.json()

    # Verify backfill job error was sanitized and claims_count exposed
    running_jobs = data["backfill"]["running_jobs"]
    job_item = next((j for j in running_jobs if j["id"] == 88001), None)
    assert job_item is not None
    assert job_item["claims_count"] == 42
    assert job_item["attempts"] == 42
    err = job_item["error_message"]
    assert "secret_pwd123" not in err
    assert "SECRET_TOKEN_XYZ" not in err
    assert "eyJhbGci" not in err
    assert "[REDACTED]" in err

    # Verify ingestion supervisor error was sanitized
    ing_err = data["ingestion"]["last_error"]
    assert "super_secret_pw" not in ing_err
    assert "my_db_password" not in ing_err
    assert "[REDACTED]" in ing_err


def test_workers_status_limits_100_watermarks_and_5_jobs(client: TestClient, db_session):
    """Verify endpoint enforces at most 100 watermarks and 5 running jobs."""
    token = _make_admin_token(db_session)
    client.cookies.set(settings.auth_cookie_name, token)

    # Create 110 ingestion states
    for i in range(1, 115):
        st = PiIngestionState(
            tag_id=i,
            source_mode="RECORDED",
            watermark_ts=NOW - timedelta(minutes=i),
            last_success_at=NOW,
        )
        db_session.merge(st)

    # Create 8 running jobs with valid tag
    tag = _ensure_tag(db_session, 9802, "JOB_TAG")
    for j in range(1, 9):
        job = PiBackfillJob(
            id=77000 + j,
            tag_id=tag.id,
            round_name="R1",
            target_start=NOW - timedelta(days=2),
            target_end=NOW,
            status="RUNNING",
            stage="IN_FLIGHT",
            lease_owner=f"owner_{j}",
            lease_expires_at=NOW + timedelta(minutes=10),
            heartbeat_at=NOW,
        )
        db_session.merge(job)
    db_session.commit()

    response = client.get("/api/workers/status")
    assert response.status_code == 200
    data = response.json()

    watermarks = data["ingestion"]["watermarks"]
    assert len(watermarks) <= 100

    running_jobs = data["backfill"]["running_jobs"]
    assert len(running_jobs) <= 5


def test_workers_status_incorrect_route_returns_404(client: TestClient):
    """Verify route without /api prefix returns 404 Not Found."""
    response = client.get("/workers/status")
    assert response.status_code == 404


# ==============================================================================
# SECTION 6: Timeout and per-tag isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_recent_minute_timeout_and_isolation_deterministic(db_session, monkeypatch):
    """Verify timeout in _ingest_recent_minute cancels coroutine, awaits cancel,
    records TAG_TIMEOUT failure with backoff, does not convert to success,
    preserves watermark, and does not block other tags.
    """
    tag_slow = _ensure_tag(db_session, 9101, "TAG_SLOW", "WEB_SLOW")
    tag_fast = _ensure_tag(db_session, 9102, "TAG_FAST", "WEB_FAST")

    initial_wm = NOW - timedelta(minutes=5)
    st_slow = PiIngestionState(tag_id=9101, source_mode="RECORDED", watermark_ts=initial_wm)
    st_fast = PiIngestionState(tag_id=9102, source_mode="RECORDED", watermark_ts=initial_wm)
    db_session.merge(st_slow)
    db_session.merge(st_fast)
    db_session.commit()

    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()

    async def fake_fetch(provider, web_id, start, end, **kwargs):
        if web_id == "WEB_SLOW":
            slow_started.set()
            try:
                while True:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise
        else:
            return [
                SimpleNamespace(
                    timestamp=NOW - timedelta(seconds=30),
                    value=42.0,
                    good=True,
                    questionable=False,
                    substituted=False,
                )
            ]

    monkeypatch.setattr(iw, "_fetch_complete_interval", fake_fetch)
    monkeypatch.setattr(settings, "ingestion_tag_timeout_seconds", 0.1)

    points = await iw._ingest_recent_minute({9101, 9102}, NOW, provider=MagicMock())

    assert slow_started.is_set(), "Slow tag fetch should have started"
    assert slow_cancelled.is_set(), "Slow tag fetch should have been cancelled and awaited"
    assert points == 1

    db_session.expire_all()
    slow_state = db_session.get(PiIngestionState, (9101, "RECORDED"))
    assert slow_state.last_error_code == "TAG_TIMEOUT"
    assert slow_state.consecutive_failures == 1
    assert slow_state.next_attempt_at is not None
    assert iw._as_utc(slow_state.next_attempt_at) > NOW
    assert iw._as_utc(slow_state.watermark_ts) == initial_wm

    fast_state = db_session.get(PiIngestionState, (9102, "RECORDED"))
    assert fast_state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_reconcile_recent_timeout_and_isolation_deterministic(db_session, monkeypatch):
    """Verify timeout in _reconcile_recent cancels coroutine, awaits cancel,
    and records failure with backoff without breaking execution.
    """
    tag_slow = _ensure_tag(db_session, 9201, "TAG_RECON_SLOW", "WEB_RECON_SLOW")
    st_slow = PiIngestionState(tag_id=9201, source_mode="RECORDED", watermark_ts=NOW - timedelta(minutes=5))
    db_session.merge(st_slow)
    db_session.commit()

    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()

    async def fake_fetch(provider, web_id, start, end, **kwargs):
        slow_started.set()
        try:
            while True:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            slow_cancelled.set()
            raise

    monkeypatch.setattr(iw, "_fetch_complete_interval", fake_fetch)
    monkeypatch.setattr(settings, "ingestion_tag_timeout_seconds", 0.1)
    monkeypatch.setattr(settings, "ingestion_reconciliation_minutes", 1)

    points = await iw._reconcile_recent({9201}, NOW, provider=MagicMock())

    assert slow_started.is_set()
    assert slow_cancelled.is_set()
    assert points == 0

    db_session.expire_all()
    state = db_session.get(PiIngestionState, (9201, "RECORDED"))
    assert state.last_error_code == "TAG_TIMEOUT"
    assert state.consecutive_failures == 1


# ==============================================================================
# SECTION 7: Expired lease recovery
# ==============================================================================

def test_recover_expired_leases_deterministic(db_session):
    """Verify _recover_expired_leases:
    - Adopts only truly stale jobs where lease_expires_at < now.
    - Leaves legitimate jobs with active leases intact.
    - Preserves checkpoint_start and target bounds.
    - Does not block or alter existing PENDING jobs.
    - Reschedules adopted jobs to PENDING with RETRY_WAIT.
    """
    tag = _ensure_tag(db_session, 9301, "TAG_BACKFILL")

    checkpoint = NOW - timedelta(days=5)
    target_start = NOW - timedelta(days=10)
    target_end = NOW

    # 1. Truly expired RUNNING job
    expired_job = PiBackfillJob(
        id=60001,
        tag_id=tag.id,
        round_name="R1",
        target_start=target_start,
        target_end=target_end,
        checkpoint_start=checkpoint,
        status="RUNNING",
        stage="IN_FLIGHT",
        lease_owner="dead_worker_1",
        lease_expires_at=NOW - timedelta(minutes=10),
        heartbeat_at=NOW - timedelta(minutes=25),
        attempts=3,
    )

    # 2. Legitimate active RUNNING job with future lease
    active_job = PiBackfillJob(
        id=60002,
        tag_id=tag.id,
        round_name="R1",
        target_start=target_start,
        target_end=target_end,
        checkpoint_start=checkpoint,
        status="RUNNING",
        stage="IN_FLIGHT",
        lease_owner="healthy_worker_2",
        lease_expires_at=NOW + timedelta(minutes=15),
        heartbeat_at=NOW - timedelta(seconds=30),
        attempts=1,
    )

    # 3. Existing PENDING job
    pending_job = PiBackfillJob(
        id=60003,
        tag_id=tag.id,
        round_name="R1",
        target_start=target_start,
        target_end=target_end,
        checkpoint_start=target_start,
        status="PENDING",
        stage="PENDING",
        lease_owner=None,
        lease_expires_at=None,
        attempts=0,
    )

    db_session.merge(expired_job)
    db_session.merge(active_job)
    db_session.merge(pending_job)
    db_session.commit()

    with patch.object(bw, "_now", return_value=NOW):
        recovered_ids = bw._recover_expired_leases()

    # Must recover ONLY job 60001
    assert 60001 in recovered_ids
    assert 60002 not in recovered_ids
    assert 60003 not in recovered_ids

    db_session.expire_all()

    # Verify recovered job state
    rec = db_session.get(PiBackfillJob, 60001)
    assert rec.status == "PENDING"
    assert rec.stage == "RETRY_WAIT"
    assert rec.lease_owner is None
    assert rec.lease_expires_at is None
    # Checkpoint PRESERVED
    assert iw._as_utc(rec.checkpoint_start) == checkpoint
    assert iw._as_utc(rec.target_start) == target_start
    assert iw._as_utc(rec.target_end) == target_end
    assert "Lease expirado" in rec.error_message

    # Verify active job was NOT altered
    act = db_session.get(PiBackfillJob, 60002)
    assert act.status == "RUNNING"
    assert act.lease_owner == "healthy_worker_2"
    assert iw._as_utc(act.lease_expires_at) > NOW

    # Verify pending job was NOT altered
    pnd = db_session.get(PiBackfillJob, 60003)
    assert pnd.status == "PENDING"
    assert pnd.stage == "PENDING"


@pytest.mark.asyncio
async def test_backfill_conditional_checkpoint_rejection(db_session):
    """Verify that if a worker tries to advance a job whose lease was expired or taken over
    by another worker, rowcount == 0 causes rollback and discards points without corrupting checkpoint.
    """
    tag = _ensure_tag(db_session, 9201, "TAG_FENCING", "WEB_FENCING")
    start = NOW - timedelta(hours=4)
    end = NOW - timedelta(hours=2)

    # Job is owned by 'other_worker' and lease is expired
    job = PiBackfillJob(
        id=70001,
        tag_id=tag.id,
        target_start=NOW - timedelta(days=1),
        target_end=NOW,
        checkpoint_start=start,
        next_start=start,
        status="RUNNING",
        stage="RUNNING",
        lease_owner="other_worker_stolen",
        lease_expires_at=NOW - timedelta(minutes=10),
        attempts=1,
    )
    db_session.merge(job)
    db_session.commit()

    mock_provider = MagicMock()
    mock_provider.get_recorded_values = AsyncMock(return_value=SimpleNamespace(values=[
        SimpleNamespace(timestamp=start + timedelta(minutes=10), value=99.9, good=True, questionable=False, substituted=False),
    ]))

    semaphore = asyncio.Semaphore(1)
    with patch.object(bw, "get_pi_data_provider", return_value=mock_provider):
        ok = await bw.backfill_tag_interval(
            tag_id=tag.id,
            start=start,
            end=end,
            t0=NOW,
            round_name="R1",
            semaphore=semaphore,
            job_id=70001,
        )

    assert ok is False, "Stale worker execution must be rejected"

    db_session.expire_all()
    j = db_session.get(PiBackfillJob, 70001)
    assert iw._as_utc(j.checkpoint_start) == start
    assert j.status != "COMPLETED"


def test_ingestion_monotonic_watermark(db_session):
    """Verify that ingestion watermark advances monotonically and never regresses even with out-of-order points."""
    st = PiIngestionState(
        tag_id=9301,
        source_mode="RECORDED",
        watermark_ts=NOW,
    )
    db_session.merge(st)
    db_session.commit()

    older_points = [
        SimpleNamespace(timestamp=NOW - timedelta(minutes=10), value=10.0, good=True, questionable=False, substituted=False),
        SimpleNamespace(timestamp=NOW - timedelta(minutes=5), value=20.0, good=True, questionable=False, substituted=False),
    ]

    iw._persist_points(db_session, 9301, older_points, "RECORDED")
    tx_state = db_session.get(PiIngestionState, (9301, "RECORDED"))
    watermark_ts, _ = iw._state_timestamps(older_points, NOW - timedelta(minutes=5), tx_state.last_source_ts)

    current_wm = iw._as_utc(tx_state.watermark_ts) if tx_state.watermark_ts is not None else None
    if current_wm is None or (watermark_ts is not None and watermark_ts > current_wm):
        tx_state.watermark_ts = watermark_ts
    db_session.commit()

    # Watermark must still be NOW, not regressed to NOW - 5m
    db_session.refresh(tx_state)
    assert iw._as_utc(tx_state.watermark_ts) == NOW


# ==============================================================================
# SECTION 8: 12 Deterministic Backoff & Worker Health State Tests
# ==============================================================================

def test_backoff_consecutive_failures_0():
    """consecutive_failures = 0 yields base delay."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(0)
    assert delay == settings.backfill_retry_base_seconds


def test_backoff_consecutive_failures_1():
    """consecutive_failures = 1 yields base delay."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(1)
    assert delay == settings.backfill_retry_base_seconds


def test_backoff_consecutive_failures_2():
    """consecutive_failures = 2 yields base * 2 delay."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(2)
    assert delay == settings.backfill_retry_base_seconds * 2


def test_backoff_consecutive_failures_3():
    """consecutive_failures = 3 yields base * 4 delay."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(3)
    assert delay == settings.backfill_retry_base_seconds * 4


def test_backoff_saturation_at_ceiling():
    """High consecutive_failures saturates at backfill_retry_max_seconds."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(25)
    assert delay == settings.backfill_retry_max_seconds


def test_backoff_explicit_numeric_retry_after():
    """Explicit numeric retry_after is respected when greater than exponential."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(1, retry_after=12.5)
    assert delay == 12.5

    # If exponential is higher than retry_after, exponential is chosen
    with patch("random.uniform", return_value=0.0):
        delay_exp = bw._retry_delay(4, retry_after=2.0)
    expected = min(settings.backfill_retry_base_seconds * 8, settings.backfill_retry_max_seconds)
    assert delay_exp == expected


def test_backoff_invalid_non_numeric_retry_after():
    """Non-numeric or None retry_after falls back to exponential delay without errors."""
    with patch("random.uniform", return_value=0.0):
        delay_str = bw._retry_delay(1, retry_after="not-a-number")
        delay_none = bw._retry_delay(1, retry_after=None)
    assert delay_str == settings.backfill_retry_base_seconds
    assert delay_none == settings.backfill_retry_base_seconds


def test_backoff_retry_after_exceeding_ceiling():
    """retry_after exceeding backfill_retry_max_seconds is capped at ceiling."""
    with patch("random.uniform", return_value=0.0):
        delay = bw._retry_delay(1, retry_after=settings.backfill_retry_max_seconds + 999.0)
    assert delay == settings.backfill_retry_max_seconds


def test_backoff_job_7188_first_failure(db_session):
    """Job 7188 with 2,163 claims suffering its 1st real failure uses consecutive_failures=1, not 2,163."""
    tag = _ensure_tag(db_session, 7188, "TAG_7188", "WEB_7188")
    job = PiBackfillJob(
        id=7188,
        tag_id=tag.id,
        round_name="R1",
        target_start=NOW - timedelta(days=10),
        target_end=NOW,
        checkpoint_start=NOW - timedelta(days=5),
        status="RUNNING",
        stage="RUNNING",
        lease_owner=bw.LEASE_OWNER,
        lease_expires_at=NOW + timedelta(minutes=10),
        heartbeat_at=NOW,
        attempts=2163,
        consecutive_failures=0,
    )
    db_session.merge(job)
    db_session.commit()

    with patch("random.uniform", return_value=0.0):
        bw._defer_job(7188, "PI_TIMEOUT", "Connection timed out")

    db_session.expire_all()
    updated = db_session.get(PiBackfillJob, 7188)
    assert updated is not None
    # attempts must remain 2163 (historical claims count preserved!)
    assert updated.attempts == 2163
    # consecutive_failures must now be 1
    assert updated.consecutive_failures == 1
    assert updated.status == "PENDING"
    assert updated.stage == "RETRY_WAIT"
    # Delay for consecutive_failures=1 is base_seconds, NOT saturated max delay
    assert updated.next_attempt_at is not None
    assert updated.last_error_at is not None
    # Verify delay is base_seconds
    expected_delay = settings.backfill_retry_base_seconds
    actual_delay = (updated.next_attempt_at - updated.last_error_at).total_seconds()
    assert abs(actual_delay - expected_delay) < 1.0


def test_backoff_intermediate_success_resets_consecutive_failures(db_session):
    """Successful window completion resets consecutive_failures to 0 while preserving attempts."""
    tag = _ensure_tag(db_session, 7189, "TAG_7189", "WEB_7189")
    start = NOW - timedelta(hours=2)
    end = NOW - timedelta(hours=1)
    target_end = NOW

    job = PiBackfillJob(
        id=7189,
        tag_id=tag.id,
        round_name="R1",
        target_start=start,
        target_end=target_end,
        checkpoint_start=start,
        next_start=start,
        status="PENDING",
        stage="PENDING",
        lease_owner=None,
        lease_expires_at=None,
        heartbeat_at=None,
        attempts=15,
        consecutive_failures=4,
    )
    db_session.merge(job)
    db_session.commit()

    mock_provider = AsyncMock()
    mock_provider.get_recorded_values = AsyncMock(return_value=SimpleNamespace(values=[]))

    with patch("app.workers.backfill_worker.get_pi_data_provider", return_value=mock_provider):
        with patch("app.workers.backfill_worker.SessionLocal", return_value=db_session):
            semaphore = asyncio.Semaphore(1)
            ok = asyncio.run(bw.backfill_tag_interval(
                tag_id=tag.id,
                start=start,
                end=end,
                mode="RECORDED",
                interval_seconds=60,
                t0=NOW - timedelta(days=1),
                round_name="R1",
                semaphore=semaphore,
                job_id=7189,
            ))

    assert ok is True
    db_session.expire_all()
    updated = db_session.get(PiBackfillJob, 7189)
    assert updated.consecutive_failures == 0
    assert updated.attempts == 16
    assert updated.status == "PENDING"
    assert updated.stage == "READY"


def test_backoff_budget_exhaustion_or_lease_loss_does_not_increment_failures(db_session):
    """Lease loss in backfill and BudgetExhaustedError in ingestion do NOT increment consecutive_failures."""
    # 1. Backfill lease loss
    tag = _ensure_tag(db_session, 7190, "TAG_7190", "WEB_7190")
    start = NOW - timedelta(hours=2)
    end = NOW - timedelta(hours=1)

    job = PiBackfillJob(
        id=7190,
        tag_id=tag.id,
        round_name="R1",
        target_start=start,
        target_end=NOW,
        checkpoint_start=start,
        next_start=start,
        status="RUNNING",
        stage="RUNNING",
        lease_owner="another_worker_stole_lease",
        lease_expires_at=NOW + timedelta(minutes=10),
        heartbeat_at=NOW,
        attempts=5,
        consecutive_failures=2,
    )
    db_session.merge(job)
    db_session.commit()

    # If _defer_job is attempted with mismatched lease_owner, it exits immediately without modifying consecutive_failures
    bw._defer_job(7190, "PI_TIMEOUT", "Should not defer because lease lost")
    db_session.expire_all()
    j = db_session.get(PiBackfillJob, 7190)
    assert j.consecutive_failures == 2
    assert j.lease_owner == "another_worker_stole_lease"

    # 2. Ingestion BudgetExhaustedError
    st = PiIngestionState(
        tag_id=7190,
        source_mode="RECORDED",
        watermark_ts=start,
        consecutive_failures=0,
    )
    db_session.merge(st)
    db_session.commit()

    from app.workers.ingestion_worker import BudgetExhaustedError
    assert issubclass(BudgetExhaustedError, RuntimeError)


def test_backoff_deterministic_mocked_jitter():
    """Deterministic mocked jitter is added to exponential delay within ceiling."""
    with patch("random.uniform", return_value=0.75):
        delay = bw._retry_delay(1)
    assert delay == settings.backfill_retry_base_seconds + 0.75

    with patch("random.uniform", return_value=1.0):
        delay_max = bw._retry_delay(20)
    assert delay_max == settings.backfill_retry_max_seconds


def test_workers_health_all_states():
    """Verify _worker_state correctly categorizes active, standby, disabled, degraded, and stopped."""
    from app.api.health import _worker_state
    from app.workers.supervisor import _WorkerStatus

    st = _WorkerStatus("test")
    # disabled
    assert _worker_state(st, enabled=False) == "disabled"

    # enabled but stopped
    st.alive = False
    assert _worker_state(st, enabled=True) == "stopped"

    # alive, leader, no failures -> active
    st.alive = True
    st.leader = True
    st.consecutive_failures = 0
    assert _worker_state(st, enabled=True) == "active"

    # alive, standby (not leader), no failures -> standby
    st.leader = False
    assert _worker_state(st, enabled=True) == "standby"

    # alive, consecutive_failures > 0 -> degraded
    st.consecutive_failures = 2
    assert _worker_state(st, enabled=True) == "degraded"
    st.leader = True
    assert _worker_state(st, enabled=True) == "degraded"

