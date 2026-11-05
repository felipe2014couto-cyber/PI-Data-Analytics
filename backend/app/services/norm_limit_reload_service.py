"""Materialize active visual norm-limit PI RECORDED events locally."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.database.session import SessionLocal
from app.integrations.pi.manager import get_pi_data_provider
from app.services.coverage_service import CoverageService
from app.models.postgres import PiIngestionState

logger = logging.getLogger("workers.norm_limits")
NORM_LIMIT_STATE_MODE = "NORM_LIMIT"


@dataclass(frozen=True)
class TagReloadResult:
    server: str
    tag_name: str
    status: str
    samples: int = 0
    seeded: bool = False
    error: str | None = None
    pi_calls: int = 0
    event_calls: int = 0
    seed_calls: int = 0
    resolve_calls: int = 0
    duration_ms: float = 0.0
    start: datetime | None = None
    end: datetime | None = None


def _configured_limit_refs(db) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT id AS source_id, pi_server, equipment_id, variable_type_id,
               trim(lower_limit_tag) AS tag_name
        FROM pi_tags WHERE active = TRUE AND lifecycle_status = 'ACTIVE'
          AND lower_limit_tag IS NOT NULL AND trim(lower_limit_tag) <> ''
        UNION ALL
        SELECT id AS source_id, pi_server, equipment_id, variable_type_id,
               trim(upper_limit_tag) AS tag_name
        FROM pi_tags WHERE active = TRUE AND lifecycle_status = 'ACTIVE'
          AND upper_limit_tag IS NOT NULL AND trim(upper_limit_tag) <> ''
    """)).mappings().all()
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        unique.setdefault((row["pi_server"], row["tag_name"].strip()), dict(row))
    return list(unique.values())


def _local_tag(db, server: str, tag_name: str):
    return db.execute(text("""
        SELECT id, pi_web_id FROM pi_tags
        WHERE pi_server = :server AND pi_tag_name = :tag_name
    """), {"server": server, "tag_name": tag_name}).mappings().one_or_none()


def _materialized_watermark(db, tag_id: int) -> datetime | None:
    state_value = db.execute(text("""
        SELECT watermark_ts FROM pi_ingestion_state
        WHERE tag_id = :tag_id AND source_mode = :source_mode
    """), {"tag_id": tag_id, "source_mode": NORM_LIMIT_STATE_MODE}).scalar_one_or_none()
    if state_value is not None:
        value = state_value
    else:
        # Adopt materialized progress written before the dedicated cursor.
        value = db.execute(text("""
        SELECT max(range_end) FROM pi_ingestion_coverage
        WHERE tag_id = :tag_id AND mode = 'RECORDED'
          AND status IN ('COMPLETE', 'EMPTY_CONFIRMED')
        """), {"tag_id": tag_id}).scalar_one_or_none()
        if value is None:
            value = db.execute(text("""
                SELECT max(ts) FROM pi_samples_timescale
                WHERE tag_id = :tag_id AND source_mode = 'RECORDED'
            """), {"tag_id": tag_id}).scalar_one_or_none()
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value is not None:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value


def _materialization_baseline(db, tag_id: int, cursor: datetime | None) -> datetime | None:
    """Return the first confirmed coverage start, or a new tag's saved baseline."""
    baseline = db.execute(text("""
        SELECT min(range_start) FROM pi_ingestion_coverage
        WHERE tag_id = :tag_id AND mode = 'RECORDED'
          AND status IN ('COMPLETE', 'EMPTY_CONFIRMED')
    """), {"tag_id": tag_id}).scalar_one_or_none()
    if baseline is None:
        baseline = cursor
    if isinstance(baseline, str):
        baseline = datetime.fromisoformat(baseline.replace("Z", "+00:00"))
    if baseline is not None:
        baseline = baseline.replace(tzinfo=timezone.utc) if baseline.tzinfo is None else baseline.astimezone(timezone.utc)
    return baseline


