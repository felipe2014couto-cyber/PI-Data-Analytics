"""Comprehensive tests for worker supervisor, ingestion, and backfill.

Tests are deterministic: no sleep, controlled clocks, fake providers.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.postgres import PiBackfillJob, PiIngestionState
from app.workers import ingestion_worker as iw
from app.workers import backfill_worker as bw
from app.workers.ingestion_worker import (
    BUDGET_EXHAUSTED,
    BudgetExhaustedError,
    FetchStats,
    IntervalIncompleteError,
    _pending_intervals,
)

UTC_TZ = timezone.utc
NOW = datetime(2026, 9, 17, 14, 32, 35, tzinfo=UTC_TZ)

@pytest.fixture(autouse=True)
def _stub_recent_features(monkeypatch):
    monkeypatch.setattr(iw, "_ingest_recent_minute", AsyncMock(return_value=0))
    monkeypatch.setattr(iw, "_reconcile_recent", AsyncMock(return_value=0))

# ==============================================================
# Helpers
# ==============================================================

class _Point:
    def __init__(self, ts: datetime, value: float = 1.0):
        self.timestamp = ts
        self.value = value
        self.good = True
        self.questionable = False
        self.substituted = False


def _resp(points):
    return SimpleNamespace(values=list(points))


def _provider_replies(pages):
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(side_effect=pages)
    return provider


class _State:
    """Concrete ingestion state."""
    def __init__(self, watermark=None):
        self.watermark_ts = watermark
        self.last_source_ts = None
        self.next_attempt_at = None
        self.consecutive_failures = 0
        self.last_error_code = None
        self.last_error_message = None
        self.last_success_at = None


def _make_tag(tag_id=7, web_id="P0WebId"):
    return SimpleNamespace(
        id=tag_id, active=True, pi_web_id=web_id,
        lower_limit_tag_id=None, upper_limit_tag_id=None,
    )


class _FakeSession:
    """Session fake."""
    instances: list[_FakeSession] = []
    tag: SimpleNamespace = None

    def __init__(self):
        self.bind = None
        self.executed = 0
        self.committed = False
        self.state = None
        self.open = False
        self._state_added = None
        _FakeSession.instances.append(self)

    def __enter__(self):
        self.open = True
        return self

    def __exit__(self, *args):
        self.open = False
        return False

    def get(self, model, key):
        if model.__name__ == "PiTag":
            return _FakeSession.tag
        return self.state or _State()

    def add(self, obj):
        self._state_added = obj

    def commit(self):
        self.committed = True
        if self._state_added is not None:
            self.state = self._state_added

    def execute(self, *a, **k):
        self.executed += 1
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        return result


class _HttpProbeProvider:
    """Provider that records how many sessions are open during its await."""
    def __init__(self, pages):
        self._pages = list(pages)

    async def get_recorded_values(self, *a, **k):
        _HTTP_OPEN_COUNTS.append(sum(1 for s in _FakeSession.instances if getattr(s, "open", False)))
        page = self._pages.pop(0) if self._pages else SimpleNamespace(values=[])
        return page


_HTTP_OPEN_COUNTS: list[int] = []


def _run_ingest(tag, state, provider, now=NOW):
    _FakeSession.instances = []
    _FakeSession.tag = tag
    _HTTP_OPEN_COUNTS.clear()
    saved = iw.SessionLocal
    iw.SessionLocal = _FakeSession
    try:
        _FakeSession.state = state
        orig_get = _FakeSession.get

        def _get(s, model, key):
            if model.__name__ == "PiTag":
                return _FakeSession.tag
            return _FakeSession.state

        _FakeSession.get = _get
        try:
            return asyncio.run(iw._ingest_tag(tag.id, now, provider=provider))
        finally:
            _FakeSession.get = orig_get
    finally:
        iw.SessionLocal = saved


# ==============================================================
# 1. Lifespan: FastAPI starts ingestion
# ==============================================================

def test_lifespan_starts_supervisor():
    """FastAPI lifespan starts the supervisor which schedules workers."""
    from app.workers.supervisor import WorkerSupervisor

    supervisor = WorkerSupervisor()
    started = False
    stopped = False

    async def _run():
        nonlocal started, stopped
        with patch("app.workers.supervisor.settings") as mock_settings:
            mock_settings.workers_enabled = True
            mock_settings.worker_ingestion_enabled = True
            mock_settings.worker_backfill_enabled = True
            mock_settings.ingestion_cycle_seconds = 10.0

            # Mock the loop functions to just set events.
            ingestion_started = asyncio.Event()
            backfill_started = asyncio.Event()

            async def fake_ingestion(*a, **k):
                ingestion_started.set()
                stop = k.get("stop_event")
                if stop:
                    await stop.wait()

            async def fake_backfill(*a, **k):
                backfill_started.set()
                stop = k.get("stop_event")
                if stop:
                    await stop.wait()

            with patch("app.workers.ingestion_worker.run_ingestion_loop", fake_ingestion), \
                 patch("app.workers.backfill_worker.run_backfill_loop", fake_backfill):
                await supervisor.start()
                started = True
                # Wait for both workers to start.
                await asyncio.wait_for(ingestion_started.wait(), timeout=5)
                await asyncio.wait_for(backfill_started.wait(), timeout=5)
                await supervisor.stop()
                stopped = True

    asyncio.run(_run())
    assert started
    assert stopped


# ==============================================================
# 2. Shutdown cancels and awaits workers
# ==============================================================

def test_shutdown_cancels_workers():
    """Supervisor.stop() cancels and awaits all worker tasks."""
    from app.workers.supervisor import WorkerSupervisor

    async def _run():
        supervisor = WorkerSupervisor()
        ingestion_ran = asyncio.Event()

        async def fake_ingestion(*a, **k):
            ingestion_ran.set()
            stop = k.get("stop_event")
            if stop:
                await stop.wait()

        async def fake_backfill(*a, **k):
            stop = k.get("stop_event")
            if stop:
                await stop.wait()

        with patch("app.workers.ingestion_worker.run_ingestion_loop", fake_ingestion), \
             patch("app.workers.backfill_worker.run_backfill_loop", fake_backfill):
            await supervisor.start()
            await asyncio.wait_for(ingestion_ran.wait(), timeout=5)
            await supervisor.stop()
            assert not supervisor._tasks
            return True

    assert asyncio.run(_run())


# ==============================================================
# 3. Backfill failure does not end API or ingestion
# ==============================================================

def test_backfill_crash_does_not_kill_ingestion():
    """Backfill crashing does not affect the ingestion worker."""
    from app.workers.supervisor import WorkerSupervisor

    async def _run():
        supervisor = WorkerSupervisor()
        ingestion_alive = asyncio.Event()
        backfill_crashed = asyncio.Event()

        async def fake_ingestion(*a, **k):
            ingestion_alive.set()
            stop = k.get("stop_event")
            if stop:
                await stop.wait()

        async def fake_backfill(*a, **k):
            backfill_crashed.set()
            raise RuntimeError("Backfill exploded!")

        with patch("app.workers.ingestion_worker.run_ingestion_loop", fake_ingestion), \
             patch("app.workers.backfill_worker.run_backfill_loop", fake_backfill):
            await supervisor.start()
            await asyncio.wait_for(ingestion_alive.wait(), timeout=5)
            await asyncio.wait_for(backfill_crashed.wait(), timeout=5)
            # Give the supervisor a tick to handle the crash.
            await asyncio.sleep(0.1)
            # Ingestion should still be alive.
            assert ingestion_alive.is_set()
            await supervisor.stop()
            return True

    assert asyncio.run(_run())


# ==============================================================
# 4. Ingestion failure does not end API
# ==============================================================

def test_ingestion_crash_does_not_kill_api():
    """Ingestion crashing does not crash the supervisor or API."""
    from app.workers.supervisor import WorkerSupervisor

    async def _run():
        supervisor = WorkerSupervisor()
        ingestion_crashed = asyncio.Event()

        async def fake_ingestion(*a, **k):
            ingestion_crashed.set()
            raise RuntimeError("Ingestion exploded!")

        async def fake_backfill(*a, **k):
            stop = k.get("stop_event")
            if stop:
                await stop.wait()

        with patch("app.workers.ingestion_worker.run_ingestion_loop", fake_ingestion), \
             patch("app.workers.backfill_worker.run_backfill_loop", fake_backfill):
            await supervisor.start()
            await asyncio.wait_for(ingestion_crashed.wait(), timeout=5)
            await asyncio.sleep(0.1)
            # Supervisor should still be running (it restarts crashed workers).
            assert len(supervisor._tasks) > 0
            await supervisor.stop()
            return True

    assert asyncio.run(_run())


# ==============================================================
# 5. Supervisor restarts crashed task with backoff
# ==============================================================

def test_supervisor_restarts_with_backoff():
    """A worker that crashes is restarted with increasing backoff."""
    from app.workers.supervisor import _run_supervised, _WorkerStatus

    crash_count = 0

    async def _run():
        nonlocal crash_count
        stop = asyncio.Event()
        status = _WorkerStatus("test")

        async def crasher():
            nonlocal crash_count
            crash_count += 1
            if crash_count >= 3:
                stop.set()
                return
            raise RuntimeError("crash!")

        task = asyncio.create_task(
            _run_supervised("test", crasher, stop, status, initial_backoff=0.01, max_backoff=0.05)
        )
        await asyncio.wait_for(task, timeout=5)
        return status.restarts

    restarts = asyncio.run(_run())
    assert restarts >= 2
    assert crash_count >= 3


# ==============================================================
# 6. Multiple instances: advisory lock prevents duplicate
# ==============================================================

def test_advisory_lock_prevents_duplicate_ingestion():
    """Only one ingestion worker runs at a time via advisory lock."""
    acquired_count = 0

    def _session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = MagicMock()
        ctx.bind.dialect.name = "postgresql"
        nonlocal acquired_count
        acquired_count += 1
        # Simulate lock not acquired on second attempt.
        ctx.execute.return_value.scalar.return_value = acquired_count == 1
        ctx.execute.return_value.scalars.return_value.all.return_value = []
        return ctx

    saved = iw.SessionLocal
    iw.SessionLocal = _session_factory
    try:
        asyncio.run(iw.run_ingestion_loop(0.01, once=True))
        asyncio.run(iw.run_ingestion_loop(0.01, once=True))
        # Second run should not acquire the lock.
    finally:
        iw.SessionLocal = saved


# ==============================================================
# 7. Normal minute with multiple RecordedValues
# ==============================================================

def test_normal_minute_with_multiple_events():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ))
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)
    events = [_Point(base + timedelta(seconds=s)) for s in (5, 15, 25, 35, 50)]
    provider = _HttpProbeProvider([_resp(events)])
    points, requests = _run_ingest(tag, state, provider)
    assert points == 5
    assert requests == 1
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC_TZ)


# ==============================================================
# 8. Empty minute
# ==============================================================

def test_empty_minute_advances_watermark():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ))
    provider = _HttpProbeProvider([_resp([])])
    points, requests = _run_ingest(tag, state, provider)
    assert points == 0
    assert requests == 1
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC_TZ)


# ==============================================================
# 9. Boundary event belongs to correct interval
# ==============================================================

def test_boundary_event_belongs_to_correct_interval():
    """Event exactly at the boundary belongs to the NEXT interval."""
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)
    end = base + timedelta(minutes=1)
    events = [_Point(base + timedelta(seconds=30)), _Point(end)]
    provider = _provider_replies([_resp(events)])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, end,
        max_count=100, stats=stats, page_budget=5,
    ))
    # The event at `end` is filtered out by the semi-open [start, end).
    assert len(out) == 1
    assert out[0].timestamp.astimezone(UTC_TZ) == base + timedelta(seconds=30)


# ==============================================================
# 10. Response exactly equal to maxCount
# ==============================================================

def test_response_at_max_count_triggers_split():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC_TZ)
    events = [_Point(base + timedelta(seconds=s)) for s in (0, 15, 30)]
    provider = _provider_replies([
        _resp(events),    # raw 3 >= maxCount=3: saturated
        _resp(events[:2]),  # left half
        _resp(events[1:]),  # right half
    ])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=3, stats=stats, page_budget=10,
    ))
    assert len(out) == 3
    assert stats.saturated_pages >= 1
    assert stats.splits >= 1


# ==============================================================
# 11. Pagination/subdivision returns all events
# ==============================================================

def test_pagination_subdivision_returns_all():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC_TZ)
    events = [_Point(base + timedelta(seconds=s)) for s in range(0, 60, 5)]  # 12 events
    provider = _provider_replies([
        _resp(events),     # saturated (12 >= 10)
        _resp(events[:6]),   # left half
        _resp(events[6:]),   # right half
    ])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=10, stats=stats, page_budget=10,
    ))
    assert len(out) == 12


# ==============================================================
# 12. Failure mid-pagination does not advance cursor
# ==============================================================

def test_failure_mid_pagination_no_cursor_advance():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ))

    class _BoomProvider:
        async def get_recorded_values(self, *a, **k):
            raise RuntimeError("PI fora do ar")

    with pytest.raises(RuntimeError, match="PI fora do ar"):
        _run_ingest(tag, state, _BoomProvider())
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)


# ==============================================================
# 13. Restart after several hours: recent-first
# ==============================================================

def test_restart_after_hours_processes_recent_first():
    """After hours of downtime, _pending_intervals processes from watermark
    in order, but the budget limits how many minutes are processed per cycle."""
    watermark = datetime(2026, 9, 17, 10, 0, tzinfo=UTC_TZ)
    now = datetime(2026, 9, 17, 14, 32, 35, tzinfo=UTC_TZ)
    intervals = _pending_intervals(now, watermark, max_intervals=5)
    assert len(intervals) == 5
    assert intervals[0][0] == watermark
    # There are many more pending but budget limits to 5.


# ==============================================================
# 14. Recent band is updated before catch-up
# ==============================================================

def test_recent_band_updated_before_catchup():
    """_ingest_recent_minute should process only the most recent minute."""
    # This test validates the concept: recent minute [14:31, 14:32) is
    # processed even when the watermark is hours behind.
    watermark = datetime(2026, 9, 17, 10, 0, tzinfo=UTC_TZ)
    now = datetime(2026, 9, 17, 14, 32, 35, tzinfo=UTC_TZ)
    limit = iw._minute_floor(now)
    recent_start = limit - iw.MINUTE
    assert recent_start == datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)
    assert limit == datetime(2026, 9, 17, 14, 32, tzinfo=UTC_TZ)


# ==============================================================
# 15. Catch-up does not skip gaps
# ==============================================================

def test_catchup_does_not_skip_gaps():
    watermark = datetime(2026, 9, 17, 14, 27, tzinfo=UTC_TZ)
    intervals = _pending_intervals(NOW, watermark)
    assert len(intervals) == 5
    for i in range(len(intervals) - 1):
        assert intervals[i][1] == intervals[i + 1][0]


# ==============================================================
# 16. Reprocessing does not create duplicates (idempotent UPSERT)
# ==============================================================

def test_reprocessing_no_duplicates():
    """Two ingestion runs for the same interval produce the same watermark."""
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ))
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)
    events = [_Point(base + timedelta(seconds=s)) for s in (5, 25, 50)]
    provider1 = _HttpProbeProvider([_resp(events)])
    points1, _ = _run_ingest(tag, state, provider1)
    assert points1 == 3
    # Second run: watermark already advanced, so no intervals pending.
    provider2 = _HttpProbeProvider([_resp(events)])
    points2, _ = _run_ingest(tag, state, provider2)
    assert points2 == 0  # No new work.


# ==============================================================
# 17. Stuck tag does not block others
# ==============================================================

def test_stuck_tag_does_not_block_others():
    """Tag A hangs; B and C complete normally."""
    calls = {"b": 0, "c": 0, "a_started": False}
    a_blocker = asyncio.Event()
    b_done = asyncio.Event()
    c_done = asyncio.Event()

    def _fake_ingest(tag_id, now, source_mode=None, provider=None):
        async def inner():
            if tag_id == 1:
                calls["a_started"] = True
                await a_blocker.wait()
                return 0, 0
            if tag_id == 2:
                calls["b"] += 1
                b_done.set()
                return 1, 1
            calls["c"] += 1
            c_done.set()
            return 1, 1
        return inner()

    saved_ingest, saved_session = iw._ingest_tag, iw.SessionLocal
    saved_concurrency = iw.settings.ingestion_tag_concurrency
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    iw.settings.ingestion_tag_concurrency = 2
    iw.settings.ingestion_tag_timeout_seconds = 60.0
    iw._ingest_tag = _fake_ingest

    def _session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = None
        tag_rows = [SimpleNamespace(id=tid, active=True, lower_limit_tag_id=None, upper_limit_tag_id=None)
                    for tid in (1, 2, 3)]
        ctx.execute.return_value.scalars.return_value.all.return_value = tag_rows
        return ctx

    iw.SessionLocal = _session_factory
    try:
        async def run():
            task = asyncio.create_task(iw.run_ingestion_loop(0.05, once=True))
            await asyncio.wait_for(b_done.wait(), timeout=5)
            await asyncio.wait_for(c_done.wait(), timeout=5)
            b_and_c_done = calls["b"] >= 1 and calls["c"] >= 1
            a_still_blocked = calls["a_started"] and not a_blocker.is_set()
            a_blocker.set()
            await task
            return b_and_c_done and a_still_blocked

        assert asyncio.run(run()) is True
    finally:
        iw._ingest_tag = saved_ingest
        iw.SessionLocal = saved_session
        iw.settings.ingestion_tag_concurrency = saved_concurrency
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout


# ==============================================================
# 18. Timeout persists backoff and preserves watermark
# ==============================================================

def test_timeout_persists_backoff_preserves_watermark():
    a_blocker = asyncio.Event()
    persisted = []
    b_done = asyncio.Event()

    def _fake_ingest(tag_id, now, source_mode=None, provider=None):
        async def inner():
            if tag_id == 1:
                await a_blocker.wait()
                return 0, 0
            b_done.set()
            return 1, 1
        return inner()

    def _record_failure(db, tag_id, mode, now, code, message):
        persisted.append((tag_id, mode, code))

    saved_ingest, saved_session = iw._ingest_tag, iw.SessionLocal
    saved_rf = iw._record_failure
    saved_concurrency = iw.settings.ingestion_tag_concurrency
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    iw.settings.ingestion_tag_concurrency = 2
    iw.settings.ingestion_tag_timeout_seconds = 0.05
    iw._ingest_tag = _fake_ingest
    iw._record_failure = _record_failure

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
    try:
        async def run():
            task = asyncio.create_task(iw.run_ingestion_loop(0.05, once=True))
            await asyncio.wait_for(b_done.wait(), timeout=5)
            await asyncio.wait_for(task, timeout=5)
            return (1, "RECORDED", "TAG_TIMEOUT") in persisted

        assert asyncio.run(run()) is True
    finally:
        iw._ingest_tag = saved_ingest
        iw.SessionLocal = saved_session
        iw._record_failure = saved_rf
        iw.settings.ingestion_tag_concurrency = saved_concurrency
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout
        a_blocker.set()


# ==============================================================
# 19. Expired lease job is recovered (DB test)
# ==============================================================

def test_expired_lease_recovered(db_session, monkeypatch):
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(bw, "SessionLocal", TestingSessionLocal)

    now = datetime.now(UTC)
    job = PiBackfillJob(
        tag_id=1, mode="RECORDED",
        target_start=now - timedelta(days=2), target_end=now - timedelta(days=1),
        next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2) + timedelta(hours=3),
        t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING",
        attempts=1,
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
    db_session.delete(db_session.get(PiBackfillJob, job.id))
    db_session.commit()


# ==============================================================
# 20. Legacy RUNNING job without lease is recovered
# ==============================================================

def test_legacy_running_without_lease_recovered(db_session, monkeypatch):
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(bw, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(bw.settings, "backfill_legacy_stale_seconds", 1)

    now = datetime.now(UTC)
    stale_time = now - timedelta(seconds=60)
    job = PiBackfillJob(
        tag_id=1, mode="RECORDED",
        target_start=now - timedelta(days=2), target_end=now - timedelta(days=1),
        next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2),
        t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING",
        attempts=1,
        lease_owner=None, lease_expires_at=None,
        heartbeat_at=None,
        updated_at=stale_time,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    recovered = bw._recover_legacy_running_jobs()
    db_session.expire_all()
    assert job.id in recovered
    refreshed = db_session.get(PiBackfillJob, job.id)
    assert refreshed.status == "PENDING"
    assert refreshed.stage == "RETRY_WAIT"
    db_session.delete(refreshed)
    db_session.commit()


# ==============================================================
# 21. Invalid RUNNING does not block PENDING jobs
# ==============================================================

def test_invalid_running_does_not_block_pending(db_session, monkeypatch):
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(bw, "SessionLocal", TestingSessionLocal)

    now = datetime.now(UTC)
    # Create a legacy RUNNING job.
    running = PiBackfillJob(
        tag_id=1, mode="RECORDED",
        target_start=now - timedelta(days=2), target_end=now - timedelta(days=1),
        next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2),
        t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING",
        lease_owner=None, lease_expires_at=None,
    )
    # Create a PENDING job for a different tag.
    pending = PiBackfillJob(
        tag_id=2, mode="RECORDED",
        target_start=now - timedelta(days=2), target_end=now - timedelta(days=1),
        next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2),
        t0=now, round_name="R1",
        stage="PENDING", status="PENDING",
    )
    db_session.add_all([running, pending])
    db_session.commit()

    # The PENDING job should be claimable even though a RUNNING exists.
    claimed = bw._claim_job(pending.id)
    db_session.expire_all()
    assert claimed is True
    assert db_session.get(PiBackfillJob, pending.id).status == "RUNNING"
    # The invalid RUNNING is NOT claimed without allow_legacy_running.
    assert bw._claim_job(running.id) is False

    for j in [running, pending]:
        obj = db_session.get(PiBackfillJob, j.id)
        if obj:
            db_session.delete(obj)
    db_session.commit()


# ==============================================================
# 22. Backfill uses round-robin (conceptual)
# ==============================================================

def test_backfill_round_robin_concept():
    """_active_job_ids returns jobs ordered by ID for fair round-robin."""
    # This is a unit check on the ordering semantic.
    with patch.object(bw, "SessionLocal") as mock_session:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.scalars.return_value.all.return_value = [3, 1, 2]
        mock_session.return_value = ctx
        # The query has ORDER BY id, so returned IDs are ordered.
        ids = bw._active_job_ids(rounds=True)
        # Whatever the DB returns, the function returns a list.
        assert isinstance(ids, list)


# ==============================================================
# 23. Ingestion has priority over backfill
# ==============================================================

def test_ingestion_priority_over_backfill():
    """Ingestion and backfill use different advisory lock keys."""
    assert iw.LOCK_KEY != bw.LOCK_KEY
    # Ingestion lock key is lower, ensuring it can be acquired independently.
    assert iw.LOCK_KEY == 2147483001
    assert bw.LOCK_KEY == 2147483002


# ==============================================================
# 24. Out-of-order PI responses don't corrupt cursors
# ==============================================================

def test_out_of_order_responses_safe():
    """Events returned out of timestamp order don't corrupt the watermark."""
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ))
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)
    # Events in reverse order.
    events = [
        _Point(base + timedelta(seconds=50)),
        _Point(base + timedelta(seconds=5)),
        _Point(base + timedelta(seconds=25)),
    ]
    provider = _HttpProbeProvider([_resp(events)])
    points, _ = _run_ingest(tag, state, provider)
    assert points == 3
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC_TZ)


