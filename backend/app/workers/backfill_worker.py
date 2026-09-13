"""Durable, restart-safe round-robin backfill worker."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.database.session import SessionLocal
from app.integrations.pi.errors import PiIntegrationError
from app.models.pi_tag import PiTag
from app.models.postgres import PiBackfillJob, PiSample
from app.schemas.pi import TimeSeriesRequest
from app.services.coverage_service import CoverageService
from app.services.pi_service import PiService

logger = logging.getLogger("workers.backfill")
BACKFILL_ROUNDS = (("R1", 7, 0), ("R2", 30, 7), ("R3", 90, 30), ("R4", 365, 90))
ROUND_NAMES = tuple(item[0] for item in BACKFILL_ROUNDS)
TRANSIENT_PI_CODES = frozenset({"PI_RATE_LIMITED", "PI_UNAVAILABLE", "PI_TIMEOUT"})
LOCK_KEY = 2147483002
LEASE_OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _job_cursor(job: PiBackfillJob) -> datetime:
    return _as_utc(job.checkpoint_start or job.next_start or job.target_start)


def _record(tag_id: int, point: Any, mode: str = "RECORDED") -> dict[str, Any]:
    value_type = "boolean" if isinstance(point.value, bool) else "double" if isinstance(point.value, (int, float)) else "string"
    return {
        "tag_id": tag_id,
        "ts": point.timestamp.astimezone(timezone.utc),
        "value_type": value_type,
        "value_double": float(point.value) if value_type == "double" else None,
        "value_boolean": bool(point.value) if value_type == "boolean" else None,
        "value_text": str(point.value) if value_type == "string" and point.value is not None else None,
        "good": point.good,
        "questionable": point.questionable,
        "substituted": point.substituted,
        "source_mode": mode,
    }


def _retry_delay(attempts: int, retry_after: Any = None) -> float:
    try:
        external_delay = float(retry_after)
    except (TypeError, ValueError):
        external_delay = 0.0
    exponential = min(
        settings.backfill_retry_base_seconds * (2 ** max(0, attempts - 1)),
        settings.backfill_retry_max_seconds,
    )
    return min(
        settings.backfill_retry_max_seconds,
        max(exponential, external_delay) + random.uniform(0, min(1.0, exponential * 0.1)),
    )


def _recover_expired_leases() -> list[int]:
    """Recover leased jobs only; legacy RUNNING rows require explicit review."""
    now = _now()
    with SessionLocal() as db:
        ids = list(db.scalars(select(PiBackfillJob.id).where(
            PiBackfillJob.status == "RUNNING",
            PiBackfillJob.lease_expires_at.is_not(None),
            PiBackfillJob.lease_expires_at < now,
        )).all())
        if not ids:
            return []
        db.execute(update(PiBackfillJob).where(PiBackfillJob.id.in_(ids)).values(
            status="PENDING",
            stage="RETRY_WAIT",
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            next_attempt_at=now,
            error_message="Lease expirado; job liberado para retomada.",
            updated_at=now,
        ))
        db.commit()
    logger.warning("backfill_expired_leases_recovered job_ids=%s", ids)
    return ids


def _claim_job(job_id: int, *, allow_legacy_running: bool = False) -> bool:
    now = _now()
    eligible = and_(
        PiBackfillJob.status == "PENDING",
        or_(PiBackfillJob.next_attempt_at.is_(None), PiBackfillJob.next_attempt_at <= now),
    )
    if allow_legacy_running:
        eligible = or_(eligible, and_(
            PiBackfillJob.status == "RUNNING",
            PiBackfillJob.lease_expires_at.is_(None),
        ))
    with SessionLocal() as db:
        result = db.execute(update(PiBackfillJob).where(
            PiBackfillJob.id == job_id, eligible,
        ).values(
            status="RUNNING",
            stage="RUNNING",
            attempts=PiBackfillJob.attempts + 1,
            lease_owner=LEASE_OWNER,
            lease_expires_at=now + timedelta(seconds=settings.backfill_lease_seconds),
            heartbeat_at=now,
            next_attempt_at=None,
            updated_at=now,
        ))
        db.commit()
        return bool(result.rowcount)


async def _heartbeat_job(job_id: int, stop: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.backfill_heartbeat_seconds)
            return
        except asyncio.TimeoutError:
            now = _now()
            try:
                with SessionLocal() as db:
                    result = db.execute(update(PiBackfillJob).where(
                        PiBackfillJob.id == job_id,
                        PiBackfillJob.status == "RUNNING",
                        PiBackfillJob.lease_owner == LEASE_OWNER,
                    ).values(
                        heartbeat_at=now,
                        lease_expires_at=now + timedelta(seconds=settings.backfill_lease_seconds),
                        updated_at=now,
                    ))
                    db.commit()
                    if not result.rowcount:
                        return
            except Exception:
                logger.exception("backfill_heartbeat_failed job_id=%s", job_id)


def _defer_job(job_id: int, code: str, message: str, retry_after: Any = None) -> None:
    now = _now()
    with SessionLocal() as db:
        job = db.get(PiBackfillJob, job_id)
        if job is None or job.lease_owner != LEASE_OWNER:
            return
        delay = _retry_delay(job.attempts or 1, retry_after)
        job.status = "PENDING"
        job.stage = "RETRY_WAIT"
        job.next_attempt_at = now + timedelta(seconds=delay)
        job.last_error_at = now
        job.error_message = f"{code}: {message}"[:2000]
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        db.commit()
    logger.warning("backfill_transient_deferred job_id=%s code=%s delay_seconds=%.2f", job_id, code, delay)


def _fail_job(job_id: int, message: str) -> None:
    with SessionLocal() as db:
        job = db.get(PiBackfillJob, job_id)
        if job is None or job.lease_owner != LEASE_OWNER:
            return
        job.stage = "FAILED"
        job.status = "FAILED"
        job.error_message = message[:2000]
        job.last_error_at = _now()
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        db.commit()


def _release_for_split(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(PiBackfillJob, job_id)
        if job is None or job.lease_owner != LEASE_OWNER:
            return
        job.status = "PENDING"
        job.stage = "PENDING"
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.next_attempt_at = None
        db.commit()


async def backfill_tag_interval(
    tag_id: int,
    start: datetime,
    end: datetime,
    t0: datetime,
    round_name: str,
    semaphore: asyncio.Semaphore,
    *,
    mode: str = "RECORDED",
    interval_seconds: int | None = None,
    job_id: int | None = None,
    max_count: int | None = None,
    allow_legacy_running: bool = False,
    _split_depth: int = 0,
) -> bool:
    if job_id is None:
        with SessionLocal() as db:
            job = db.scalar(select(PiBackfillJob).where(
                PiBackfillJob.tag_id == tag_id,
                PiBackfillJob.round_name == round_name,
                PiBackfillJob.t0 == t0,
                PiBackfillJob.target_start == start,
                PiBackfillJob.target_end == end,
            ))
            if job is None:
                job = PiBackfillJob(
                    tag_id=tag_id, mode=mode, interval_seconds=interval_seconds,
                    target_start=start, target_end=end, next_start=start,
                    checkpoint_start=start, t0=t0, round_name=round_name,
                    stage="PENDING", status="PENDING",
                )
                db.add(job)
                db.commit()
                db.refresh(job)
            job_id = job.id

    if not _claim_job(job_id, allow_legacy_running=allow_legacy_running):
        return False

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat_job(job_id, stop_heartbeat))
    split_window: tuple[datetime, datetime] | None = None
    minimum_window = timedelta(minutes=15)
    try:
        async with semaphore:
            with SessionLocal() as db:
                tag = db.get(PiTag, tag_id)
                if tag is None or not tag.active:
                    _fail_job(job_id, "Tag inexistente ou inativa.")
                    return False
                request_mode = "interpolated" if mode.startswith("INTERPOLATED_") else "recorded"
                request_interval = f"{interval_seconds}s" if request_mode == "interpolated" else None
                result = await PiService(db).fetch_time_series(TimeSeriesRequest(
                    tag_ids=[tag_id], start_time=start, end_time=end,
                    mode=request_mode, interval=request_interval, max_count=max_count,
                ))
                error = next(iter(result.errors), None)
                if error:
                    code = str(error.get("code") or "PI_ERROR")
                    if code == "PI_TIMEOUT" and end - start > minimum_window:
                        split_window = (start, start + (end - start) / 2)
                    elif code in TRANSIENT_PI_CODES:
                        _defer_job(job_id, code, str(error.get("message") or "Falha transitoria no PI."), error.get("retry_after"))
                        return False
                    else:
                        _fail_job(job_id, f"{code}: {error.get('message') or 'resposta incompleta do PI'}")
                        return False

                points = [
                    point for point in (result.series[0].points if result.series else [])
                    if start <= point.timestamp.astimezone(timezone.utc) < end
                ]
                if max_count is not None and len(points) >= max_count:
                    if end - start > minimum_window:
                        split_window = (start, start + (end - start) / 2)
                    else:
                        _fail_job(job_id, "Resposta PI atingiu maxCount na janela minima.")
                        return False

                if split_window is None:
                    points = list({point.timestamp.astimezone(timezone.utc): point for point in points}.values())
                    if points:
                        insert_factory = pg_insert if db.bind is not None and db.bind.dialect.name == "postgresql" else sqlite_insert
                        records = [_record(tag_id, point, mode) for point in points]
                        for offset in range(0, len(records), 500):
                            stmt = insert_factory(PiSample).values(records[offset:offset + 500])
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["tag_id", "ts", "source_mode"],
                                set_={column: getattr(stmt.excluded, column) for column in (
                                    "value_type", "value_double", "value_boolean", "value_text",
                                    "good", "questionable", "substituted", "source_mode",
                                )},
                            )
                            db.execute(stmt)
                    CoverageService.record_coverage(db, tag_id, start, end, mode, interval_seconds, pi_web_id=tag.pi_web_id)
                    job = db.get(PiBackfillJob, job_id)
                    if job is None or job.lease_owner != LEASE_OWNER or job.status == "CANCELLED":
                        db.rollback()
                        return False
                    job.next_start = end
                    job.checkpoint_start = end
                    is_final = end >= job.target_end
                    job.stage = "READY"
                    job.status = "COMPLETED" if is_final else "PENDING"
                    job.error_message = None
                    job.last_error_at = None
                    job.next_attempt_at = None
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.heartbeat_at = None
                    db.commit()
                    logger.info(
                        "backfill_window_completed job_id=%s tag_id=%s round=%s start=%s end=%s points=%d final=%s",
                        job_id, tag_id, round_name, start, end, len(points), is_final,
                    )
                    return True
    except PiIntegrationError as exc:
        if exc.code == "PI_TIMEOUT" and end - start > minimum_window:
            split_window = (start, start + (end - start) / 2)
        elif exc.code in TRANSIENT_PI_CODES:
            retry_after = exc.details.get("retry_after") if isinstance(exc.details, dict) else None
            _defer_job(job_id, exc.code, exc.safe_message, retry_after)
            return False
        else:
            _fail_job(job_id, f"{exc.code}: {exc.safe_message}")
            logger.exception("backfill_window_failed job_id=%s", job_id)
            return False
    except Exception as exc:
        _fail_job(job_id, str(exc))
        logger.exception("backfill_window_failed job_id=%s", job_id)
        return False
    finally:
        stop_heartbeat.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task

    if split_window is None:
        return False
    _release_for_split(job_id)
    split_start, midpoint = split_window
    logger.info("backfill_window_split job_id=%s tag_id=%s start=%s end=%s depth=%s", job_id, tag_id, start, end, _split_depth)
    left = await backfill_tag_interval(
        tag_id, split_start, midpoint, t0, round_name, semaphore,
        mode=mode, interval_seconds=interval_seconds, job_id=job_id,
        max_count=max_count, _split_depth=_split_depth + 1,
    )
    if not left:
        return False
    return await backfill_tag_interval(
        tag_id, midpoint, end, t0, round_name, semaphore,
        mode=mode, interval_seconds=interval_seconds, job_id=job_id,
        max_count=max_count, _split_depth=_split_depth + 1,
    )


def _window_for_job(job: PiBackfillJob) -> timedelta:
    if job.mode == "INTERPOLATED_300S":
        return timedelta(days=30)
    return timedelta(hours=settings.backfill_recorded_window_hours)


def _active_job_ids(*, rounds: bool) -> list[int]:
    with SessionLocal() as db:
        round_filter = PiBackfillJob.round_name.in_(ROUND_NAMES) if rounds else PiBackfillJob.round_name.is_(None)
        return list(db.scalars(select(PiBackfillJob.id).where(
            round_filter,
            PiBackfillJob.status.in_(("PENDING", "RUNNING")),
        ).order_by(PiBackfillJob.id)).all())


async def _resume_job_by_id(job_id: int, semaphore: asyncio.Semaphore, *, explicit: bool = False) -> bool:
    with SessionLocal() as db:
        job = db.get(PiBackfillJob, job_id)
        if job is None:
            logger.warning("backfill_resume_missing job_id=%s", job_id)
            return False
        if job.status in ("COMPLETED", "FAILED", "CANCELLED"):
            return True
        if job.next_attempt_at is not None and _as_utc(job.next_attempt_at) > _now():
            return False
        cursor = _job_cursor(job)
        target_end = _as_utc(job.target_end)
        if cursor >= target_end:
            job.status = "COMPLETED"
            job.stage = "READY"
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            db.commit()
            return True
        end = min(cursor + _window_for_job(job), target_end)
        snapshot = (
            job.tag_id,
            _as_utc(job.t0 or job.created_at) if (job.t0 or job.created_at) else _now(),
            job.round_name or "ADMIN",
            job.mode or "RECORDED",
            job.interval_seconds,
        )
    tag_id, t0, round_name, mode, interval_seconds = snapshot
    return await backfill_tag_interval(
        tag_id, cursor, end, t0, round_name, semaphore,
        mode=mode, interval_seconds=interval_seconds, job_id=job_id,
        max_count=settings.backfill_recorded_max_points if mode in ("RECORDED", "INTERPOLATED_10S") else None,
        allow_legacy_running=explicit,
    )


async def _resume_jobs(job_ids: Iterable[int], *, explicit: bool = False) -> bool:
    ids = list(dict.fromkeys(job_ids))
    if not ids:
        return False
    semaphore = asyncio.Semaphore(max(1, settings.pi_query_concurrency))
    concurrency = max(1, min(settings.backfill_admin_concurrency, settings.pi_query_concurrency))
    processed = False
    while True:
        with SessionLocal() as db:
            active_ids = list(db.scalars(select(PiBackfillJob.id).where(
                PiBackfillJob.id.in_(ids),
                PiBackfillJob.status.in_(("PENDING", "RUNNING")),
                or_(PiBackfillJob.next_attempt_at.is_(None), PiBackfillJob.next_attempt_at <= _now()),
            ).order_by(PiBackfillJob.id)).all())
        if not active_ids:
            return processed
        advanced = False
        for offset in range(0, len(active_ids), concurrency):
            results = await asyncio.gather(*(
                _resume_job_by_id(item, semaphore, explicit=explicit)
                for item in active_ids[offset:offset + concurrency]
            ))
            advanced = any(results) or advanced
            processed = True
        if not advanced:
            return processed


async def _resume_round_jobs() -> bool:
    """Resume persisted R1-R4 jobs independently of this process' T0."""
    with SessionLocal() as db:
        ids = list(db.scalars(select(PiBackfillJob.id).where(
            PiBackfillJob.round_name.in_(ROUND_NAMES),
            PiBackfillJob.status == "PENDING",
            or_(PiBackfillJob.next_attempt_at.is_(None), PiBackfillJob.next_attempt_at <= _now()),
        ).order_by(PiBackfillJob.updated_at, PiBackfillJob.id)).all())
    return await _resume_jobs(ids)


