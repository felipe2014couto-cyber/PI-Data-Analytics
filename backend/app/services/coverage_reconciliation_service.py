"""Surgical reconciliation of one evidenced coverage interval."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.postgres import PiIngestionCoverage


@dataclass(frozen=True)
class CoverageReconciliation:
    tag_id: int
    start: datetime
    end: datetime
    raw_count: int
    pi_count: int | None
    action: str
    affected_ids: tuple[int, ...]


def reconcile_recorded_coverage(
    db: Session, *, tag_id: int, start: datetime, end: datetime,
    pi_count: int | None, dry_run: bool = True,
) -> CoverageReconciliation:
    """Invalidate only an explicit interval when PI evidence proves mismatch.

    ``pi_count=None`` is inconclusive and can never mutate coverage.  The
    caller performs the bounded PI request before opening this transaction.
    """
    start = start.astimezone(timezone.utc); end = end.astimezone(timezone.utc)
    if start >= end:
        raise ValueError("start must be before end")
    raw_count = int(db.execute(text("""
        SELECT count(*) FROM pi_samples_timescale
        WHERE tag_id=:tag_id AND source_mode='RECORDED' AND ts>=:start AND ts<:end
    """), {"tag_id": tag_id, "start": start, "end": end}).scalar_one())
    rows = list(db.scalars(select(PiIngestionCoverage).where(
        PiIngestionCoverage.tag_id == tag_id,
        PiIngestionCoverage.mode == "RECORDED",
        PiIngestionCoverage.status.in_(("COMPLETE", "EMPTY_CONFIRMED")),
        PiIngestionCoverage.range_end > start,
        PiIngestionCoverage.range_start < end,
    ).with_for_update()).all())
    ids = tuple(row.id for row in rows)
    if pi_count is None:
        action = "INCONCLUSIVE"
    elif pi_count == raw_count:
        action = "NO_CHANGE"
    elif not rows:
        action = "NO_COVERAGE_TO_INVALIDATE"
    else:
        action = "INVALIDATE_MISMATCH"
    result = CoverageReconciliation(tag_id, start, end, raw_count, pi_count, action, ids)
    if dry_run or action != "INVALIDATE_MISMATCH":
        return result
    for row in rows:
        row_start, row_end = row.range_start, row.range_end
        if row_start < start:
            db.add(PiIngestionCoverage(
                tag_id=tag_id, range_start=row_start, range_end=start,
                mode=row.mode, interval_seconds=row.interval_seconds,
                status=row.status, pi_web_id=row.pi_web_id,
            ))
        if row_end > end:
            db.add(PiIngestionCoverage(
                tag_id=tag_id, range_start=end, range_end=row_end,
                mode=row.mode, interval_seconds=row.interval_seconds,
                status=row.status, pi_web_id=row.pi_web_id,
            ))
        row.range_start = max(row_start, start)
        row.range_end = min(row_end, end)
        row.status = "INVALIDATED"
    return result