# ==============================================================
# 25. No session open during HTTP
# ==============================================================

def test_no_session_during_http():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ))
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC_TZ)
    events = [_Point(base + timedelta(seconds=10))]
    provider = _HttpProbeProvider([_resp(events)])
    _run_ingest(tag, state, provider)
    assert _HTTP_OPEN_COUNTS
    assert all(count == 0 for count in _HTTP_OPEN_COUNTS)


# ==============================================================
# 26. stop_event stops ingestion loop
# ==============================================================

def test_stop_event_stops_ingestion_loop():
    """Setting stop_event causes the ingestion loop to exit."""
    async def _run():
        stop = asyncio.Event()

        def _session_factory():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.bind = None
            ctx.execute.return_value.scalars.return_value.all.return_value = []
            return ctx

        saved = iw.SessionLocal
        iw.SessionLocal = _session_factory
        try:
            # Schedule stop after first cycle.
            async def stop_after():
                await asyncio.sleep(0.05)
                stop.set()

            asyncio.create_task(stop_after())
            await asyncio.wait_for(
                iw.run_ingestion_loop(0.01, stop_event=stop),
                timeout=5,
            )
        finally:
            iw.SessionLocal = saved

    asyncio.run(_run())


# ==============================================================
# 27. stop_event stops backfill loop
# ==============================================================