async def _run_admin_jobs() -> bool:
    with SessionLocal() as db:
        ids = list(db.scalars(select(PiBackfillJob.id).where(
            PiBackfillJob.round_name.is_(None),
            PiBackfillJob.status == "PENDING",
            or_(PiBackfillJob.next_attempt_at.is_(None), PiBackfillJob.next_attempt_at <= _now()),
        ).order_by(PiBackfillJob.id).limit(100)).all())
    return await _resume_jobs(ids)


async def _run_round(tags: list[int], t0: datetime, round_name: str, days_from: int, days_to: int) -> None:
    round_start = t0 - timedelta(days=days_from)
    round_end = t0 - timedelta(days=days_to)
    semaphore = asyncio.Semaphore(max(1, settings.pi_query_concurrency))

    async def process_tag(tag_id: int) -> None:
        with SessionLocal() as db:
            missing = CoverageService.get_missing_intervals(db, tag_id, round_start, round_end, "RECORDED")
        for start, end in missing:
            cursor = start
            while cursor < end:
                window_end = min(cursor + timedelta(days=settings.backfill_chunk_days), end)
                if not await backfill_tag_interval(tag_id, cursor, window_end, t0, round_name, semaphore):
                    return
                cursor = window_end

    await asyncio.gather(*(process_tag(tag_id) for tag_id in tags))


