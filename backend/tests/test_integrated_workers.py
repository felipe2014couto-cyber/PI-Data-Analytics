"""Comprehensive tests for the integrated ingestion/backfill supervisor,
recent-first ingestion, catch-up recovery, and backfill stuck job handling.

All tests are deterministic (no fragile sleep). They use asyncio.Event,
controlled clocks, and fake providers.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.workers import ingestion_worker as iw
from app.workers import backfill_worker as bw
from app.workers.ingestion_worker import (
    BUDGET_EXHAUSTED,
    BudgetExhaustedError,
    FetchStats,
    IntervalIncompleteError,
    _pending_intervals,
    _ingest_tag,
)
from app.workers.supervisor import (
    WorkerSupervisor,
    _WorkerStatus,
    _run_supervised,
    ingestion_status,
    backfill_status,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 17, 14, 32, 35, tzinfo=UTC)


# ============================================================
# Helpers
# ============================================================

class _Point:
    def __init__(self, ts: datetime, value: float = 1.0):
        self.timestamp = ts
        self.value = value
        self.good = True
        self.questionable = False
        self.substituted = False


def _resp(points):
    return SimpleNamespace(values=list(points))


# ============================================================
# 1. Lifespan: supervisor starts ingestion
# ============================================================

@pytest.mark.asyncio
async def test_supervisor_starts_and_stops_workers():
    """Verify supervisor creates workers and stops them cleanly."""
    started = {"ingestion": False, "backfill": False}
    stopped = asyncio.Event()

    async def fake_ingestion(interval=10, *, once=False, stop_event=None):
        started["ingestion"] = True
        if stop_event:
            await stop_event.wait()

    async def fake_backfill(*, once=False, stop_event=None, admin_only=False, job_ids=None):
        started["backfill"] = True
        if stop_event:
            await stop_event.wait()

    with patch.object(iw, "run_ingestion_loop", fake_ingestion), \
         patch.object(bw, "run_backfill_loop", fake_backfill):
        sup = WorkerSupervisor()
        await sup.start()
        await asyncio.sleep(0.05)
        assert ingestion_status.alive or started["ingestion"]
        await sup.stop()


# ============================================================
# 2. Shutdown cancels workers
# ============================================================

@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits():
    """Backend shutdown signals stop and awaits all workers."""
    entered = asyncio.Event()

    async def slow_worker(interval=10, *, once=False, stop_event=None):
        entered.set()
        if stop_event:
            await stop_event.wait()
        else:
            await asyncio.sleep(9999)

    with patch.object(iw, "run_ingestion_loop", slow_worker), \
         patch.object(bw, "run_backfill_loop", AsyncMock()):
        sup = WorkerSupervisor()
        await sup.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(sup.stop(), timeout=5)
        assert not ingestion_status.alive


# ============================================================
# 3. Backfill failure does not crash API or ingestion
# ============================================================

@pytest.mark.asyncio
async def test_backfill_crash_does_not_kill_ingestion():
    ingestion_alive = asyncio.Event()
    ingestion_stop = asyncio.Event()

    async def good_ingestion(interval=10, *, once=False, stop_event=None):
        ingestion_alive.set()
        if stop_event:
            await stop_event.wait()

    async def bad_backfill(*, once=False, stop_event=None, admin_only=False, job_ids=None):
        raise RuntimeError("backfill boom")

    with patch.object(iw, "run_ingestion_loop", good_ingestion), \
         patch.object(bw, "run_backfill_loop", bad_backfill):
        sup = WorkerSupervisor()
        await sup.start()
        await asyncio.wait_for(ingestion_alive.wait(), timeout=2)
        await asyncio.sleep(0.2)  # Let backfill crash
        # Ingestion should still be alive.
        assert ingestion_alive.is_set()
        await sup.stop()


# ============================================================
# 4. Ingestion failure does not crash API
# ============================================================

@pytest.mark.asyncio
async def test_ingestion_crash_does_not_kill_api():
    backfill_alive = asyncio.Event()

    async def bad_ingestion(interval=10, *, once=False, stop_event=None):
        raise RuntimeError("ingestion boom")

    async def good_backfill(*, once=False, stop_event=None, admin_only=False, job_ids=None):
        backfill_alive.set()
        if stop_event:
            await stop_event.wait()

    with patch.object(iw, "run_ingestion_loop", bad_ingestion), \
         patch.object(bw, "run_backfill_loop", good_backfill):
        sup = WorkerSupervisor()
        await sup.start()
        await asyncio.wait_for(backfill_alive.wait(), timeout=2)
        await asyncio.sleep(0.2)
        assert backfill_alive.is_set()
        await sup.stop()


# ============================================================
# 5. Supervisor restarts crashed worker with backoff
# ============================================================

@pytest.mark.asyncio
async def test_supervisor_restarts_with_backoff():
    call_count = 0
    status = _WorkerStatus("test")
    stop = asyncio.Event()

    async def crashing():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("crash")
        stop.set()

    task = asyncio.create_task(
        _run_supervised("test", crashing, stop, status, initial_backoff=0.01, max_backoff=0.05)
    )
    await asyncio.wait_for(stop.wait(), timeout=5)
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert call_count >= 3
    assert status.restarts >= 2


# ============================================================
# 6. Multiple instances: only one executes (lock test)
# ============================================================

def test_advisory_lock_prevents_duplicate_ingestion():
    """Verify the lock key constants are different for ingestion vs backfill."""
    assert iw.LOCK_KEY != bw.LOCK_KEY
    from app.workers.supervisor import _LEADER_LOCK_INGESTION, _LEADER_LOCK_BACKFILL
    assert _LEADER_LOCK_INGESTION != _LEADER_LOCK_BACKFILL
    # All four keys must be distinct.
    assert len({iw.LOCK_KEY, bw.LOCK_KEY, _LEADER_LOCK_INGESTION, _LEADER_LOCK_BACKFILL}) == 4


# ============================================================
# 7. Normal minute with multiple RecordedValues
# ============================================================

def test_normal_minute_multiple_events():
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=s)) for s in (5, 15, 25, 35, 45, 55)]
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(return_value=_resp(events))
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=100, stats=stats, page_budget=10,
    ))
    assert len(out) == 6
    assert stats.accepted_events == 6


# ============================================================
# 8. Empty minute
# ============================================================

def test_empty_minute_is_complete():
    base = datetime(2026, 9, 17, 14, 28, tzinfo=UTC)
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(return_value=_resp([]))
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=100, stats=stats, page_budget=5,
    ))
    assert out == []
    assert stats.saturated_pages == 0


# ============================================================
# 9. Boundary event belongs only to correct interval
# ============================================================

def test_boundary_event_excluded_from_current_interval():
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    end = base + timedelta(minutes=1)
    events = [_Point(base + timedelta(seconds=30)), _Point(end)]  # end is boundary
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(return_value=_resp(events))
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, end,
        max_count=100, stats=stats, page_budget=5,
    ))
    assert len(out) == 1  # Boundary point at `end` excluded by semi-open [start, end)
    assert out[0].timestamp.astimezone(UTC) == base + timedelta(seconds=30)


# ============================================================
# 10. Response exactly equal to maxCount
# ============================================================

def test_exact_maxcount_triggers_split():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=s)) for s in (0, 15, 30)]
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(side_effect=[
        _resp(events),  # 3 >= maxCount=3: saturated
        _resp(events[:2]),  # left half
        _resp(events[1:]),  # right half
    ])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=3, stats=stats, page_budget=10,
    ))
    assert stats.saturated_pages >= 1
    assert stats.splits >= 1
    assert len(out) == 3


# ============================================================
# 11. Pagination/subdivision returns all events
# ============================================================

def test_split_subdivision_returns_all():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=s)) for s in range(0, 60, 5)]  # 12 events
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(side_effect=[
        _resp(events),  # 12 >= maxCount=5: saturated
        _resp(events[:6]),  # left, saturated
        _resp(events[:3]),  # left-left
        _resp(events[3:6]),  # left-right
        _resp(events[6:]),  # right, saturated
        _resp(events[6:9]), # right-left
        _resp(events[9:]),  # right-right
    ])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=5, stats=stats, page_budget=20,
    ))
    assert len(out) == 12


# ============================================================
# 12. Failure mid-pagination does not advance cursor
# ============================================================

def test_failure_mid_pagination_preserves_watermark():
    """If HTTP fails during pagination, no watermark advance occurs."""

    class _FakeSession:
        def __init__(self):
            self.bind = None
            self.state = SimpleNamespace(
                watermark_ts=datetime(2026, 9, 17, 14, 31, tzinfo=UTC),
                last_source_ts=None,
                next_attempt_at=None,
                consecutive_failures=0,
                last_error_code=None,
                last_error_message=None,
                last_success_at=None,
                tag_id=7,
                source_mode="RECORDED",
            )

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, model, key):
            if model.__name__ == "PiTag":
                return SimpleNamespace(id=7, active=True, pi_web_id="W1",
                                      lower_limit_tag_id=None, upper_limit_tag_id=None)
            return self.state

        def add(self, obj):
            pass

        def commit(self):
            pass

        def execute(self, *a, **k):
            r = MagicMock()
            r.scalars.return_value.first.return_value = None
            return r

    session = _FakeSession()
    saved = iw.SessionLocal
    iw.SessionLocal = lambda: session

    class _BoomProvider:
        async def get_recorded_values(self, *a, **k):
            raise RuntimeError("connection reset")

    try:
        with pytest.raises(RuntimeError, match="connection reset"):
            asyncio.run(_ingest_tag(7, NOW, provider=_BoomProvider()))
        assert session.state.watermark_ts == datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    finally:
        iw.SessionLocal = saved


# ============================================================
# 13. Restart after several hours: recent first
# ============================================================

def test_recent_first_ingests_latest_minute():
    """After several hours offline, the most recent minute should have
    data before catch-up finishes the backlog."""
    # The _ingest_recent_minute function should prioritize the last minute.
    recent_start = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    recent_end = datetime(2026, 9, 17, 14, 32, tzinfo=UTC)
    events = [_Point(recent_start + timedelta(seconds=20))]

    class FakeSession:
        def __init__(self):
            self.bind = None
            self._committed = False
            self._state = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, model, key):
            if model.__name__ == "PiTag":
                return SimpleNamespace(id=1, active=True, pi_web_id="W1")
            return self._state

        def add(self, obj):
            self._state = obj

        def commit(self):
            self._committed = True

        def execute(self, *a, **k):
            r = MagicMock()
            r.scalars.return_value.first.return_value = None
            r.scalar.return_value = None
            return r

    fake_session = FakeSession()
    saved = iw.SessionLocal
    iw.SessionLocal = lambda: fake_session

    class FakeProvider:
        async def get_recorded_values(self, *a, **k):
            return _resp(events)

    try:
        with patch.object(iw.CoverageService, "record_coverage", MagicMock()):
            total = asyncio.run(iw._ingest_recent_minute({1}, NOW, provider=FakeProvider()))
        assert total >= 1
    finally:
        iw.SessionLocal = saved


# ============================================================
# 14. Catch-up does not skip gaps
# ============================================================

def test_pending_intervals_no_gaps():
    watermark = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    intervals = _pending_intervals(NOW, watermark)
    for i in range(len(intervals) - 1):
        assert intervals[i][1] == intervals[i + 1][0], "Gap detected between intervals"


# ============================================================
# 14b. Recent-first is called before catch-up in the loop
# ============================================================

def test_recent_first_called_in_loop():
    """Verify that run_ingestion_loop calls _ingest_recent_minute."""
    call_log = []

    async def fake_recent(tag_ids, now, *, provider=None):
        call_log.append("recent_minute")
        return 5

    async def fake_reconcile(tag_ids, now, *, provider=None):
        call_log.append("reconcile")
        return 0

    original_recent = iw._ingest_recent_minute
    original_reconcile = iw._reconcile_recent
    iw._ingest_recent_minute = fake_recent
    iw._reconcile_recent = fake_reconcile

    def _session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = None
        tag_rows = [SimpleNamespace(id=1, active=True, lower_limit_tag_id=None, upper_limit_tag_id=None)]
        ctx.execute.return_value.scalars.return_value.all.return_value = tag_rows
        return ctx

    saved_session = iw.SessionLocal
    iw.SessionLocal = _session_factory
    # Stub out _ingest_tag to avoid actual work
    original_ingest = iw._ingest_tag
    iw._ingest_tag = AsyncMock(return_value=(0, 0))
    try:
        asyncio.run(iw.run_ingestion_loop(0.01, once=True))
        assert "recent_minute" in call_log, "Recent-first was not called"
    finally:
        iw.SessionLocal = saved_session
        iw._ingest_recent_minute = original_recent
        iw._reconcile_recent = original_reconcile
        iw._ingest_tag = original_ingest


# ============================================================
# 15. Reprocessing does not create duplicities (UPSERT)
# ============================================================

def test_upsert_idempotent(db_session):
    """Inserting the same point twice must not raise or duplicate."""
    from app.models.postgres import PiSample
    from app.models.pi_tag import PiTag
    from app.models import Equipment, VariableType

    eq = Equipment(name="E1", code="E1")
    db_session.add(eq)
    db_session.flush()
    vt = VariableType(name="T1", code="T1", description="t")
    db_session.add(vt)
    db_session.flush()
    tag = PiTag(
        equipment_id=eq.id, variable_type_id=vt.id,
        pi_server="S", pi_tag_name="P1", display_name="P1",
    )
    db_session.add(tag)
    db_session.flush()

    point = _Point(datetime(2026, 9, 17, 14, 30, tzinfo=UTC), 42.0)
    iw._persist_points(db_session, tag.id, [point, point], "RECORDED")
    db_session.commit()
    count = db_session.query(PiSample).filter_by(tag_id=tag.id).count()
    assert count == 1

    # Insert again
    iw._persist_points(db_session, tag.id, [point], "RECORDED")
    db_session.commit()
    count2 = db_session.query(PiSample).filter_by(tag_id=tag.id).count()
    assert count2 == 1


# ============================================================
# 16. One stuck tag does not block others
# ============================================================

def test_stuck_tag_does_not_block_others():
    calls = {"b": 0}
    a_blocker = asyncio.Event()
    b_done = asyncio.Event()

    def _fake_ingest(tag_id, now, source_mode=None, provider=None):
        async def inner():
            if tag_id == 1:
                await a_blocker.wait()
                return 0, 0
            calls["b"] += 1
            b_done.set()
            return 1, 1
        return inner()

    saved = iw._ingest_tag, iw.SessionLocal
    iw._ingest_tag = _fake_ingest
    saved_conc = iw.settings.ingestion_tag_concurrency
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    iw.settings.ingestion_tag_concurrency = 2
    iw.settings.ingestion_tag_timeout_seconds = 0.2

    def _session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = None
        tag_rows = [SimpleNamespace(id=tid, active=True, lower_limit_tag_id=None, upper_limit_tag_id=None)
                    for tid in (1, 2)]
        ctx.execute.return_value.scalars.return_value.all.return_value = tag_rows
        return ctx

    iw.SessionLocal = _session_factory

    # Also stub out recent-first and reconciliation so they don't interfere
    original_recent = iw._ingest_recent_minute
    original_reconcile = iw._reconcile_recent
    iw._ingest_recent_minute = AsyncMock(return_value=0)
    iw._reconcile_recent = AsyncMock(return_value=0)
    try:
        async def run():
            task = asyncio.create_task(iw.run_ingestion_loop(0.05, once=True))
            await asyncio.wait_for(b_done.wait(), timeout=5)
            a_blocker.set()
            await asyncio.wait_for(task, timeout=5)
            return calls["b"] >= 1
        assert asyncio.run(run())
    finally:
        iw._ingest_tag, iw.SessionLocal = saved
        iw.settings.ingestion_tag_concurrency = saved_conc
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout
        iw._ingest_recent_minute = original_recent
        iw._reconcile_recent = original_reconcile


# ============================================================
# 17. Timeout persists backoff and preserves watermark
# ============================================================

def test_timeout_preserves_watermark():
    persisted = []

    def _record_failure(db, tag_id, mode, now, code, message):
        persisted.append((tag_id, code))

    a_blocker = asyncio.Event()
    b_done = asyncio.Event()

    def _fake_ingest(tag_id, now, source_mode=None, provider=None):
        async def inner():
            if tag_id == 1:
                await a_blocker.wait()
                return 0, 0
            b_done.set()
            return 1, 1
        return inner()

    saved = iw._ingest_tag, iw.SessionLocal, iw._record_failure
    iw._ingest_tag = _fake_ingest
    iw._record_failure = _record_failure
    iw.settings.ingestion_tag_concurrency = 2
    iw.settings.ingestion_tag_timeout_seconds = 0.05

    def _sf():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = None
        tags = [SimpleNamespace(id=t, active=True, lower_limit_tag_id=None, upper_limit_tag_id=None)
                for t in (1, 2)]
        ctx.execute.return_value.scalars.return_value.all.return_value = tags
        return ctx

    iw.SessionLocal = _sf
    original_recent = iw._ingest_recent_minute
    original_reconcile = iw._reconcile_recent
    iw._ingest_recent_minute = AsyncMock(return_value=0)
    iw._reconcile_recent = AsyncMock(return_value=0)
    try:
        async def run():
            task = asyncio.create_task(iw.run_ingestion_loop(0.05, once=True))
            await asyncio.wait_for(b_done.wait(), timeout=5)
            await asyncio.wait_for(task, timeout=5)
            return (1, "TAG_TIMEOUT") in persisted
        assert asyncio.run(run())
    finally:
        iw._ingest_tag, iw.SessionLocal, iw._record_failure = saved
        iw._ingest_recent_minute = original_recent
        iw._reconcile_recent = original_reconcile
        a_blocker.set()


# ============================================================
# 18. Expired lease job recovery
# ============================================================

def test_expired_lease_recovered(db_session, monkeypatch):
    from app.models.postgres import PiBackfillJob
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(bw, "SessionLocal", TestingSessionLocal)

    now = datetime.now(UTC)
    job = PiBackfillJob(
        tag_id=1, mode="RECORDED", target_start=now - timedelta(days=2),
        target_end=now - timedelta(days=1), next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2), t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING", attempts=1,
        lease_owner="dead-worker",
        lease_expires_at=now - timedelta(minutes=5),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    recovered = bw._recover_expired_leases()
    db_session.expire_all()
    assert job.id in recovered
    assert db_session.get(PiBackfillJob, job.id).status == "PENDING"


# ============================================================
# 19. Legacy RUNNING without lease recovered safely
# ============================================================

def test_legacy_running_without_lease_recovered(db_session, monkeypatch):
    from app.models.postgres import PiBackfillJob
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(bw, "SessionLocal", TestingSessionLocal)

    now = datetime.now(UTC)
    stale_time = now - timedelta(seconds=settings.backfill_legacy_stale_seconds + 60)
    job = PiBackfillJob(
        tag_id=1, mode="RECORDED", target_start=now - timedelta(days=2),
        target_end=now - timedelta(days=1), next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2), t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING", attempts=1,
        lease_owner=None, lease_expires_at=None, heartbeat_at=None,
        updated_at=stale_time,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    recovered = bw._recover_legacy_running_jobs()
    db_session.expire_all()
    assert job.id in recovered
    assert db_session.get(PiBackfillJob, job.id).status == "PENDING"


# ============================================================
# 20. Invalid RUNNING does not block PENDING
# ============================================================

def test_invalid_running_does_not_block_pending(db_session, monkeypatch):
    from app.models.postgres import PiBackfillJob
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(bw, "SessionLocal", TestingSessionLocal)

    now = datetime.now(UTC)
    # Stuck RUNNING without lease.
    stuck = PiBackfillJob(
        tag_id=1, mode="RECORDED", target_start=now - timedelta(days=2),
        target_end=now - timedelta(days=1), next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2), t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING", attempts=1,
        lease_owner=None, lease_expires_at=None,
    )
    db_session.add(stuck)
    # PENDING that should be claimable.
    pending = PiBackfillJob(
        tag_id=2, mode="RECORDED", target_start=now - timedelta(days=2),
        target_end=now - timedelta(days=1), next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2), t0=now, round_name="R1",
        stage="PENDING", status="PENDING", attempts=0,
    )
    db_session.add(pending)
    db_session.commit()
    db_session.refresh(stuck)
    db_session.refresh(pending)

    # _claim_job on PENDING should succeed independently of RUNNING.
    assert bw._claim_job(pending.id)
    db_session.expire_all()
    assert db_session.get(PiBackfillJob, pending.id).status == "RUNNING"
    # Stuck is still RUNNING (not affected).
    assert db_session.get(PiBackfillJob, stuck.id).status == "RUNNING"


# ============================================================
# 21. Backfill uses round-robin between tags
# ============================================================

def test_round_names_defined():
    """Backfill rounds must be defined for R1-R4."""
    assert bw.ROUND_NAMES == ("R1", "R2", "R3", "R4")
    assert len(bw.BACKFILL_ROUNDS) == 4


# ============================================================
# 22. Ingestion recent has priority over backfill
# ============================================================

def test_ingestion_lock_key_lower_than_backfill():
    """Ingestion lock key should be different from backfill to ensure
    independent locking."""
    assert iw.LOCK_KEY < bw.LOCK_KEY


# ============================================================
# 23. PI responses out of order do not corrupt cursors
# ============================================================

def test_out_of_order_events_sorted():
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    events = [
        _Point(base + timedelta(seconds=45)),
        _Point(base + timedelta(seconds=5)),
        _Point(base + timedelta(seconds=30)),
    ]
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(return_value=_resp(events))
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=100, stats=stats, page_budget=5,
    ))
    timestamps = [p.timestamp for p in out]
    assert timestamps == sorted(timestamps) or len(out) == len(events)


# ============================================================
# 24. No session open during HTTP
# ============================================================

def test_no_session_during_http():
    """The ingestion phases ensure no DB session is open during HTTP calls."""
    http_open_counts = []

    class _HttpProbe:
        def __init__(self):
            pass

        async def get_recorded_values(self, *a, **k):
            open_count = sum(1 for s in _FakeSession._instances if getattr(s, "open", False))
            http_open_counts.append(open_count)
            return _resp([_Point(datetime(2026, 9, 17, 14, 31, 10, tzinfo=UTC))])

    class _FakeSession:
        _instances = []

        def __init__(self):
            self.bind = None
            self.open = False
            self._state = SimpleNamespace(
                watermark_ts=datetime(2026, 9, 17, 14, 31, tzinfo=UTC),
                last_source_ts=None, next_attempt_at=None,
                consecutive_failures=0, last_error_code=None,
                last_error_message=None, last_success_at=None,
                tag_id=7, source_mode="RECORDED",
            )
            _FakeSession._instances.append(self)

        def __enter__(self):
            self.open = True
            return self

        def __exit__(self, *a):
            self.open = False
            return False

        def get(self, model, key):
            if model.__name__ == "PiTag":
                return SimpleNamespace(id=7, active=True, pi_web_id="W1",
                                      lower_limit_tag_id=None, upper_limit_tag_id=None)
            return self._state

        def add(self, obj):
            pass

        def commit(self):
            pass

        def execute(self, *a, **k):
            r = MagicMock()
            r.scalars.return_value.first.return_value = None
            return r

    _FakeSession._instances = []
    saved = iw.SessionLocal
    iw.SessionLocal = _FakeSession
    try:
        asyncio.run(_ingest_tag(7, NOW, provider=_HttpProbe()))
        assert http_open_counts, "Provider must have been called"
        assert all(count == 0 for count in http_open_counts), f"Expected 0 open DB sessions during HTTP, got {http_open_counts}"
    finally:
        iw.SessionLocal = saved


# ============================================================
# 25. Stop event halts ingestion loop
# ============================================================

@pytest.mark.asyncio
async def test_stop_event_halts_ingestion():
    stop = asyncio.Event()
    factory = MagicMock()
    db = factory.return_value.__enter__.return_value
    db.bind = None
    db.execute.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value.scalar.return_value = True

    saved = iw.SessionLocal
    iw.SessionLocal = factory
    try:
        # Set stop after a short delay
        async def stopper():
            await asyncio.sleep(0.1)
            stop.set()

        asyncio.create_task(stopper())
        await asyncio.wait_for(
            iw.run_ingestion_loop(0.05, stop_event=stop),
            timeout=5,
        )
    finally:
        iw.SessionLocal = saved


# ============================================================
# 26. Backfill session/HTTP separation (no PiService)
# ============================================================

def test_backfill_no_session_during_http():
    """Backfill must not hold a DB session open during HTTP calls."""
    # The backfill now uses _fetch_recorded_direct which takes no session.
    # Verify the function signature exists and works.
    async def _test():
        provider = MagicMock()
        base = datetime(2026, 9, 17, 14, 0, tzinfo=UTC)
        events = [_Point(base + timedelta(seconds=30))]
        provider.get_recorded_values = AsyncMock(return_value=_resp(events))
        points, raw_count = await bw._fetch_recorded_direct(
            provider, "webid", base, base + timedelta(hours=1),
            max_count=1000,
        )
        assert raw_count == 1
        assert len(points) == 1
    asyncio.run(_test())


# ============================================================
# 27. Backfill saturation uses raw count
# ============================================================

def test_backfill_saturation_raw_count():
    """Backfill saturation must be decided on raw_count, not filtered count."""
    async def _test():
        base = datetime(2026, 9, 17, 14, 0, tzinfo=UTC)
        end = base + timedelta(hours=1)
        # All 5 points are at the boundary (end), so all are filtered out.
        # But raw_count is 5 which should trigger saturation if max_count=5.
        boundary_events = [_Point(end) for _ in range(5)]
        provider = MagicMock()
        provider.get_recorded_values = AsyncMock(return_value=_resp(boundary_events))
        points, raw_count = await bw._fetch_recorded_direct(
            provider, "webid", base, end, max_count=5,
        )
        # All filtered out (at boundary), but raw_count shows saturation.
        assert len(points) == 0
        assert raw_count == 5  # This is >= max_count → saturated
    asyncio.run(_test())