def _coverage_gaps_to_cursor(db, tag_id: int, cursor: datetime) -> list[tuple[datetime, datetime]]:
    """Find only uncovered history bounded by already materialized progress."""
    from app.services.coverage_service import CoverageService

    coverage_start = db.execute(text("""
        SELECT min(range_start) FROM pi_ingestion_coverage
        WHERE tag_id = :tag_id AND mode = 'RECORDED'
          AND status IN ('COMPLETE', 'EMPTY_CONFIRMED')
    """), {"tag_id": tag_id}).scalar_one_or_none()
    anchor = coverage_start
    if anchor is None:
        anchor = db.execute(text("""
            SELECT min(ts) FROM pi_samples_timescale
            WHERE tag_id = :tag_id AND source_mode = 'RECORDED'
        """), {"tag_id": tag_id}).scalar_one_or_none()
    if anchor is None:
        return []
    if isinstance(anchor, str):
        anchor = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
    anchor = anchor.replace(tzinfo=timezone.utc) if anchor.tzinfo is None else anchor.astimezone(timezone.utc)
    cursor = cursor.replace(tzinfo=timezone.utc) if cursor.tzinfo is None else cursor.astimezone(timezone.utc)
    if anchor >= cursor:
        return []
    return CoverageService.get_missing_intervals(db, tag_id, anchor, cursor, "RECORDED")


def _advance_contiguous_coverage(db, tag_id: int, cursor: datetime, horizon: datetime) -> datetime:
    """Traverse confirmed coverage through the cycle horizon, stopping at a hole."""
    cursor = cursor.replace(tzinfo=timezone.utc) if cursor.tzinfo is None else cursor.astimezone(timezone.utc)
    horizon = horizon.replace(tzinfo=timezone.utc) if horizon.tzinfo is None else horizon.astimezone(timezone.utc)
    if cursor >= horizon:
        return cursor
    for start, covered_end in CoverageService.get_coverage(db, tag_id, cursor, horizon, "RECORDED"):
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
        covered_end = covered_end.replace(tzinfo=timezone.utc) if covered_end.tzinfo is None else covered_end.astimezone(timezone.utc)
        if start > cursor:
            break
        if covered_end > cursor:
            cursor = covered_end
        if cursor >= horizon:
            return horizon
    return cursor


def _split_intervals(
    intervals: list[tuple[datetime, datetime]],
    max_intervals: int | None = None,
) -> list[tuple[datetime, datetime]]:
    minute = timedelta(minutes=1)
    pieces = []
    for start, end in intervals:
        cursor = start
        while cursor < end:
            next_end = min(cursor + minute, end)
            pieces.append((cursor, next_end))
            cursor = next_end
            if max_intervals is not None and len(pieces) >= max_intervals:
                return pieces
    return pieces



def _register_dependency(db, source: dict[str, Any], tag_name: str, web_id: str) -> int:
    """Create a dependency row only during explicit materialization.

    It is inactive so this metadata row does not enroll the point in ordinary
    active-tag ingestion. No schema-specific ORM columns are selected.
    """
    values = {
        "equipment_id": source["equipment_id"],
        "variable_type_id": source["variable_type_id"],
        "pi_server": source["pi_server"],
        "pi_tag_name": tag_name,
        "pi_web_id": web_id,
        "tag_kind": "DEPENDENCY",
        "display_name": tag_name,
        "data_type": "NUMERIC",
        "active": False,
        "validation_status": "VALID",
    }
    sql = text("""
        INSERT INTO pi_tags (equipment_id, variable_type_id, pi_server, pi_tag_name,
          pi_web_id, tag_kind, display_name, data_type, active, validation_status)
        VALUES (:equipment_id, :variable_type_id, :pi_server, :pi_tag_name,
          :pi_web_id, :tag_kind, :display_name, :data_type, :active, :validation_status)
        ON CONFLICT (pi_server, pi_tag_name) DO UPDATE SET pi_web_id = EXCLUDED.pi_web_id
        RETURNING id
    """)
    return int(db.execute(sql, values).scalar_one())


