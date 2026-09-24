"""Supervised, idempotent multimode PI ingestion worker.

Cursor semantics: ``pi_ingestion_state.watermark_ts`` is the end of the last
minute interval proven complete. Live ingestion processes every pending
minute between the watermark and the start of the current UTC minute, in
bounded turns, so a lagging tag catches up gradually without monopolizing
the cycle and without skipping minutes.

Each minute interval is processed in three phases:
  A) short session: read tag, WebId, watermark, state; close session;
  B) no DB session: fetch + paginate RecordedValues over HTTP;
  C) short transaction: upsert events, coverage, watermark; commit.

Two responsibilities after downtime:
  - **Recent-first**: the last completed minute is always ingested first so
    current data appears immediately.
  - **Catch-up**: pending minutes between the watermark and the present are
    recovered in order, with a limited budget, without blocking recent data.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.database.session import SessionLocal
from app.integrations.pi.manager import get_pi_data_provider
from app.models.pi_tag import PiTag
from app.models.postgres import PiIngestionState, PiSample
from app.services.coverage_service import CoverageService

logger = logging.getLogger("workers.ingestion")
LOCK_KEY = 2147483001
MINUTE = timedelta(minutes=1)

# Turn outcomes
COMPLETE = "COMPLETE"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
INCOMPLETE = "INCOMPLETE"
FAILED = "FAILED"


class BudgetExhaustedError(RuntimeError):
    """Fairness budget reached: not an error, the tag is rescheduled."""

class IntervalIncompleteError(RuntimeError):
    """Completeness of the interval cannot be proven."""


@dataclass
class RecordedPage:
    """Raw response of one RecordedValues call, before edge filtering."""
    raw_count: int
    points_in_half_open: list[Any]
    saturated: bool


@dataclass
class FetchStats:
    """Pagination metrics for one tag turn (budget owned by the caller)."""
    pages: int = 0
    splits: int = 0
    raw_events: int = 0
    saturated_pages: int = 0
    stop_reason: str | None = None
    accepted_events: int = 0
    _accepted_ts: set = field(default_factory=set)

    def _accept(self, points: list[Any]) -> None:
        for point in points:
            self._accepted_ts.add(point.timestamp.astimezone(timezone.utc))
        self.accepted_events = len(self._accepted_ts)

    def log(self, tag_id: int, start: datetime, end: datetime) -> None:
        logger.info(
            "ingestion_fetch tag_id=%s interval=[%s,%s) pages=%d splits=%d "
            "raw_events=%d accepted_events=%d saturated=%d stop=%s",
            tag_id, start.isoformat(), end.isoformat(),
            self.pages, self.splits, self.raw_events, self.accepted_events,
            self.saturated_pages, self.stop_reason or COMPLETE,
        )


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


def _as_utc(value: datetime | None) -> datetime | None:
    """Tolerate naive datetimes returned by some drivers (e.g. SQLite tests)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minute_floor(now: datetime) -> datetime:
    """Start of the current UTC minute: the eligible ingest limit."""
    return now.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _pending_intervals(
    now: datetime,
    watermark: datetime | None,
    *,
    max_intervals: int | None = None,
) -> list[tuple[datetime, datetime]]:
    """Semi-open intervals [watermark, current_minute_start), aligned after
    the first partial one.

    A legacy watermark with sub-minute remainder (e.g. 14:27:35.5) yields a
    first partial interval [14:27:35.5, 14:28) followed by aligned minute
    intervals. A watermark ahead of the limit logs an inconsistency and
    yields nothing (no automatic regression).
    """
    limit = _minute_floor(now)
    if watermark is None:
        initial_minutes = max(1, settings.ingestion_no_watermark_minutes)
        start = limit - MINUTE * initial_minutes
        # Aligned individual intervals, not one wide window, so the budget
        # and the per-interval watermark advance keep their meaning.
        out: list[tuple[datetime, datetime]] = []
        cursor = start
        while cursor < limit and (max_intervals is None or len(out) < max_intervals):
            out.append((cursor, min(cursor + MINUTE, limit)))
            cursor += MINUTE
        return out
    start = watermark.astimezone(timezone.utc)
    if start > limit:
        logger.warning(
            "ingestion_watermark_ahead tag watermark=%s limit=%s (sem regressao)",
            start.isoformat(), limit.isoformat(),
        )
        return []
    intervals: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < limit and (max_intervals is None or len(intervals) < max_intervals):
        next_boundary = (cursor + MINUTE).replace(second=0, microsecond=0)
        intervals.append((cursor, min(next_boundary, limit)))
        cursor = min(next_boundary, limit)
    return intervals


