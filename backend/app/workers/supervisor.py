"""Supervisor for PI ingestion and backfill workers integrated into the
FastAPI lifespan.

Features:
  * Leader election via PostgreSQL advisory locks on dedicated connections.
  * Automatic restart with bounded exponential backoff.
  * Independent failure domains: ingestion crash ≠ backfill crash ≠ API crash.
  * Graceful shutdown with stop signal propagation.
  * Configurable enable/disable via settings for tests and maintenance.
  * Duplicate prevention when an external ``run_workers.py`` is also running.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger("workers.supervisor")

OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"

# Advisory lock keys – must not collide with per-function locks in the workers.
_LEADER_LOCK_INGESTION = 2147483601
_LEADER_LOCK_BACKFILL = 2147483602


class _WorkerStatus:
    """Observable status for one supervised worker."""

    __slots__ = (
        "name", "alive", "leader", "leader_id",
        "last_cycle_started", "last_cycle_completed",
        "last_success", "last_error", "restarts",
        "consecutive_failures", "events_written",
        "delay_minutes", "tags_processed", "tags_in_backoff",
        "timeouts", "pages", "splits",
    )

    def __init__(self, name: str) -> None:
        self.name = name
        self.alive = False
        self.leader = False
        self.leader_id: str | None = None
        self.last_cycle_started: datetime | None = None
        self.last_cycle_completed: datetime | None = None
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self.restarts = 0
        self.consecutive_failures = 0
        self.events_written = 0
        self.delay_minutes: float | None = None
        self.tags_processed = 0
        self.tags_in_backoff = 0
        self.timeouts = 0
        self.pages = 0
        self.splits = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alive": self.alive,
            "leader": self.leader,
            "leader_id": self.leader_id,
            "last_cycle_started": self.last_cycle_started.isoformat() if self.last_cycle_started else None,
            "last_cycle_completed": self.last_cycle_completed.isoformat() if self.last_cycle_completed else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
            "restarts": self.restarts,
            "consecutive_failures": self.consecutive_failures,
            "events_written": self.events_written,
            "delay_minutes": self.delay_minutes,
            "tags_processed": self.tags_processed,
            "tags_in_backoff": self.tags_in_backoff,
            "timeouts": self.timeouts,
            "pages": self.pages,
            "splits": self.splits,
        }


# Module-level observable state for health endpoints.
ingestion_status = _WorkerStatus("ingestion")
backfill_status = _WorkerStatus("backfill")


class _AdvisoryLock:
    """Holds a PostgreSQL session-level advisory lock on a dedicated raw
    connection that stays open for the lifetime of leadership.

    On SQLite (tests) this is always considered acquired.
    """

    def __init__(self, lock_key: int, name: str) -> None:
        self._lock_key = lock_key
        self._name = name
        self._conn: Any = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def try_acquire(self) -> bool:
        """Try to acquire the advisory lock.  Non-blocking."""
        if self._acquired:
            if self._conn is None or self.check_alive():
                return True
            self.release()

        try:
            from app.database.session import engine

            if engine.dialect.name != "postgresql":
                self._acquired = True
                return True

            # Use a raw DBAPI connection outside the ORM pool so this lock
            # does not interfere with ORM transactions and remains held for
            # the lifetime of the connection.
            raw = engine.raw_connection()
            try:
                cursor = raw.cursor()
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (self._lock_key,))
                result = cursor.fetchone()
                if result and result[0]:
                    self._conn = raw
                    self._acquired = True
                    # Important: commit so the lock is session-level, not
                    # transaction-level.
                    raw.commit()
                    logger.info(
                        "leader_acquired lock=%s name=%s owner=%s",
                        self._lock_key, self._name, OWNER_ID,
                    )
                    return True
                else:
                    raw.close()
                    return False
            except Exception:
                raw.close()
                raise
        except Exception:
            logger.debug("advisory_lock_acquire_failed key=%d", self._lock_key, exc_info=True)
            return False

    def check_alive(self) -> bool:
        """Verify that the dedicated connection holding the lock is still valid and holds the lock."""
        if not self._acquired:
            return False
        if self._conn is None:
            return True  # Non-PostgreSQL (e.g. SQLite tests)
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s AND pid = pg_backend_pid() AND granted = true",
                (self._lock_key,),
            )
            row = cursor.fetchone()
            if not row or row[0] < 1:
                logger.warning("advisory_lock_not_held lock=%s name=%s", self._lock_key, self._name)
                return False
            return True
        except Exception:
            logger.warning("advisory_lock_connection_lost lock=%s name=%s", self._lock_key, self._name)
            return False

    def get_backend_pid(self) -> int | None:
        """Get the backend PID of the lock connection, if PostgreSQL."""
        if self._conn is None:
            return None
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT pg_backend_pid()")
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def release(self) -> None:
        """Release the advisory lock and close the dedicated connection."""
        if not self._acquired:
            return
        conn = self._conn
        self._conn = None
        self._acquired = False
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT pg_advisory_unlock(%s)", (self._lock_key,))
                conn.commit()
            except Exception:
                logger.debug("advisory_lock_release_failed key=%d", self._lock_key, exc_info=True)
                if hasattr(conn, "invalidate"):
                    try:
                        conn.invalidate()
                    except Exception:
                        pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        logger.info(
            "leader_released lock=%s name=%s owner=%s",
            self._lock_key, self._name, OWNER_ID,
        )


async def _acquire_leader(
    lock: _AdvisoryLock,
    stop_event: asyncio.Event,
    *,
    poll_interval: float = 5.0,
) -> bool:
    """Block until the advisory lock is acquired or stop is signaled."""
    while not stop_event.is_set():
        acquired = await asyncio.get_event_loop().run_in_executor(
            None, lock.try_acquire,
        )
        if acquired:
            return True
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            return False  # stop signaled
        except asyncio.TimeoutError:
            pass
    return False


async def _run_supervised(
    name: str,
    coro_factory: Callable[[], Coroutine],
    stop_event: asyncio.Event,
    status: _WorkerStatus,
    *,
    max_backoff: float = 60.0,
    initial_backoff: float = 1.0,
    lock: _AdvisoryLock | None = None,
    lock_check_interval: float = 1.0,
    lock_check_timeout: float = 2.0,
    leader_poll_interval: float = 5.0,
) -> None:
    """Run *coro_factory()* under supervised leadership.

    If *lock* is provided:
      1. Acquires leadership via advisory lock before starting the worker.
      2. Continuously verifies connection liveness with bounded timeout.
      3. If connection dies, drops or loses session, leadership is immediately
         marked lost, the worker task is cancelled and awaited, and local
         resources released before a new election can occur.
    """
    backoff = initial_backoff
    status.alive = True
    status.leader_id = OWNER_ID

    try:
        while not stop_event.is_set():
            if lock is not None:
                status.leader = False
                acquired = await _acquire_leader(lock, stop_event, poll_interval=leader_poll_interval)
                if not acquired or stop_event.is_set():
                    break
                status.leader = True
                logger.info(
                    "supervisor_started worker=%s owner=%s (leader)",
                    name, OWNER_ID,
                )
            else:
                status.leader = True
                logger.info("supervisor_started worker=%s owner=%s", name, OWNER_ID)

            leadership_lost = asyncio.Event()

            async def _monitor_lock() -> None:
                try:
                    while not stop_event.is_set() and not leadership_lost.is_set():
                        await asyncio.sleep(lock_check_interval)
                        if stop_event.is_set() or leadership_lost.is_set():
                            break
                        try:
                            alive = await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(None, lock.check_alive),
                                timeout=lock_check_timeout,
                            )
                        except Exception:
                            alive = False
                        if not alive:
                            logger.error(
                                "leadership_lost worker=%s lock=%s owner=%s",
                                name, lock._lock_key, OWNER_ID,
                            )
                            leadership_lost.set()
                            break
                except asyncio.CancelledError:
                    pass

            monitor_task = None
            if lock is not None and lock._conn is not None:
                monitor_task = asyncio.create_task(_monitor_lock())

            try:
                while not stop_event.is_set() and not leadership_lost.is_set():
                    status.last_cycle_started = datetime.now(timezone.utc)
                    task = asyncio.create_task(coro_factory())

                    stop_wait = asyncio.create_task(stop_event.wait())
                    lost_wait = asyncio.create_task(leadership_lost.wait())

                    finished, pending = await asyncio.wait(
                        [task, stop_wait, lost_wait],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for p in [stop_wait, lost_wait]:
                        if p in pending:
                            p.cancel()
                            with suppress(asyncio.CancelledError):
                                await p

                    if leadership_lost.is_set():
                        status.leader = False
                        if not task.done():
                            task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        logger.warning("worker_cancelled_due_to_lost_leadership worker=%s", name)
                        break  # Exit inner execution loop to release lock and backoff

                    if stop_event.is_set():
                        if not task.done():
                            task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        break

                    # Task finished (clean or crash)
                    try:
                        task.result()
                        backoff = initial_backoff
                        status.consecutive_failures = 0
                        status.last_success = datetime.now(timezone.utc)
                        status.last_cycle_completed = datetime.now(timezone.utc)
                        logger.info("supervisor_worker_exited worker=%s (clean)", name)
                    except asyncio.CancelledError:
                        break
                    except Exception as exc:
                        status.consecutive_failures += 1
                        status.last_error = str(exc)[:500]
                        status.restarts += 1
                        logger.exception(
                            "supervisor_worker_crashed worker=%s restarts=%d backoff=%.1fs",
                            name, status.restarts, backoff,
                        )
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                            break
                        except asyncio.TimeoutError:
                            pass
                        backoff = min(backoff * 2, max_backoff)
            finally:
                if monitor_task is not None:
                    monitor_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await monitor_task
                if lock is not None:
                    try:
                        await asyncio.get_event_loop().run_in_executor(None, lock.release)
                    except Exception:
                        logger.debug("leader_release_failed worker=%s", name, exc_info=True)
                status.leader = False

            if stop_event.is_set():
                break

            # Brief pause before attempting election again after lost leadership
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                pass
    finally:
        status.alive = False
        status.leader = False
        logger.info("supervisor_stopped worker=%s", name)


class WorkerSupervisor:
    """Manages the lifecycle of ingestion and backfill workers."""

    def __init__(self) -> None:
        self._stop: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self._locks: list[_AdvisoryLock] = []

    async def start(self) -> None:
        """Start supervised workers based on settings."""
        if not getattr(settings, "workers_enabled", True):
            logger.info("supervisor_workers_disabled (settings.workers_enabled=False)")
            return

        from app.workers.ingestion_worker import run_ingestion_loop
        from app.workers.backfill_worker import run_backfill_loop

        self._stop = asyncio.Event()

        if getattr(settings, "worker_ingestion_enabled", True):
            lock = _AdvisoryLock(_LEADER_LOCK_INGESTION, "ingestion")
            self._locks.append(lock)
            t = asyncio.create_task(
                _run_supervised(
                    "ingestion",
                    lambda: run_ingestion_loop(
                        settings.ingestion_cycle_seconds,
                        stop_event=self._stop,
                    ),
                    self._stop,
                    ingestion_status,
                    lock=lock,
                ),
            )
            self._tasks.append(t)
            logger.info("supervisor_ingestion_scheduled")

        if getattr(settings, "worker_backfill_enabled", True):
            lock = _AdvisoryLock(_LEADER_LOCK_BACKFILL, "backfill")
            self._locks.append(lock)
            t = asyncio.create_task(
                _run_supervised(
                    "backfill",
                    lambda: run_backfill_loop(
                        stop_event=self._stop,
                        admin_only=not getattr(settings, "backfill_auto_rounds_enabled", False),
                    ),
                    self._stop,
                    backfill_status,
                    lock=lock,
                ),
            )
            self._tasks.append(t)
            logger.info("supervisor_backfill_scheduled")

    async def stop(self) -> None:
        """Signal all workers to stop and await their completion."""
        if self._stop is not None:
            self._stop.set()
        if self._tasks:
            logger.info("supervisor_stopping workers=%d", len(self._tasks))
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        # Release any locks still held (defensive).
        for lock in self._locks:
            try:
                lock.release()
            except Exception:
                pass
        self._locks.clear()
        ingestion_status.alive = False
        ingestion_status.leader = False
        backfill_status.alive = False
        backfill_status.leader = False
        logger.info("supervisor_all_stopped")


# Module-level singleton.
_supervisor: WorkerSupervisor | None = None


def get_supervisor() -> WorkerSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = WorkerSupervisor()
    return _supervisor
