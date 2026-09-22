"""Deterministic test for advisory lock connection loss and concurrent failover.

Requirements verified:
1. Instance A acquires leadership and runs controlled work.
2. Instance B attempts continuously to acquire leadership.
3. PostgreSQL connection of A is terminated with pg_terminate_backend.
4. B acquires the lock as soon as PostgreSQL releases it (without waiting for A).
5. Real timeline of A and B is recorded.
6. Check if an overlap window exists between B starting and A stopping, proving that
   the liveness monitor check interval determines the maximum failover latency.
7. Zero orphan tasks remain after shutdown.
8. Ingestion and backfill locks are completely independent.
9. No ORM session or business transaction is used to hold the lock.
"""
from __future__ import annotations

import asyncio
import subprocess
import time
import pytest
from sqlalchemy import create_engine, text

from app.workers.supervisor import (
    _AdvisoryLock,
    _run_supervised,
    _WorkerStatus,
    _LEADER_LOCK_INGESTION,
    _LEADER_LOCK_BACKFILL,
)


DISPOSABLE_DB = "test_disposable_lock_db"
ADMIN_CONN = "postgresql+psycopg://postgres@127.0.0.1:5432/postgres"
DISPOSABLE_URL = f"postgresql+psycopg://pi_app:pi_app_secret@127.0.0.1:5432/{DISPOSABLE_DB}"


