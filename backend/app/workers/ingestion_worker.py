"""Idempotent ten-second PI ingestion worker."""
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


def _mode_for(tag: PiTag) -> tuple[str, str | None, int | None]:
    mode = (tag.sampling_mode or "RECORDED").upper()
    if mode == "INTERPOLATED_10S":
        return mode, "10s", 10
    return "RECORDED", None, None


def _record(tag_id: int, point: Any, mode: str) -> dict[str, Any]:
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


async def _ingest_tag(tag_id: int, now: datetime) -> tuple[int, int]:
    with SessionLocal() as db:
        tag = db.get(PiTag, tag_id)
        if tag is None or not tag.active:
            return 0, 0
        state = db.get(PiIngestionState, tag.id)
        mode, interval, interval_seconds = _mode_for(tag)
        watermark = state.watermark_ts if state and state.watermark_ts else now - timedelta(seconds=settings.ingestion_overlap_seconds)
        start = min(watermark, now - timedelta(seconds=settings.ingestion_overlap_seconds))
        result = await PiService(db).fetch_time_series(TimeSeriesRequest(
            tag_ids=[tag.id], start_time=start, end_time=now,
            mode="interpolated" if interval else "recorded", interval=interval,
        ))
        if result.errors:
            if state is None:
                state = PiIngestionState(tag_id=tag.id)
                db.add(state)
            state.consecutive_failures = (state.consecutive_failures or 0) + 1
            state.last_error_code = str(result.errors[0].get("code", "PI_ERROR"))
            state.last_error_message = str(result.errors[0].get("message", "Falha de ingestao"))
            db.commit()
            return 0, 0

        points = result.series[0].points if result.series else []
        if points:
            records = [_record(tag.id, point, mode) for point in points]
            insert_factory = pg_insert if db.bind is not None and db.bind.dialect.name == "postgresql" else sqlite_insert
            stmt = insert_factory(PiSample).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["tag_id", "ts"],
                set_={column: getattr(stmt.excluded, column) for column in (
                    "value_type", "value_double", "value_boolean", "value_text",
                    "good", "questionable", "substituted", "source_mode",
                )},
            )
            db.execute(stmt)
            max_ts = max(point.timestamp for point in points).astimezone(timezone.utc)
        else:
            max_ts = watermark

        # Empty but successful PI responses are valid coverage.  All of these
        # writes are one transaction so a crash cannot advance only the state.
        CoverageService.record_coverage(
            db, tag.id, start, now, mode, interval_seconds, pi_web_id=tag.pi_web_id
        )
        if state is None:
            state = PiIngestionState(tag_id=tag.id)
            db.add(state)
        state.watermark_ts = max_ts
        state.last_source_ts = max_ts
        state.last_success_at = now
        state.consecutive_failures = 0
        state.last_error_code = None
        state.last_error_message = None
        db.commit()
        return len(points), 1


async def run_ingestion_loop(interval_seconds: float = 10.0, *, once: bool = False) -> None:
    """Run cycles without overlapping leaders; safe to run in many processes."""
    interval_seconds = interval_seconds or settings.ingestion_cycle_seconds
    while True:
        cycle_started = datetime.now(timezone.utc)
        acquired = False
        try:
            with SessionLocal() as db:
                if db.bind is not None and db.bind.dialect.name == "postgresql":
                    acquired = bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar())
                else:
                    acquired = True
                if not acquired:
                    logger.debug("ingestion_leader_busy")
                else:
                    tags = db.execute(select(PiTag).where(PiTag.active.is_(True))).scalars().all()
                    tag_ids = {tag.id for tag in tags}
                    for tag in tags:
                        tag_ids.update(filter(None, (tag.lower_limit_tag_id, tag.upper_limit_tag_id)))
                    total_points = 0
                    for tag_id in sorted(tag_ids):
                        points, _ = await _ingest_tag(tag_id, cycle_started)
                        total_points += points
                    logger.info("ingestion_cycle_completed duration_ms=%d points_written=%d tag_count=%d", int((datetime.now(timezone.utc) - cycle_started).total_seconds() * 1000), total_points, len(tag_ids))
                if acquired and db.bind is not None and db.bind.dialect.name == "postgresql":
                    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        except Exception:
            if once:
                raise
            logger.exception("ingestion_cycle_failed")
        if once:
            return
        elapsed = (datetime.now(timezone.utc) - cycle_started).total_seconds()
        await asyncio.sleep(max(0.0, interval_seconds - elapsed))