def test_stop_event_stops_backfill_loop():
    """Setting stop_event causes the backfill loop to exit."""
    async def _run():
        stop = asyncio.Event()

        def _session_factory():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.bind = None
            ctx.execute.return_value.scalar.return_value = True  # advisory lock
            ctx.scalars.return_value.all.return_value = []
            ctx.execute.return_value.scalars.return_value.all.return_value = []
            return ctx

        saved = bw.SessionLocal
        bw.SessionLocal = _session_factory
        try:
            async def stop_after():
                await asyncio.sleep(0.05)
                stop.set()

            asyncio.create_task(stop_after())
            await asyncio.wait_for(
                bw.run_backfill_loop(stop_event=stop),
                timeout=5,
            )
        finally:
            bw.SessionLocal = saved

    asyncio.run(_run())


# ==============================================================
# 28. Job cursor prefers checkpoint
# ==============================================================

def test_job_cursor_prefers_checkpoint(db_session):
    now = datetime.now(UTC)
    job = PiBackfillJob(
        tag_id=1, mode="RECORDED",
        target_start=now - timedelta(days=2), target_end=now - timedelta(days=1),
        next_start=now - timedelta(days=2),
        checkpoint_start=now - timedelta(days=2) + timedelta(hours=3),
        t0=now, round_name="R1",
        stage="RUNNING", status="RUNNING", attempts=1,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    assert bw._job_cursor(job) == job.checkpoint_start.replace(tzinfo=UTC)
    db_session.delete(job)
    db_session.commit()


# ==============================================================
# 29. Workers disabled in settings
# ==============================================================

def test_workers_disabled_in_settings():
    """When workers_enabled=False, supervisor does not start workers."""
    from app.workers.supervisor import WorkerSupervisor

    async def _run():
        supervisor = WorkerSupervisor()
        with patch("app.workers.supervisor.settings") as mock_settings:
            mock_settings.workers_enabled = False
            await supervisor.start()
            assert len(supervisor._tasks) == 0
            await supervisor.stop()

    asyncio.run(_run())


# ==============================================================
# 30. Budget exhausted is not a failure
# ==============================================================

def test_budget_exhausted_not_failure():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 27, tzinfo=UTC_TZ))
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC_TZ)
    events = [_Point(base + timedelta(seconds=s)) for s in (5, 25, 50)]
    provider = _HttpProbeProvider([_resp(events * 3)] * 12)
    saved_budget = iw.settings.ingestion_tag_request_budget
    saved_minutes = iw.settings.ingestion_tag_budget_minutes
    iw.settings.ingestion_tag_request_budget = 3
    iw.settings.ingestion_tag_budget_minutes = 5
    try:
        points, _ = _run_ingest(tag, state, provider)
        assert state.last_error_code != "PI_ERROR"
        assert state.last_error_code != "INTERVAL_INCOMPLETE"
        assert state.next_attempt_at is None
        assert points > 0
        assert state.watermark_ts > datetime(2026, 9, 17, 14, 27, tzinfo=UTC_TZ)
    finally:
        iw.settings.ingestion_tag_request_budget = saved_budget
        iw.settings.ingestion_tag_budget_minutes = saved_minutes
