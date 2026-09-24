"""Durable, range-scoped refresh of Plot continuous aggregates."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.database.session import SessionLocal, engine
from app.models.postgres import PiBackfillJob, PiCaggRefreshJob
from app.services.database_time_series_service import invalidate_time_series_cache

logger = logging.getLogger("workers.cagg_refresh")

_CAGGS = (
    (10, "pi_recorded_plot_10s"),
    (60, "pi_recorded_plot_1m"),
    (300, "pi_recorded_plot_5m"),
    (3600, "pi_recorded_plot_hourly"),
    (86400, "pi_recorded_plot_daily"),
)
_LOCK_KEY = 2147483004


def cagg_refresh_schema_available() -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT to_regclass('public.pi_cagg_refresh_jobs') IS NOT NULL")).scalar_one()


def enqueue_cagg_refresh(backfill_job_id: int, tag_id: int, start: datetime, end: datetime) -> None:
    """Enqueue only after raw persistence has committed."""
    invalidate_time_series_cache([tag_id], start, end)
    if not cagg_refresh_schema_available():
        logger.error("cagg_refresh_not_enqueued schema_not_available backfill_job_id=%s", backfill_job_id)
        return
    with SessionLocal.begin() as db:
        existing = db.scalar(select(PiCaggRefreshJob).where(PiCaggRefreshJob.backfill_job_id == backfill_job_id))
        if existing is None:
            db.add(PiCaggRefreshJob(
                backfill_job_id=backfill_job_id, tag_id=tag_id,
                range_start=start, range_end=end, status="PENDING",
            ))
        db.execute(text("""
            UPDATE pi_backfill_jobs
            SET materialization_status = 'PENDING', materialization_error = NULL
            WHERE id = :job_id
        """), {"job_id": backfill_job_id})


def _align(value: datetime, seconds: int, *, ceil: bool) -> datetime:
    stamp = value.astimezone(timezone.utc).timestamp()
    aligned = ((int(stamp) + seconds - 1) // seconds if ceil else int(stamp) // seconds) * seconds
    return datetime.fromtimestamp(aligned, timezone.utc)


def process_one_cagg_refresh() -> bool:
    """Claim and process one retryable refresh job outside backfill transactions."""
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        job = db.scalar(select(PiCaggRefreshJob).where(
            PiCaggRefreshJob.status.in_(("PENDING", "FAILED")),
            (PiCaggRefreshJob.next_attempt_at.is_(None) | (PiCaggRefreshJob.next_attempt_at <= now)),
        ).order_by(PiCaggRefreshJob.id).with_for_update(skip_locked=True))
        if job is None:
            return False
        job.status = "RUNNING"
        job.attempts += 1
        job.error_message = None
        job_id, backfill_job_id, tag_id = job.id, job.backfill_job_id, job.tag_id
        range_start, range_end = job.range_start, job.range_end
        db.execute(text("UPDATE pi_backfill_jobs SET materialization_status='RUNNING' WHERE id=:id"), {"id": backfill_job_id})

    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            locked = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY}).scalar_one())
            if not locked:
                raise RuntimeError("cagg refresh advisory lock is busy")
            try:
                for seconds, name in _CAGGS:
                    start = _align(range_start, seconds, ceil=False)
                    end = _align(range_end, seconds, ceil=True)
                    if start >= end:
                        continue
                    logger.info("cagg_refresh_started job_id=%s aggregate=%s start=%s end=%s", job_id, name, start, end)
                    conn.execute(text("CALL refresh_continuous_aggregate(:name, :start, :end)"), {"name": name, "start": start, "end": end})
                    logger.info("cagg_refresh_completed job_id=%s aggregate=%s start=%s end=%s", job_id, name, start, end)
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})
        invalidate_time_series_cache([tag_id], range_start, range_end)
        with SessionLocal.begin() as db:
            row = db.get(PiCaggRefreshJob, job_id)
            row.status = "COMPLETED"
            row.error_message = None
            row.next_attempt_at = None
            db.execute(text("UPDATE pi_backfill_jobs SET materialization_status='COMPLETED', materialization_error=NULL WHERE id=:id"), {"id": backfill_job_id})
        return True
    except Exception as exc:
        message = str(exc)[:1000]
        with SessionLocal.begin() as db:
            row = db.get(PiCaggRefreshJob, job_id)
            row.status = "FAILED"
            row.error_message = message
            row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
            db.execute(text("UPDATE pi_backfill_jobs SET materialization_status='FAILED', materialization_error=:error WHERE id=:id"), {"id": backfill_job_id, "error": message})
        logger.exception("cagg_refresh_failed job_id=%s", job_id)
        return True
