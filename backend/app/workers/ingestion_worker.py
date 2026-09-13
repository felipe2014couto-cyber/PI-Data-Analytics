"""Supervised, idempotent multimode PI ingestion worker."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.pi_tag import PiTag
from app.models.postgres import PiIngestionState, PiSample
from app.schemas.pi import TimeSeriesRequest
from app.services.coverage_service import CoverageService
from app.services.pi_service import PiService

logger = logging.getLogger("workers.ingestion")
LOCK_KEY = 2147483001


def _modes_for(tag: PiTag) -> tuple[tuple[str, str | None, int | None], ...]:
    """Return the single raw mode used as the source for Plot aggregates."""
    return (("RECORDED", None, None),)


def _mode_for(tag: PiTag) -> tuple[str, str | None, int | None]:
    """Backward-compatible helper for existing callers."""
    return _modes_for(tag)[0]


def _window_for(mode: str) -> timedelta:
    if mode == "INTERPOLATED_10S":
        return timedelta(hours=settings.ingestion_interpolated_10s_window_hours)
    if mode == "INTERPOLATED_300S":
        return timedelta(days=settings.ingestion_interpolated_300s_window_days)
    return timedelta(seconds=settings.ingestion_recorded_window_seconds)


def _record(tag_id: int, point: Any, mode: str) -> dict[str, Any]:
    value_type = "boolean" if isinstance(point.value, bool) else "double" if isinstance(point.value, (int, float)) else "string"
    return {"tag_id": tag_id, "ts": point.timestamp.astimezone(timezone.utc), "value_type": value_type,
            "value_double": float(point.value) if value_type == "double" else None,
            "value_boolean": bool(point.value) if value_type == "boolean" else None,
            "value_text": str(point.value) if value_type == "string" and point.value is not None else None,
            "good": point.good, "questionable": point.questionable, "substituted": point.substituted,
            "source_mode": mode}


def _safe_error(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit] or "Falha de ingestão"


async def _fetch_points(
    service: PiService,
    tag_id: int,
    start: datetime,
    end: datetime,
    *,
    mode: str,
    interval: str | None,
    max_count: int | None,
    depth: int = 0,
) -> tuple[list[Any], dict[str, Any] | None]:
    """Fetch one window, splitting RecordedValues when maxCount is reached."""
    result = await service.fetch_time_series(TimeSeriesRequest(
        tag_ids=[tag_id],
        start_time=start,
        end_time=end,
        mode="interpolated" if interval else "recorded",
        interval=interval,
        max_count=max_count,
    ))
    error = next(iter(result.errors), None)
    if error:
        return [], error
    points = list(result.series[0].points if result.series else [])
    points = [
        point for point in points
        if start <= point.timestamp.astimezone(timezone.utc) < end
    ]
    if mode != "RECORDED" or max_count is None or len(points) < max_count:
        return points, None
    duration = end - start
    if depth >= 12 or duration <= timedelta(seconds=1):
        raise RuntimeError("RecordedValues atingiu maxCount na menor janela permitida")
    midpoint = start + duration / 2
    left, error = await _fetch_points(
        service, tag_id, start, midpoint, mode=mode, interval=interval,
        max_count=max_count, depth=depth + 1,
    )
    if error:
        return [], error
    right, error = await _fetch_points(
        service, tag_id, midpoint, end, mode=mode, interval=interval,
        max_count=max_count, depth=depth + 1,
    )
    if error:
        return [], error
    return left + right, None


def _live_window(now: datetime, watermark: datetime | None, window: timedelta) -> tuple[datetime, datetime]:
    """Return only the live ingestion window; historical gaps belong to backfill."""
    live_start = now - window
    if watermark is None:
        return live_start, now
    overlap = timedelta(seconds=settings.ingestion_overlap_seconds)
    # A recent watermark is deliberately overlapped, including when a cycle
    # starts a few milliseconds late.  An old watermark is ignored so this
    # worker never turns into an accidental historical backfill.
    if watermark >= live_start - overlap:
        return min(live_start, watermark - overlap), now
    return live_start, now


def _state_timestamps(
    points: list[Any],
    end: datetime,
    previous_last_source: datetime | None,
) -> tuple[datetime, datetime | None]:
    """Separate coverage progress from the timestamp of the last real PI event."""
    last_source = previous_last_source
    if points:
        last_source = max(point.timestamp for point in points).astimezone(timezone.utc)
    return end, last_source


async def _ingest_tag(tag_id: int, now: datetime, source_mode: str | None = None) -> tuple[int, int]:
    with SessionLocal() as db:
        tag = db.get(PiTag, tag_id)
        if tag is None or not tag.active:
            return 0, 0
        modes = tuple(item for item in _modes_for(tag) if source_mode is None or item[0] == source_mode)
        total_points = 0
        requests = 0
        for mode, interval, interval_seconds in modes:
            state = db.get(PiIngestionState, (tag.id, mode))
            watermark = state.watermark_ts if state and state.watermark_ts else None
            window = _window_for(mode)
            # The continuous worker must stay at the live edge. Historical
            # gaps are durable backfill jobs and must never consume this loop.
            start, end = _live_window(now, watermark, window)
            if start >= end:
                continue
            try:
                points, result_error = await _fetch_points(
                    PiService(db), tag.id, start, end,
                    mode=mode, interval=interval,
                    max_count=settings.ingestion_recorded_max_points if mode == "RECORDED" else None,
                )
            except Exception as exc:
                if state is None:
                    state = PiIngestionState(tag_id=tag.id, source_mode=mode); db.add(state)
                state.consecutive_failures = (state.consecutive_failures or 0) + 1
                state.last_error_code = "PI_ERROR"; state.last_error_message = _safe_error(exc)
                state.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(state.consecutive_failures, 8)))
                db.commit(); raise
            if result_error:
                if state is None:
                    state = PiIngestionState(tag_id=tag.id, source_mode=mode); db.add(state)
                state.consecutive_failures = (state.consecutive_failures or 0) + 1
                state.last_error_code = _safe_error(result_error.get("code", "PI_ERROR"), 255)
                state.last_error_message = _safe_error(result_error.get("message", "Falha de ingestão"))
                state.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(state.consecutive_failures, 8)))
                db.commit()
                # Propagate the failure to the cycle supervisor so this
                # minute is retried on the next cycle instead of being
                # counted as a successful RecordedValues pass.
                raise RuntimeError(state.last_error_message)
            points = list({point.timestamp.astimezone(timezone.utc): point for point in points}.values())
            if points:
                records = [_record(tag.id, point, mode) for point in points]
                insert_factory = pg_insert if db.bind is not None and db.bind.dialect.name == "postgresql" else sqlite_insert
                for offset in range(0, len(records), 500):
                    stmt = insert_factory(PiSample).values(records[offset:offset + 500])
                    stmt = stmt.on_conflict_do_update(index_elements=["tag_id", "ts", "source_mode"], set_={column: getattr(stmt.excluded, column) for column in (
                        "value_type", "value_double", "value_boolean", "value_text", "good", "questionable", "substituted", "source_mode")})
                    db.execute(stmt)
            # Coverage follows the committed UPSERT in this transaction.
            CoverageService.record_coverage(db, tag.id, start, end, mode, interval_seconds, pi_web_id=tag.pi_web_id)
            if state is None:
                state = PiIngestionState(tag_id=tag.id, source_mode=mode); db.add(state)
            watermark_ts, last_source_ts = _state_timestamps(
                points,
                end,
                state.last_source_ts,
            )
            state.watermark_ts = watermark_ts
            state.last_source_ts = last_source_ts
            state.last_success_at = now
            state.consecutive_failures = 0; state.last_error_code = None; state.last_error_message = None; state.next_attempt_at = None
            db.commit(); total_points += len(points); requests += 1
        return total_points, requests


async def run_ingestion_loop(interval_seconds: float = 10.0, *, once: bool = False) -> None:
    """Run cycles with global concurrency one and a small circuit breaker."""
    interval_seconds = interval_seconds or settings.ingestion_cycle_seconds
    last_recorded_cycle: datetime | None = None
    while True:
        cycle_started = datetime.now(timezone.utc); acquired = False
        recorded_due = (
            last_recorded_cycle is None
            or (cycle_started - last_recorded_cycle).total_seconds()
            >= settings.ingestion_recorded_cycle_seconds
        )
        try:
            with SessionLocal() as db:
                if db.bind is not None and db.bind.dialect.name == "postgresql":
                    acquired = bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar())
                else: acquired = True
                if acquired:
                    tags = db.execute(select(PiTag).where(PiTag.active.is_(True))).scalars().all()
                    tag_ids = {tag.id for tag in tags}
                    for tag in tags: tag_ids.update(filter(None, (tag.lower_limit_tag_id, tag.upper_limit_tag_id)))
                    failures = 0; total_points = 0; cycle_failed = False
                    for tag_id in sorted(tag_ids):
                        try:
                            points, _ = await _ingest_tag(
                                tag_id, cycle_started,
                                source_mode=None if recorded_due else "__INTERPOLATED_ONLY__",
                            )
                            total_points += points; failures = 0
                        except Exception as exc:
                            cycle_failed = True
                            failures += 1; logger.exception("ingestion_tag_failed tag_id=%s error=%s", tag_id, _safe_error(exc))
                            if failures >= 3:
                                logger.error("ingestion_circuit_open failures=%d", failures); break
                    logger.info("ingestion_cycle_completed duration_ms=%d points_written=%d tag_count=%d", int((datetime.now(timezone.utc) - cycle_started).total_seconds() * 1000), total_points, len(tag_ids))
                    # Do not advance the one-minute RecordedValues cadence
                    # after a partial/failed cycle.  The next cycle retries
                    # the same live window instead of silently acknowledging
                    # a tag that was not ingested.
                    if recorded_due and not cycle_failed:
                        last_recorded_cycle = cycle_started
                if acquired and db.bind is not None and db.bind.dialect.name == "postgresql":
                    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        except Exception:
            if once: raise
            logger.exception("ingestion_cycle_failed")
        if once: return
        elapsed = (datetime.now(timezone.utc) - cycle_started).total_seconds()
        await asyncio.sleep(max(0.0, interval_seconds - elapsed))