async def _fetch_target(
    provider, source, intervals: list[tuple[datetime, datetime]], max_count: int, *,
    seed_start: datetime | None = None, local=None, page_budget: int = 1024,
    metrics: dict[str, int] | None = None, initial_watermark: datetime | None = None,
    coverage_end: datetime | None = None, incremental: bool = True,
) -> tuple[int, int, bool, int, int, int, datetime | None]:
    metrics = metrics if metrics is not None else {"event_calls": 0, "seed_calls": 0, "resolve_calls": 0}
    server, name = source["pi_server"], source["tag_name"]
    point = None
    if local is None or not local["pi_web_id"]:
        metrics["resolve_calls"] += 1
        point = await provider.resolve_point(f"\\\\{server}\\{name.lstrip('\\\\')}")
        if point is None:
            raise LookupError(f"Tag PI {name!r} nao encontrada no servidor {server!r}.")
        web_id = point.web_id
    else:
        web_id = local["pi_web_id"]

    seed = None
    if seed_start is not None:
        metrics["seed_calls"] += 1
        boundary = await provider.get_recorded_values_boundary(
            web_id, seed_start, seed_start + timedelta(microseconds=1),
            boundary_type="Outside", max_count=2,
        )
        seeds = [p for p in boundary.values if p.timestamp.astimezone(timezone.utc) < seed_start]
        seed = max(seeds, key=lambda p: p.timestamp) if seeds else None

    from app.workers.ingestion_worker import (
        BudgetExhaustedError, FetchStats, _fetch_complete_interval, _persist_points,
    )
    total_samples = 0
    completed_intervals = 0
    completed_until = None
    stats = FetchStats()
    for interval_index, (start, end) in enumerate(intervals):
        points: list[Any] = []
        try:
            points = await _fetch_complete_interval(
                provider, web_id, start, end, max_count=max_count,
                stats=stats, page_budget=page_budget,
            )
        except BudgetExhaustedError:
            # Completed intervals stay committed. The persisted cursor makes
            # the next minute resume at the first unfinished interval.
            break
        finally:
            # FetchStats.pages includes the budget guard attempt; count only
            # actual provider pages for the operational call metric.
            metrics["event_calls"] = min(stats.pages, page_budget)

        interval_seed = seed if interval_index == 0 else None
        batch = ([interval_seed] if interval_seed is not None else []) + points
        with SessionLocal() as db:
            local = _local_tag(db, server, name)
            if local is None:
                tag_id = _register_dependency(db, source, name, web_id)
            else:
                tag_id = int(local["id"])
                if not local["pi_web_id"]:
                    db.execute(text("UPDATE pi_tags SET pi_web_id=:web_id WHERE id=:id"), {"web_id": web_id, "id": tag_id})
            _persist_points(db, tag_id, batch, "RECORDED")
            CoverageService.record_coverage(
                db, tag_id, start, end, "RECORDED",
                status="COMPLETE" if points else "EMPTY_CONFIRMED",
                pi_web_id=web_id,
            )
            db.flush()
            state = db.get(PiIngestionState, (tag_id, NORM_LIMIT_STATE_MODE))
            if state is None:
                state = PiIngestionState(
                    tag_id=tag_id, source_mode=NORM_LIMIT_STATE_MODE,
                    watermark_ts=initial_watermark,
                )
                db.add(state)
            current_watermark = state.watermark_ts
            if current_watermark is not None:
                current_watermark = current_watermark.replace(tzinfo=timezone.utc) if current_watermark.tzinfo is None else current_watermark.astimezone(timezone.utc)
            cursor_candidates = [value for value in (current_watermark, initial_watermark) if value is not None]
            cursor_start = max(cursor_candidates) if cursor_candidates else end
            new_watermark = max(cursor_start, end)
            # Advance only through confirmed coverage from the materialization
            # baseline. The baseline prevents pre-materialization history from
            # pinning this cursor; later gaps still keep it retryable.
            state.watermark_ts = _advance_contiguous_coverage(
                db, tag_id, cursor_start, coverage_end or end,
            ) if incremental else new_watermark
            state.last_success_at = datetime.now(timezone.utc)
            if batch:
                newest_source = max(point.timestamp.astimezone(timezone.utc) for point in batch)
                last_source = state.last_source_ts
                if last_source is not None:
                    last_source = last_source.replace(tzinfo=timezone.utc) if last_source.tzinfo is None else last_source.astimezone(timezone.utc)
                if last_source is None or newest_source > last_source:
                    state.last_source_ts = newest_source
            state.consecutive_failures = 0
            state.next_attempt_at = None
            state.last_error_code = None
            state.last_error_message = None
            db.commit()
        total_samples += len(batch)
        completed_intervals += 1
        completed_until = end

    return (
        total_samples, completed_intervals, seed is not None,
        metrics["event_calls"], metrics["seed_calls"], metrics["resolve_calls"], completed_until,
    )


