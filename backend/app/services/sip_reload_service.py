"""Durable SIP reload jobs; Oracle is read-only, TimescaleDB stores samples."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import SipCoverage, SipReloadJob, SipSample, SipSource
from app.services.sip_oracle_service import SipOracleService, period_sql


def fingerprint(source: SipSource) -> str:
    value = "\0".join(("sip-period-lookback-v2", source.sql_text, source.timestamp_column, source.value_column))
    return hashlib.sha256(value.encode()).hexdigest()


def normalized(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def has_coverage(db: Session, source: SipSource, start: datetime, end: datetime) -> bool:
    cursor = normalized(start)
    for interval in db.scalars(select(SipCoverage).where(
        SipCoverage.source_id == source.id,
        SipCoverage.query_fingerprint == fingerprint(source),
        SipCoverage.end_time > start,
        SipCoverage.start_time < end,
    ).order_by(SipCoverage.start_time)).all():
        if normalized(interval.start_time) > cursor:
            return False
        cursor = max(cursor, normalized(interval.end_time))
        if cursor >= normalized(end):
            return True
    return False


def enqueue(db: Session, source_id: int, start: datetime, end: datetime) -> SipReloadJob:
    source = db.get(SipSource, source_id)
    if source is None or not source.active:
        raise NotFoundError("Consulta SIP temporal não encontrada.")
    start, end = normalized(start), normalized(end)
    if start >= end or end - start > timedelta(days=366) or end > datetime.now(timezone.utc) + timedelta(minutes=1):
        raise ValidationError("Escolha um período válido de até um ano.")
    job = SipReloadJob(source_id=source_id, target_start=start, target_end=end,
                       next_start=start, status="PENDING", progress_percent=0, rows_written=0)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fetch_complete(source: SipSource, start: datetime, end: datetime, depth: int = 0):
    rows, truncated = SipOracleService().fetch_rows(period_sql(source.sql_text), source.timestamp_column,
                                                    source.value_column, start, end)
    if not truncated:
        return rows
    if depth >= 24 or end - start <= timedelta(seconds=1):
        raise ValidationError("A consulta SIP excedeu o limite de linhas por segundo; reduza o período ou agregue o SQL.")
    middle = start + (end - start) / 2
    return _fetch_complete(source, start, middle, depth + 1) + _fetch_complete(source, middle, end, depth + 1)


def process_next(db: Session) -> bool:
    job = db.scalars(select(SipReloadJob).where(SipReloadJob.status.in_(("PENDING", "RUNNING"))).order_by(SipReloadJob.id)).first()
    if job is None:
        return False
    source = db.get(SipSource, job.source_id)
    if source is None:
        job.status, job.error_message = "FAILED", "Consulta SIP removida."
        db.commit()
        return True
    start = normalized(job.next_start)
    end = min(start + timedelta(hours=6), normalized(job.target_end))
    if start >= end:
        job.status, job.progress_percent = "COMPLETED", 100
        db.commit()
        return True
    job.status = "RUNNING"
    db.commit()
    try:
        source_fingerprint = fingerprint(source)
        rows = _fetch_complete(source, start, end)
        # The source may have been edited while Oracle was executing.
        db.refresh(job)
        db.refresh(source)
        if job.status == "CANCELLED":
            return True
        if fingerprint(source) != source_fingerprint:
            raise ValidationError("A consulta SIP mudou durante a recarga; inicie uma nova recarga.")
        query_hash = source_fingerprint
        now = datetime.now(timezone.utc)
        # Replace the complete chunk, including timestamps absent from the new query.
        db.execute(delete(SipSample).where(SipSample.source_id == source.id,
            SipSample.ts >= start, SipSample.ts < end))
        batch = {}
        for ts, value in rows:
            batch[ts] = {
                "source_id": source.id, "ts": ts,
                "value_double": float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                "value_boolean": value if isinstance(value, bool) else None,
                "value_text": value if isinstance(value, str) else None,
                "ingested_at": now,
            }
        if batch:
            db.execute(SipSample.__table__.insert(), list(batch.values()))
        coverage = db.get(SipCoverage, (source.id, start))
        if coverage is None:
            coverage = SipCoverage(source_id=source.id, start_time=start, end_time=end, query_fingerprint=query_hash)
            db.add(coverage)
        else:
            coverage.end_time, coverage.query_fingerprint = end, query_hash
        job.next_start = end
        job.rows_written += len(batch)
        job.progress_percent = 100 * (end - normalized(job.target_start)) / (normalized(job.target_end) - normalized(job.target_start))
        if end >= normalized(job.target_end):
            job.status, job.progress_percent = "COMPLETED", 100
        db.commit()
    except Exception as exc:
        db.rollback()
        failed = db.get(SipReloadJob, job.id)
        if failed and failed.status != "CANCELLED":
            failed.status, failed.error_message = "FAILED", str(exc)[:1000]
            db.commit()
    return True


def stored_rows(db: Session, source_id: int, start: datetime, end: datetime, max_rows: int | None = None):
    query = select(SipSample).where(SipSample.source_id == source_id,
        SipSample.ts >= start, SipSample.ts < end)
    query = query.order_by(SipSample.ts.desc()).limit(max_rows) if max_rows else query.order_by(SipSample.ts)
    samples = db.scalars(query).all()
    if max_rows:
        samples.reverse()
    return [(normalized(item.ts), item.value_text if item.value_text is not None else
             item.value_boolean if item.value_boolean is not None else item.value_double) for item in samples]