async def run_backfill_loop(
    *, once: bool = False, admin_only: bool = False, job_ids: list[int] | None = None,
) -> None:
    while True:
        acquired = False
        try:
            t0 = _now()
            with SessionLocal() as lock_db:
                postgres = lock_db.bind is not None and lock_db.bind.dialect.name == "postgresql"
                acquired = bool(lock_db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar()) if postgres else True
                try:
                    if acquired:
                        _recover_expired_leases()
                        if job_ids:
                            await _resume_jobs(job_ids, explicit=True)
                        else:
                            admin_ids = _active_job_ids(rounds=False)
                            if admin_ids:
                                await _run_admin_jobs()
                            round_ids = [] if admin_only or admin_ids else _active_job_ids(rounds=True)
                            if round_ids:
                                await _resume_round_jobs()
                            if not admin_only and not admin_ids and not round_ids:
                                tags = list(lock_db.scalars(select(PiTag.id).where(PiTag.active.is_(True)).order_by(PiTag.id)).all())
                                for round_name, days_from, days_to in BACKFILL_ROUNDS:
                                    await _run_round(tags, t0, round_name, days_from, days_to)
                            elif admin_only:
                                logger.info("backfill_admin_cycle_completed")
                        logger.info("backfill_run_completed t0=%s owner=%s", t0, LEASE_OWNER)
                finally:
                    if acquired and postgres:
                        lock_db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        except Exception:
            if once:
                raise
            logger.exception("backfill_run_failed")
        if once:
            return
        await asyncio.sleep(60 if not acquired else 10)