def _live_window(now: datetime, watermark: datetime | None, window: timedelta) -> tuple[datetime, datetime]:
    """Minute-aligned semi-open window for a single fetch turn (compat)."""
    live_start = now - window
    if watermark is not None:
        overlap = timedelta(seconds=settings.ingestion_overlap_seconds)
        if watermark >= live_start - overlap:
            live_start = min(live_start, watermark - overlap)
    minute_end = _minute_floor(now)
    minute_start = live_start.replace(second=0, microsecond=0)
    if minute_end <= minute_start:
        return minute_start, minute_start
    return minute_start, minute_end


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


async def _fetch_page(provider: Any, web_id: str, start: datetime, end: datetime, *, max_count: int) -> RecordedPage:
    """One RecordedValues call: saturation is decided on the RAW response,
    before filtering points to the semi-open [start, end)."""
    response = await provider.get_recorded_values(web_id, start, end, max_count=max_count)
    points = list(response.values)
    saturated = len(points) >= max_count
    filtered = [
        point for point in points
        if start <= point.timestamp.astimezone(timezone.utc) < end
    ]
    return RecordedPage(raw_count=len(points), points_in_half_open=filtered, saturated=saturated)


async def _fetch_complete_interval(
    provider: Any,
    web_id: str,
    start: datetime,
    end: datetime,
    *,
    max_count: int,
    stats: FetchStats,
    page_budget: int,
    depth: int = 0,
) -> list[Any]:
    """Fetch a full semi-open interval, splitting saturated pages.

    A page whose RAW count reached ``max_count`` is potentially incomplete,
    so the interval is split in halves. Duplicates at the split boundary are
    collapsed by timestamp. If the minimum splittable interval is still
    saturated, IntervalIncompleteError is raised and the watermark must not
    advance.
    """
    if start >= end:
        return []
    stats.pages += 1
    if stats.pages > page_budget:
        stats.stop_reason = "page_budget"
        raise BudgetExhaustedError("orcamento de paginas excedido para o intervalo")
    page = await _fetch_page(provider, web_id, start, end, max_count=max_count)
    stats.raw_events += page.raw_count
    if not page.saturated:
        stats._accept(page.points_in_half_open)
        return page.points_in_half_open
    stats.saturated_pages += 1
    duration = end - start
    if duration <= timedelta(seconds=1) or depth >= settings.ingestion_page_depth_limit:
        stats.stop_reason = "min_interval_saturated" if duration <= timedelta(seconds=1) else "depth_limit"
        raise IntervalIncompleteError(
            "RecordedValues permanece saturado no menor subintervalo permitido"
        )
    stats.splits += 1
    midpoint = start + duration / 2
    left = await _fetch_complete_interval(
        provider, web_id, start, midpoint, max_count=max_count,
        stats=stats, page_budget=page_budget, depth=depth + 1,
    )
    right = await _fetch_complete_interval(
        provider, web_id, midpoint, end, max_count=max_count,
        stats=stats, page_budget=page_budget, depth=depth + 1,
    )
    merged = {point.timestamp.astimezone(timezone.utc): point for point in left}
    for point in right:
        merged.setdefault(point.timestamp.astimezone(timezone.utc), point)
    stats._accept([merged[ts] for ts in merged])
    return [merged[ts] for ts in sorted(merged)]


