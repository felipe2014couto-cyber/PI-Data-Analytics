"""Durable, round-robin backfill worker with a fixed T0 per run."""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
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
BACKFILL_ROUNDS = (
    ("R1", 7, 0),
    ("R2", 30, 7),
    ("R3", 90, 30),
    ("R4", 365, 90),
)
LOCK_KEY = 2147483002


def _record(tag_id: int, point: Any, mode: str = "RECORDED") -> dict[str, Any]:
    value_type = "boolean" if isinstance(point.value, bool) else "double" if isinstance(point.value, (int, float)) else "string"
    return {
        "tag_id": tag_id,
        "ts": point.timestamp.astimezone(timezone.utc),
        "value_type": value_type,
        "value_double": float(point.value) if value_type == "double" else None,
        "value_boolean": bool(point.value) if value_type == "boolean" else None,
        "value_text": str(point.value) if value_type == "string" and point.value is not None else None,
        "good": point.good, "questionable": point.questionable, "substituted": point.substituted,
        "source_mode": mode,
    }


async def _fetch_with_retry(service: PiService, request: TimeSeriesRequest) -> Any:
    for attempt in range(1, settings.pi_request_max_retries + 2):
        try:
            return await service.fetch_time_series(request)
        except PiIntegrationError as exc:
            if not exc.retryable or attempt >= settings.pi_request_max_retries + 1:
                raise
            retry_after = None
            if isinstance(exc.details, dict):
                try:
                    retry_after = float(exc.details.get("retry_after"))
                except (TypeError, ValueError):
                    pass
            delay = retry_after if retry_after is not None else min(2 ** (attempt - 1), 30)
            await asyncio.sleep(max(0.1, min(delay, 60.0)) + random.uniform(0, 0.5))


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
    _split_depth: int = 0,
) -> bool:
    split_window: tuple[datetime, datetime] | None = None
    completed = False
    await semaphore.acquire()
    try:
        with SessionLocal() as db:
            tag = db.get(PiTag, tag_id)
            if tag is None or not tag.active:
                return False
            job = db.get(PiBackfillJob, job_id) if job_id is not None else db.execute(select(PiBackfillJob).where(
                PiBackfillJob.tag_id == tag_id,
                PiBackfillJob.round_name == round_name,
                PiBackfillJob.t0 == t0,
                PiBackfillJob.target_start == start,
                PiBackfillJob.target_end == end,
            )).scalar_one_or_none()
            if job is None:
                job = PiBackfillJob(tag_id=tag_id, mode=mode, interval_seconds=interval_seconds,
                                    target_start=start, target_end=end, next_start=start,
                                    t0=t0, round_name=round_name, stage="RUNNING", status="RUNNING")
                db.add(job)
            elif job.status == "CANCELLED":
                return False
            job.mode = mode
            job.interval_seconds = interval_seconds
            job.stage = "RUNNING"
            job.status = "RUNNING"
            job.attempts = (job.attempts or 0) + 1
            db.commit()

            try:
                request_mode = "interpolated" if mode.startswith("INTERPOLATED_") else "recorded"
                request_interval = f"{interval_seconds}s" if request_mode == "interpolated" else None
                result = await _fetch_with_retry(PiService(db), TimeSeriesRequest(
                    tag_ids=[tag_id], start_time=start, end_time=end,
                    mode=request_mode, interval=request_interval,
                    max_count=max_count,
                ))
                error = next(iter(result.errors), None)
                duration = end - start
                minimum_window = timedelta(minutes=15)
                if error:
                    error_code = str(error.get("code") or "PI_ERROR")
                    if error_code == "PI_TIMEOUT" and duration > minimum_window:
                        midpoint = start + duration / 2
                        split_window = (start, midpoint)
                    else:
                        raise RuntimeError(f"PI {error_code}: resposta nao completa")
                points = [
                    point for point in (result.series[0].points if result.series else [])
                    if start <= point.timestamp.astimezone(timezone.utc) < end
                ]
                too_many = max_count is not None and len(points) >= max_count
                if too_many and duration > minimum_window:
                    midpoint = start + duration / 2
                    split_window = (start, midpoint)
                elif too_many:
                    raise RuntimeError("resposta PI excede maxCount na janela minima")
                if split_window is not None:
                    logger.info(
                        "backfill_window_split tag_id=%s job_id=%s start=%s end=%s depth=%s",
                        tag_id, job_id, start, end, _split_depth,
                    )
                    return_value = None
                else:
                    return_value = True
                if return_value is None:
                    # The recursive calls happen after releasing the semaphore.
                    pass
                else:
                    # PI can return the same event more than once at a boundary;
                    # collapse it before a single INSERT ... ON CONFLICT statement.
                    points = list({point.timestamp.astimezone(timezone.utc): point for point in points}.values())
                    if points:
                        insert_factory = pg_insert if db.bind is not None and db.bind.dialect.name == "postgresql" else sqlite_insert
                        records = [_record(tag_id, point, mode) for point in points]
                        for offset in range(0, len(records), 500):
                            stmt = insert_factory(PiSample).values(records[offset:offset + 500])
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["tag_id", "ts", "source_mode"],
                                set_={column: getattr(stmt.excluded, column) for column in (
                                    "value_type", "value_double", "value_boolean", "value_text", "good", "questionable", "substituted", "source_mode"
                                )},
                            )
                            db.execute(stmt)
                    CoverageService.record_coverage(db, tag_id, start, end, mode, interval_seconds, pi_web_id=tag.pi_web_id)
                    job.next_start = end
                    job.checkpoint_start = end
                    is_final = end >= job.target_end
                    job.stage = "READY"
                    job.status = "COMPLETED" if is_final else "PENDING"
                    job.error_message = None
                    db.commit()
                    completed = True
                    logger.info("backfill_window_completed tag_id=%s round=%s mode=%s start=%s end=%s points=%d final=%s", tag_id, round_name, mode, start, end, len(points), is_final)
            except PiIntegrationError as exc:
                db.rollback()
                if exc.code == "PI_TIMEOUT" and (end - start) > timedelta(minutes=15):
                    split_window = (start, start + (end - start) / 2)
                else:
                    job = db.get(PiBackfillJob, job.id)
                    if job is not None:
                        job.stage = "FAILED"
                        job.status = "FAILED"
                        job.error_message = exc.safe_message[:2000]
                        job.last_error_at = datetime.now(timezone.utc)
                        db.commit()
                if split_window is None:
                    logger.exception("backfill_window_failed tag_id=%s round=%s mode=%s", tag_id, round_name, mode)
                    return False
            except Exception as exc:
                db.rollback()
                if split_window is None:
                    job = db.get(PiBackfillJob, job.id)
                    if job is not None:
                        job.stage = "FAILED"
                        job.status = "FAILED"
                        job.error_message = str(exc)[:2000]
                        job.last_error_at = datetime.now(timezone.utc)
                        db.commit()
                logger.exception("backfill_window_failed tag_id=%s round=%s mode=%s", tag_id, round_name, mode)
                if split_window is None:
                    return False
    finally:
        semaphore.release()

    if split_window is not None:
        split_start, midpoint = split_window
        left = await backfill_tag_interval(
            tag_id, split_start, midpoint, t0, round_name, semaphore,
            mode=mode, interval_seconds=interval_seconds, job_id=job_id,
            max_count=max_count, _split_depth=_split_depth + 1,
        )
        if not left:
            return False
        right = await backfill_tag_interval(
            tag_id, midpoint, end, t0, round_name, semaphore,
            mode=mode, interval_seconds=interval_seconds, job_id=job_id,
            max_count=max_count, _split_depth=_split_depth + 1,
        )
        return left and right
    return completed