async def _reload_norm_limits(
    *, provider=None, now: datetime | None = None, incremental: bool,
) -> list[TagReloadResult]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = now.replace(second=0, microsecond=0) if incremental else now
    manual_start = now - timedelta(days=7)
    with SessionLocal() as db:
        targets = _configured_limit_refs(db)
        db.rollback()
    mode = "incremental" if incremental else "manual_initial"
    cycle_started = time.perf_counter()
    logger.info("norm_limit_reload_started mode=%s tags=%d end=%s", mode, len(targets), end.isoformat())
    if not targets:
        return []
    provider = provider or get_pi_data_provider()
    if provider is None:
        return [TagReloadResult(target["pi_server"], target["tag_name"], "FAILED",
                                error="PI Web API nao configurada", end=end) for target in targets]

    semaphore = asyncio.Semaphore(max(1, min(settings.pi_query_concurrency, 8)))

    async def run_one(source):
        async with semaphore:
            started = time.perf_counter()
            local = None
            metrics = {"event_calls": 0, "seed_calls": 0, "resolve_calls": 0}
            backlog = False
            first_start = None
            try:
                if incremental:
                    with SessionLocal() as db:
                        local = _local_tag(db, source["pi_server"], source["tag_name"])
                        watermark = _materialized_watermark(db, int(local["id"])) if local else None
                        if watermark is None:
                            # An automatically discovered, never-materialized
                            # limit starts at the recent edge. Historical seed
                            # and older samples remain manual-only.
                            watermark = end - timedelta(minutes=1)
                            if local is None:
                                tag_id = _register_dependency(
                                    db, source, source["tag_name"], None,
                                )
                            else:
                                tag_id = int(local["id"])
                            state = db.get(PiIngestionState, (tag_id, NORM_LIMIT_STATE_MODE))
                            if state is None:
                                state = PiIngestionState(
                                    tag_id=tag_id, source_mode=NORM_LIMIT_STATE_MODE,
                                )
                                db.add(state)
                            state.watermark_ts = watermark
                            db.commit()
                            local = _local_tag(db, source["pi_server"], source["tag_name"])
                        else:
                            watermark = watermark.replace(tzinfo=timezone.utc) if watermark.tzinfo is None else watermark.astimezone(timezone.utc)

                        tag_id = int(local["id"])
                        state = db.get(PiIngestionState, (tag_id, NORM_LIMIT_STATE_MODE))

                        baseline = _materialization_baseline(db, tag_id, watermark)
                        if baseline is not None:
                            # Legacy cursors can predate the first known
                            # materialization. Align them to that baseline so
                            # pre-materialization history never blocks them.
                            watermark = max(watermark, baseline)
                        scan_start = baseline or watermark
                        missing_intervals = CoverageService.get_missing_intervals(
                            db, tag_id, scan_start, end, "RECORDED",
                        ) if scan_start < end else []

                        if not missing_intervals:
                            watermark = max(watermark, end)
                            if state is None:
                                state = PiIngestionState(
                                    tag_id=tag_id, source_mode=NORM_LIMIT_STATE_MODE,
                                    watermark_ts=watermark,
                                )
                                db.add(state)
                            else:
                                state.watermark_ts = watermark
                            db.commit()
                            intervals = []
                            backlog = False
                        else:
                            # Confirmed coverage before the first gap is
                            # already materialized; start retry at that gap.
                            watermark = max(watermark, missing_intervals[0][0])

                            budget = max(1, settings.ingestion_tag_budget_minutes)
                            pending = _split_intervals(missing_intervals, max_intervals=budget + 1)
                            intervals = pending[:budget]
                            backlog = len(pending) > len(intervals)
                else:
                    intervals = [(manual_start, end)]
                    backlog = False

                if not intervals:
                    return TagReloadResult(
                        source["pi_server"], source["tag_name"],
                        "COMPLETE",
                        end=watermark if incremental else end,
                    )
                first_start = intervals[0][0]
                seed_start = intervals[0][0] if not incremental else None
                samples, completed_intervals, seeded, event_calls, seed_calls, resolve_calls, completed_until = await _fetch_target(
                    provider, source, intervals, settings.ingestion_recorded_max_points,
                    seed_start=seed_start, local=local,
                    page_budget=settings.ingestion_tag_request_budget if incremental else 1024,
                    metrics=metrics, initial_watermark=watermark if incremental else None,
                    coverage_end=end, incremental=incremental,
                )
                duration_ms = (time.perf_counter() - started) * 1000
                caught_up = not backlog and completed_intervals == len(intervals)
                status = "COMPLETE" if caught_up else "CATCHING_UP"
                result = TagReloadResult(
                    source["pi_server"], source["tag_name"], status, samples, seeded,
                    pi_calls=event_calls + seed_calls + resolve_calls,
                    event_calls=event_calls, seed_calls=seed_calls, resolve_calls=resolve_calls,
                    duration_ms=duration_ms, start=intervals[0][0], end=completed_until or intervals[0][0],
                )
            except asyncio.CancelledError:
                try:
                    with SessionLocal() as db:
                        local = _local_tag(db, source["pi_server"], source["tag_name"])
                        if local:
                            tag_id = int(local["id"])
                            state = db.get(PiIngestionState, (tag_id, NORM_LIMIT_STATE_MODE))
                            if state is not None:
                                state.consecutive_failures = (state.consecutive_failures or 0) + 1
                                state.last_error_code = "CancelledError"
                                state.last_error_message = "CancelledError"
                                state.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=30)
                                db.commit()
                except Exception as db_exc:
                    logger.warning("Failed to record cancellation state (%s)", type(db_exc).__name__)
                raise
            except Exception as exc:  # one bad point must not abort its peers
                try:
                    with SessionLocal() as db:
                        local = _local_tag(db, source["pi_server"], source["tag_name"])
                        if local:
                            tag_id = int(local["id"])
                            state = db.get(PiIngestionState, (tag_id, NORM_LIMIT_STATE_MODE))
                            if state is not None:
                                state.consecutive_failures = (state.consecutive_failures or 0) + 1
                                state.last_error_code = type(exc).__name__[:255]
                                state.last_error_message = type(exc).__name__
                                state.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=30)
                                db.commit()
                except Exception as db_exc:
                    logger.warning("Failed to record reload failure state (%s)", type(db_exc).__name__)
                result = TagReloadResult(
                    source["pi_server"], source["tag_name"], "FAILED",
                    error=type(exc).__name__,
                    pi_calls=sum(metrics.values()), event_calls=metrics["event_calls"],
                    seed_calls=metrics["seed_calls"], resolve_calls=metrics["resolve_calls"],
                    duration_ms=(time.perf_counter() - started) * 1000,
                    start=first_start, end=end,
                )
            logger.info(
                "norm_limit_reload_tag mode=%s server=%s tag=%s status=%s samples=%d seed=%s "
                "pi_calls=%d event_calls=%d seed_calls=%d resolve_calls=%d duration_ms=%.1f error=%s",
                mode, result.server, result.tag_name, result.status, result.samples, result.seeded,
                result.pi_calls, result.event_calls, result.seed_calls, result.resolve_calls,
                result.duration_ms, result.error or "",
            )
            return result

    results = await asyncio.gather(*(run_one(source) for source in targets))
    logger.info(
        "norm_limit_reload_cycle_complete mode=%s tags=%d complete=%d skipped=%d failed=%d "
        "catching_up=%d samples=%d pi_calls=%d duration_ms=%.1f",
        mode, len(results), sum(row.status == "COMPLETE" for row in results),
        sum(row.status == "SKIPPED" for row in results), sum(row.status == "FAILED" for row in results),
        sum(row.status == "CATCHING_UP" for row in results),
        sum(row.samples for row in results), sum(row.pi_calls for row in results),
        (time.perf_counter() - cycle_started) * 1000,
    )
    return results


async def reload_norm_limits(*, provider=None, now: datetime | None = None) -> list[TagReloadResult]:
    """Explicitly materialize the initial seven-day RECORDED history."""
    return await _reload_norm_limits(provider=provider, now=now, incremental=False)


async def reload_norm_limits_incremental(*, provider=None, now: datetime | None = None) -> list[TagReloadResult]:
    """Advance each configured limit's RECORDED cursor in bounded intervals."""
    return await _reload_norm_limits(provider=provider, now=now, incremental=True)