def _persist_points(db: Any, tag_id: int, points: list[Any], mode: str) -> None:
    """Idempotent upsert of raw events inside the caller's short transaction."""
    unique = {point.timestamp.astimezone(timezone.utc): point for point in points}
    if not unique:
        return
    records = [_record(tag_id, point, mode) for point in unique.values()]
    insert_factory = pg_insert if db.bind is not None and db.bind.dialect.name == "postgresql" else sqlite_insert
    for offset in range(0, len(records), 500):
        stmt = insert_factory(PiSample).values(records[offset:offset + 500])
        stmt = stmt.on_conflict_do_update(index_elements=["tag_id", "ts", "source_mode"], set_={column: getattr(stmt.excluded, column) for column in (
            "value_type", "value_double", "value_boolean", "value_text", "good", "questionable", "substituted", "source_mode")})
        db.execute(stmt)


def _record_failure(db: Any, tag_id: int, mode: str, now: datetime, code: str, message: str) -> None:
    state = db.get(PiIngestionState, (tag_id, mode))
    if state is None:
        state = PiIngestionState(tag_id=tag_id, source_mode=mode); db.add(state)
    state.consecutive_failures = (state.consecutive_failures or 0) + 1
    state.last_error_code = _safe_error(code, 255)
    state.last_error_message = _safe_error(message)
    state.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(state.consecutive_failures, 8)))
    db.commit()