async def _run_admin_jobs(jobs: list[PiBackfillJob] | None = None) -> None:
    """Process explicit administrative reload jobs before legacy round-robin work."""
    semaphore = asyncio.Semaphore(max(1, settings.pi_query_concurrency))
    if jobs is None:
        with SessionLocal() as db:
            jobs = list(db.scalars(select(PiBackfillJob).where(
                PiBackfillJob.status.in_(("PENDING", "RUNNING")),
                PiBackfillJob.round_name.is_(None),
            ).order_by(PiBackfillJob.id).limit(100)).all())
    jobs.sort(key=lambda job: (0 if job.mode == "INTERPOLATED_300S" else 1 if job.mode == "INTERPOLATED_10S" else 2, job.id))
    selected_ids = {job.id for job in jobs}
    while True:
        with SessionLocal() as db:
            pending = list(db.scalars(select(PiBackfillJob).where(
                PiBackfillJob.id.in_(selected_ids),
                PiBackfillJob.status.in_(("PENDING", "RUNNING")),
            ).order_by(PiBackfillJob.id)).all())
        if not pending:
            return
        progressed = False
        for job in pending:
            cursor = job.next_start or job.target_start
            if cursor >= job.target_end:
                continue
            if job.mode == "INTERPOLATED_300S":
                window = timedelta(days=30)
            elif job.mode == "INTERPOLATED_10S":
                window = timedelta(hours=settings.backfill_recorded_window_hours)
            else:
                window = timedelta(hours=settings.backfill_recorded_window_hours)
            window_end = min(cursor + window, job.target_end)
            ok = await backfill_tag_interval(
                job.tag_id, cursor, window_end,
                job.t0 or job.created_at or datetime.now(timezone.utc), "ADMIN", semaphore,
                mode=job.mode or "RECORDED", interval_seconds=job.interval_seconds,
                job_id=job.id,
                max_count=settings.backfill_recorded_max_points if job.mode in ("RECORDED", "INTERPOLATED_10S") else None,
            )
            if not ok:
                return
            progressed = True
        if not progressed:
            return