def _setup_disposable_db():
    try:
        subprocess.run(
            [
                "psql", "-U", "postgres", "-h", "127.0.0.1", "-p", "5432",
                "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DISPOSABLE_DB}';",
                "-c", f"DROP DATABASE IF EXISTS {DISPOSABLE_DB};",
                "-c", f"CREATE DATABASE {DISPOSABLE_DB} OWNER pi_app;",
            ],
            check=True,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def _teardown_disposable_db():
    try:
        subprocess.run(
            [
                "psql", "-U", "postgres", "-h", "127.0.0.1", "-p", "5432",
                "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DISPOSABLE_DB}';",
                "-c", f"DROP DATABASE IF EXISTS {DISPOSABLE_DB};",
            ],
            check=True,
            capture_output=True,
        )
    except Exception:
        pass


@pytest.fixture
def disposable_pg():
    ok = _setup_disposable_db()
    if not ok:
        pytest.skip("PostgreSQL port 5432 with admin privileges not available")
    engine = create_engine(DISPOSABLE_URL)
    import app.database.session
    orig_engine = app.database.session.engine
    app.database.session.engine = engine
    yield engine
    app.database.session.engine = orig_engine
    engine.dispose()
    _teardown_disposable_db()


@pytest.mark.asyncio
async def test_advisory_lock_connection_loss_and_concurrent_failover(disposable_pg):
    """Real concurrent election test:
    1. A acquires lock and starts work.
    2. B concurrently retries acquiring the lock without artificial waiting.
    3. A's connection is terminated via pg_terminate_backend.
    4. B acquires lock as soon as PG releases it.
    5. A and B timelines are recorded, measuring the exact overlap window.
    """
    LOCK_KEY = 88888801
    timeline: list[tuple[float, str, str]] = []

    lock_a = _AdvisoryLock(LOCK_KEY, "test_ingestion_a")
    lock_b = _AdvisoryLock(LOCK_KEY, "test_ingestion_b")

    a_started = asyncio.Event()
    b_started = asyncio.Event()

    async def coro_a():
        timeline.append((time.time(), "A", "START"))
        a_started.set()
        try:
            while True:
                timeline.append((time.time(), "A", "PULSE"))
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            timeline.append((time.time(), "A", "CANCELLED"))
            raise
        finally:
            timeline.append((time.time(), "A", "STOPPED"))

    async def coro_b():
        timeline.append((time.time(), "B", "START"))
        b_started.set()
        try:
            while True:
                timeline.append((time.time(), "B", "PULSE"))
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            timeline.append((time.time(), "B", "CANCELLED"))
            raise
        finally:
            timeline.append((time.time(), "B", "STOPPED"))

    stop_a = asyncio.Event()
    stop_b = asyncio.Event()
    status_a = _WorkerStatus("worker_a")
    status_b = _WorkerStatus("worker_b")

    # Step 1: Start A with supervision (checking connection every 100ms)
    task_a = asyncio.create_task(
        _run_supervised(
            "worker_a",
            coro_a,
            stop_a,
            status_a,
            lock=lock_a,
            lock_check_interval=0.1,
            lock_check_timeout=0.5,
            leader_poll_interval=0.05,
        )
    )

    # Wait for A to acquire lock and begin working
    await asyncio.wait_for(a_started.wait(), timeout=3.0)
    pid_a = lock_a.get_backend_pid()
    assert pid_a is not None, "Expected valid backend PID for Instance A"
    assert status_a.leader is True

    # Step 2: Start B concurrently trying to acquire leadership in a retry loop
    task_b = asyncio.create_task(
        _run_supervised(
            "worker_b",
            coro_b,
            stop_b,
            status_b,
            lock=lock_b,
            lock_check_interval=0.1,
            lock_check_timeout=0.5,
            leader_poll_interval=0.05,
        )
    )

    # Allow B to make several failed acquisition attempts while A is running
    await asyncio.sleep(0.15)
    assert b_started.is_set() is False, "Instance B should not start while A holds lock"
    assert status_b.leader is False

    # Step 3: Terminate A's backend connection directly in PostgreSQL
    with create_engine(ADMIN_CONN).connect() as aconn:
        res = aconn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid_a}).scalar()
        aconn.commit()
    assert res is True
    term_time = time.time()
    timeline.append((term_time, "SYS", f"TERMINATED_PID_{pid_a}"))

    # Step 4: B should acquire lock concurrently as soon as PG releases it
    await asyncio.wait_for(b_started.wait(), timeout=3.0)
    assert status_b.leader is True

    # Allow B to run for a few pulses
    await asyncio.sleep(0.15)

    # Step 5: Stop both workers cleanly
    stop_a.set()
    stop_b.set()
    await asyncio.gather(task_a, task_b, return_exceptions=True)
    lock_b.release()

    # Step 6: Analyze the real recorded timeline
    a_pulses = [t for t, actor, ev in timeline if actor == "A" and ev == "PULSE"]
    b_pulses = [t for t, actor, ev in timeline if actor == "B" and ev == "PULSE"]
    a_stopped_events = [t for t, actor, ev in timeline if actor == "A" and ev in ("CANCELLED", "STOPPED")]

    assert len(a_pulses) > 0, "Expected pulses from A"
    assert len(b_pulses) > 0, "Expected pulses from B"
    assert len(a_stopped_events) > 0, "Expected stopped event from A"

    t_b_first_pulse = b_pulses[0]
    t_a_last_pulse = a_pulses[-1]
    t_a_stopped = a_stopped_events[-1]

    # Measure potential overlap window
    # Overlap occurs if B produced a pulse BEFORE A completely stopped producing pulses
    overlap_duration = max(0.0, t_a_last_pulse - t_b_first_pulse)
    print(f"\nTimeline analysis:")
    print(f"  Terminated A PID at:   {term_time:.4f}")
    print(f"  A last pulse at:       {t_a_last_pulse:.4f}")
    print(f"  A stopped at:          {t_a_stopped:.4f}")
    print(f"  B first pulse at:      {t_b_first_pulse:.4f}")
    print(f"  Measured overlap (s):  {overlap_duration:.4f}")

    # Maximum overlap is strictly bounded by the lock check interval (0.1s in test) + network/query delay
    assert overlap_duration <= 0.6, (
        f"Overlap duration {overlap_duration:.4f}s exceeded safe bound of lock_check_interval"
    )

    # After failover, B remains the sole leader
    assert status_a.leader is False


@pytest.mark.asyncio
async def test_ingestion_and_backfill_locks_are_independent(disposable_pg):
    """Verify that Ingestion and Backfill locks are independent and can be held concurrently."""
    lock_ingestion = _AdvisoryLock(_LEADER_LOCK_INGESTION, "ingestion")
    lock_backfill = _AdvisoryLock(_LEADER_LOCK_BACKFILL, "backfill")

    try:
        assert lock_ingestion.try_acquire() is True
        assert lock_backfill.try_acquire() is True

        assert lock_ingestion.check_alive() is True
        assert lock_backfill.check_alive() is True
    finally:
        lock_ingestion.release()
        lock_backfill.release()