async def _ingest_tag(
    tag_id: int,
    now: datetime,
    source_mode: str | None = None,
    *,
    provider: Any = None,
) -> tuple[int, int]:
    """One bounded turn for one tag (phases A/B/C).

    Phase A reads tag + watermark in a short session and closes it. Phase B
    performs HTTP pagination with NO open DB session. Phase C persists each
    completed minute (upsert + coverage + watermark) in its own short
    transaction. Exceeding the fairness budget raises BudgetExhaustedError,
    which is NOT a failure: earlier minutes stay committed and the tag is
    simply rescheduled for the next cycle.
    """
    # Phase A: short session, then close before any HTTP call.
    with SessionLocal() as db:
        tag = db.get(PiTag, tag_id)
        if tag is None or not tag.active:
            return 0, 0
        web_id = tag.pi_web_id
        modes = tuple(item for item in _modes_for(tag) if source_mode is None or item[0] == source_mode)
        due = []
        for mode, interval, interval_seconds in modes:
            state = db.get(PiIngestionState, (tag.id, mode))
            if state and state.next_attempt_at and _as_utc(state.next_attempt_at) > now:
                continue
            watermark = _as_utc(state.watermark_ts) if state and state.watermark_ts else None
            due.append((mode, interval, interval_seconds, watermark))
    if not due:
        return 0, 0
    if provider is None:
        provider = get_pi_data_provider()
    if provider is None or not web_id:
        # Fail explicitly with a short session, without HTTP attempts.
        with SessionLocal() as db:
            _record_failure(db, tag_id, due[0][0], now, "PI_NOT_CONFIGURED", "Provider ou WebId indisponivel")
        return 0, 0

    total_points = 0
    requests = 0
    for mode, interval, interval_seconds, watermark in due:
        intervals = _pending_intervals(
            now, watermark,
            max_intervals=settings.ingestion_tag_budget_minutes,
        )
        if not intervals:
            continue
        stats = FetchStats()
        completed_until: datetime | None = None
        outcome = COMPLETE
        for start, end in intervals:
            try:
                points = await _fetch_complete_interval(  # Phase B: no session
                    provider, web_id, start, end,
                    max_count=settings.ingestion_recorded_max_points,
                    stats=stats,
                    page_budget=settings.ingestion_tag_request_budget,
                )
            except BudgetExhaustedError:
                outcome = BUDGET_EXHAUSTED
                break
            except IntervalIncompleteError as exc:
                stats.stop_reason = stats.stop_reason or "incomplete"
                with SessionLocal() as db:  # Phase C: failure, backoff, no watermark advance
                    _record_failure(db, tag_id, mode, now, "INTERVAL_INCOMPLETE", _safe_error(exc))
                stats.log(tag_id, start, end)
                raise
            except Exception as exc:
                stats.stop_reason = stats.stop_reason or "error"
                with SessionLocal() as db:
                    _record_failure(db, tag_id, mode, now, "PI_ERROR", _safe_error(exc))
                stats.log(tag_id, start, end)
                raise
            # Phase C: short transaction: upsert + coverage + watermark.
            with SessionLocal() as tx:
                _persist_points(tx, tag_id, points, mode)
                CoverageService.record_coverage(
                    tx, tag_id, start, end, mode, interval_seconds,
                    status="COMPLETE" if points else "EMPTY_CONFIRMED",
                    pi_web_id=web_id,
                )
                tx_state = tx.get(PiIngestionState, (tag_id, mode))
                if tx_state is None:
                    tx_state = PiIngestionState(tag_id=tag_id, source_mode=mode); tx.add(tx_state)
                watermark_ts, last_source_ts = _state_timestamps(
                    points, end, tx_state.last_source_ts,
                )
                current_wm = _as_utc(tx_state.watermark_ts) if tx_state.watermark_ts is not None else None
                new_wm = _as_utc(watermark_ts) if watermark_ts is not None else None
                if current_wm is None or (new_wm is not None and new_wm > current_wm):
                    tx_state.watermark_ts = watermark_ts
                cur_last = _as_utc(tx_state.last_source_ts) if tx_state.last_source_ts is not None else None
                new_last = _as_utc(last_source_ts) if last_source_ts is not None else None
                if cur_last is None or (new_last is not None and new_last > cur_last):
                    tx_state.last_source_ts = last_source_ts
                tx_state.last_success_at = now
                tx_state.consecutive_failures = 0
                tx_state.last_error_code = None
                tx_state.last_error_message = None
                tx_state.next_attempt_at = None
                tx.commit()
            total_points += len(points); requests += 1
            completed_until = end
        if outcome == BUDGET_EXHAUSTED:
            # Fairness reschedule: not a failure, minutes already committed
            # stay committed, watermark of the incomplete minute is not
            # advanced; the tag remains eligible for the next cycle.
            logger.info(
                "ingestion_budget_exhausted tag_id=%s completed_until=%s pages=%d",
                tag_id, completed_until.isoformat() if completed_until else None, stats.pages,
            )
        stats.log(tag_id, intervals[0][0], intervals[-1][1])
    return total_points, requests