async def _run_round(tags: list[int], t0: datetime, round_name: str, days_from: int, days_to: int) -> None:
    round_start = t0 - timedelta(days=days_from)
    round_end = t0 - timedelta(days=days_to)
    semaphore = asyncio.Semaphore(max(1, settings.pi_query_concurrency))
    # One task per tag, but each tag's missing windows are processed in order.
    async def process_tag(tag_id: int) -> None:
        with SessionLocal() as db:
            missing = CoverageService.get_missing_intervals(db, tag_id, round_start, round_end, "RECORDED")
        for start, end in missing:
            cursor = start
            while cursor < end:
                window_end = min(cursor + timedelta(days=settings.backfill_chunk_days), end)
                await backfill_tag_interval(tag_id, cursor, window_end, t0, round_name, semaphore)
                cursor = window_end
    await asyncio.gather(*(process_tag(tag_id) for tag_id in tags))


async def run_backfill_loop(*, once: bool = False) -> None:
    while True:
        acquired = False
        try:
            t0 = datetime.now(timezone.utc)
            with SessionLocal() as db:
                if db.bind is not None and db.bind.dialect.name == "postgresql":
                    acquired = bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar())
                else:
                    acquired = True
                tags = db.execute(select(PiTag.id).where(PiTag.active.is_(True)).order_by(PiTag.id)).scalars().all()
                if acquired:
                    admin_jobs = list(db.scalars(select(PiBackfillJob).where(
                        PiBackfillJob.status.in_(("PENDING", "RUNNING")),
                        PiBackfillJob.round_name.is_(None),
                    ).order_by(PiBackfillJob.id).limit(100)).all())
                    if admin_jobs:
                        await _run_admin_jobs(admin_jobs)
                    else:
                        for round_name, days_from, days_to in BACKFILL_ROUNDS:
                            await _run_round(list(tags), t0, round_name, days_from, days_to)
                    logger.info("backfill_run_completed t0=%s tag_count=%d", t0, len(tags))
                    if db.bind is not None and db.bind.dialect.name == "postgresql":
                        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        except Exception:
            if once:
                raise
            logger.exception("backfill_run_failed")
        if once:
            return
        await asyncio.sleep(60 if not acquired else 10)