async def _ingest_recent_minute(
    tag_ids: set[int],
    now: datetime,
    *,
    provider: Any = None,
) -> int:
    """Ingest only the most recent completed minute for all tags.

    This ensures current data appears immediately after a restart, before
    the catch-up backlog is processed.
    """
    limit = _minute_floor(now)
    recent_start = limit - MINUTE
    semaphore = asyncio.Semaphore(settings.ingestion_tag_concurrency)
    total = 0

    async def _one(tag_id: int) -> int:
        async with semaphore:
            # Check if this minute already has coverage or tag is in backoff.
            with SessionLocal() as db:
                tag = db.get(PiTag, tag_id)
                if tag is None or not tag.active or not tag.pi_web_id:
                    return 0
                state = db.get(PiIngestionState, (tag_id, "RECORDED"))
                if state and state.next_attempt_at and _as_utc(state.next_attempt_at) > now:
                    return 0  # Tag in backoff; do not query PI
                wm = _as_utc(state.watermark_ts) if state and state.watermark_ts else None
                if wm is not None and wm >= limit:
                    return 0  # Already covered.
            try:
                p = provider or get_pi_data_provider()
                if p is None:
                    return 0
                with SessionLocal() as db:
                    tag = db.get(PiTag, tag_id)
                    if tag is None or not tag.pi_web_id:
                        return 0
                    web_id = tag.pi_web_id

                stats = FetchStats()
                task = asyncio.create_task(
                    _fetch_complete_interval(
                        p, web_id, recent_start, limit,
                        max_count=settings.ingestion_recorded_max_points,
                        stats=stats,
                        page_budget=settings.ingestion_tag_request_budget,
                    )
                )
                try:
                    points = await asyncio.wait_for(
                        task,
                        timeout=settings.ingestion_tag_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    with SessionLocal() as fdb:
                        _record_failure(fdb, tag_id, "RECORDED", now, "TAG_TIMEOUT",
                                        "Turno de minuto recente excedeu o timeout de ingestao")
                    logger.warning("recent_minute_timeout tag_id=%s timeout=%.1fs", tag_id, settings.ingestion_tag_timeout_seconds)
                    return 0
                # Persist with coverage but do NOT advance contiguous watermark
                # over gaps. Instead we record the coverage separately and let
                # the catch-up merge it.
                with SessionLocal() as tx:
                    _persist_points(tx, tag_id, points, "RECORDED")
                    CoverageService.record_coverage(
                        tx, tag_id, recent_start, limit, "RECORDED", None,
                        pi_web_id=web_id,
                    )
                    # Only advance watermark if it's contiguous.
                    tx_state = tx.get(PiIngestionState, (tag_id, "RECORDED"))
                    if tx_state is None:
                        tx_state = PiIngestionState(tag_id=tag_id, source_mode="RECORDED")
                        tx.add(tx_state)
                    existing_wm = _as_utc(tx_state.watermark_ts)
                    if existing_wm is not None and existing_wm >= recent_start:
                        if limit > existing_wm:
                            tx_state.watermark_ts = limit
                    elif existing_wm is None:
                        tx_state.watermark_ts = limit
                    tx_state.last_success_at = now
                    tx_state.consecutive_failures = 0
                    tx_state.last_error_code = None
                    tx_state.last_error_message = None
                    tx_state.next_attempt_at = None
                    tx.commit()
                return len(points)
            except (BudgetExhaustedError, IntervalIncompleteError):
                return 0
            except Exception:
                logger.debug("recent_minute_failed tag_id=%s", tag_id, exc_info=True)
                return 0

    results = await asyncio.gather(*(_one(tid) for tid in sorted(tag_ids)), return_exceptions=True)
    for r in results:
        if isinstance(r, int):
            total += r
    return total


async def _reconcile_recent(
    tag_ids: set[int],
    now: datetime,
    *,
    provider: Any = None,
) -> int:
    """Re-ingest the last N completed minutes to capture late-arriving events.

    The UPSERT makes this idempotent; events already persisted are updated
    in place rather than duplicated.
    """
    recon_minutes = settings.ingestion_reconciliation_minutes
    if recon_minutes <= 0:
        return 0
    limit = _minute_floor(now)
    semaphore = asyncio.Semaphore(settings.ingestion_tag_concurrency)
    total = 0

    async def _one(tag_id: int) -> int:
        async with semaphore:
            with SessionLocal() as db:
                tag = db.get(PiTag, tag_id)
                if tag is None or not tag.active or not tag.pi_web_id:
                    return 0
                state = db.get(PiIngestionState, (tag_id, "RECORDED"))
                if state and state.next_attempt_at and _as_utc(state.next_attempt_at) > now:
                    return 0  # Tag in backoff; do not reconcile
                web_id = tag.pi_web_id
            p = provider or get_pi_data_provider()
            if p is None:
                return 0
            subtotal = 0
            for offset in range(recon_minutes, 0, -1):
                interval_start = limit - MINUTE * offset
                interval_end = interval_start + MINUTE
                try:
                    stats = FetchStats()
                    task = asyncio.create_task(
                        _fetch_complete_interval(
                            p, web_id, interval_start, interval_end,
                            max_count=settings.ingestion_recorded_max_points,
                            stats=stats,
                            page_budget=settings.ingestion_tag_request_budget,
                        )
                    )
                    points = await asyncio.wait_for(
                        task,
                        timeout=settings.ingestion_tag_timeout_seconds,
                    )
                    if points:
                        with SessionLocal() as tx:
                            _persist_points(tx, tag_id, points, "RECORDED")
                            CoverageService.record_coverage(
                                tx, tag_id, interval_start, interval_end,
                                "RECORDED", None, pi_web_id=web_id,
                            )
                            tx.commit()
                        subtotal += len(points)
                except asyncio.TimeoutError:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    with SessionLocal() as fdb:
                        _record_failure(fdb, tag_id, "RECORDED", now, "TAG_TIMEOUT",
                                        "Turno de reconciliacao excedeu o timeout de ingestao")
                    logger.warning("reconcile_minute_timeout tag_id=%s timeout=%.1fs", tag_id, settings.ingestion_tag_timeout_seconds)
                    break
                except Exception:
                    logger.debug(
                        "reconcile_minute_failed tag_id=%s minute=%s",
                        tag_id, interval_start.isoformat(), exc_info=True,
                    )
            return subtotal

    results = await asyncio.gather(*(_one(tid) for tid in sorted(tag_ids)), return_exceptions=True)
    for r in results:
        if isinstance(r, int):
            total += r
    if total:
        logger.info("reconciliation_completed events=%d tags=%d minutes=%d", total, len(tag_ids), recon_minutes)
    return total


async def run_ingestion_loop(
    interval_seconds: float = 10.0,
    *,
    once: bool = False,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run cycles with bounded tag concurrency and per-tag isolation.

    Tags run as independent asyncio tasks capped by
    ``ingestion_tag_concurrency``; each task is bounded by the per-tag total
    timeout ``ingestion_tag_timeout_seconds``. On timeout the task is
    cancelled and awaited, and a TAG_TIMEOUT failure with backoff is
    persisted in a dedicated short session; other tags are unaffected.
    The Recorded cadence advances after each minute-cycle regardless of
    individual tag failures: per-tag retries are governed by
    ``next_attempt_at``, not by the global cadence.

    After downtime, the cycle:
      1. Ingests the most recent completed minute first (recent-first).
      2. Reconciles configurable recent minutes for late-arriving events.
      3. Processes catch-up from the watermark forward (bounded budget).
    """
    interval_seconds = interval_seconds or settings.ingestion_cycle_seconds
    last_recorded_cycle: datetime | None = None
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        cycle_started = datetime.now(timezone.utc); acquired = False
        recorded_due = (
            last_recorded_cycle is None
            or (cycle_started - last_recorded_cycle).total_seconds()
        )
        raw_lock_conn = None
        acquired = False
        try:
            from app.database.session import engine
            if getattr(engine, "dialect", None) is not None and engine.dialect.name == "postgresql":
                try:
                    raw_lock_conn = engine.raw_connection()
                    cursor = raw_lock_conn.cursor()
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
                    row = cursor.fetchone()
                    acquired = bool(row and row[0])
                    raw_lock_conn.commit()
                    if not acquired:
                        raw_lock_conn.close()
                        raw_lock_conn = None
                except Exception:
                    if raw_lock_conn is not None:
                        try:
                            raw_lock_conn.close()
                        except Exception:
                            pass
                        raw_lock_conn = None
                    acquired = False
            else:
                acquired = True

            if acquired:
                with SessionLocal() as db:
                    tags = db.execute(select(PiTag).where(PiTag.active.is_(True))).scalars().all()
                    tag_ids = {tag.id for tag in tags}
                    for tag in tags:
                        tag_ids.update(filter(None, (tag.lower_limit_tag_id, tag.upper_limit_tag_id)))
                # Session is closed: all HTTP calls happen with NO open DB session.

                if recorded_due and tag_ids:
                    # Step 1: Recent-first — ingest the last completed
                    # minute so current data appears immediately.
                    recent_points = await _ingest_recent_minute(
                        tag_ids, cycle_started,
                    )
                    if recent_points:
                        logger.info(
                            "recent_first_completed events=%d tags=%d",
                            recent_points, len(tag_ids),
                        )

                    # Step 2: Reconciliation — re-query last N minutes
                    # for late-arriving events (idempotent via UPSERT).
                    if settings.ingestion_reconciliation_minutes > 0:
                        await _reconcile_recent(tag_ids, cycle_started)

                # Step 3: Catch-up / normal ingestion from watermark.
                selected_mode = None if recorded_due else "__INTERPOLATED_ONLY__"
                semaphore = asyncio.Semaphore(settings.ingestion_tag_concurrency)
                total_points = 0
                tag_timeouts = 0

                async def run_one(tag_id: int) -> None:
                    nonlocal total_points, tag_timeouts
                    async with semaphore:
                        task = asyncio.create_task(
                            _ingest_tag(tag_id, cycle_started, source_mode=selected_mode)
                        )
                        try:
                            points, _ = await asyncio.wait_for(
                                task, timeout=settings.ingestion_tag_timeout_seconds,
                            )
                            total_points += points
                        except asyncio.TimeoutError:
                            tag_timeouts += 1
                            task.cancel()
                            try:
                                await task  # let cancellation settle; CancelledError is not success
                            except (asyncio.CancelledError, Exception):
                                pass
                            # Dedicated short session: TAG_TIMEOUT failure
                            # with backoff; watermark is not touched here.
                            with SessionLocal() as fdb:
                                _record_failure(fdb, tag_id, "RECORDED", cycle_started, "TAG_TIMEOUT",
                                                "Turno excedeu o timeout total de ingestao")
                            logger.error("ingestion_tag_timeout tag_id=%s timeout_seconds=%.0f",
                                         tag_id, settings.ingestion_tag_timeout_seconds)
                        except asyncio.CancelledError:
                            raise
                        except BudgetExhaustedError:
                            # Fairness reschedule, not a failure.
                            logger.info("ingestion_tag_rescheduled tag_id=%s", tag_id)
                        except Exception as exc:
                            # Per-tag failure already persisted inside
                            # _ingest_tag; other tags keep running.
                            logger.exception("ingestion_tag_failed tag_id=%s error=%s", tag_id, _safe_error(exc))

                if tag_ids:
                    await asyncio.gather(*(run_one(tag_id) for tag_id in sorted(tag_ids)))
                logger.info("ingestion_cycle_completed duration_ms=%d points_written=%d tag_count=%d tag_timeouts=%d",
                            int((datetime.now(timezone.utc) - cycle_started).total_seconds() * 1000),
                            total_points, len(tag_ids), tag_timeouts)
                # The one-minute Recorded cadence advances on every
                # executed cycle; individual tag retries are governed by
                # each tag's next_attempt_at and pending watermark.
                if recorded_due:
                    last_recorded_cycle = cycle_started
        except Exception:
            if once: raise
            logger.exception("ingestion_cycle_failed")
        finally:
            if raw_lock_conn is not None:
                try:
                    cursor = raw_lock_conn.cursor()
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
                    raw_lock_conn.commit()
                except Exception:
                    pass
                finally:
                    try:
                        raw_lock_conn.close()
                    except Exception:
                        pass
        if once: return
        elapsed = (datetime.now(timezone.utc) - cycle_started).total_seconds()
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, interval_seconds - elapsed))
                break
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(max(0.0, interval_seconds - elapsed))
