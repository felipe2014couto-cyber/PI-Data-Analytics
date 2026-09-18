"""Controlled PI Web API vs TimescaleDB comparison for Recorded ingestion.

Usage (from backend/, with staging .env loaded):
    .venv/bin/python ops/compare_pi_vs_timescaledb.py --tag-ids 1 2 3 \
        --start 2026-09-17T14:00:00+00:00 --minutes 10

For each completed minute [m, m+1) it compares, per tag:
  - total events, timestamps, values, quality flags
  - boundary events between minutes
  - duplicates / missing / extra rows in the local DB
  - timestamp precision (decimal digits in raw ISO strings)

Prints a per-minute verdict plus a summary. No credentials, tokens or
headers are ever printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.integrations.pi.manager import get_pi_data_provider
from app.models.pi_tag import PiTag


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def fetch_pi_minute(provider: Any, web_id: str, start: datetime, end: datetime, max_count: int):
    response = await provider.get_recorded_values(web_id, start, end, max_count=max_count)
    points = []
    for p in response.values:
        ts = p.timestamp.astimezone(timezone.utc)
        if start <= ts < end:  # semi-open [start, end)
            points.append((ts, p.value, bool(p.good), bool(p.questionable), bool(p.substituted)))
    return points


def fetch_db_minute(tag_id: int, start: datetime, end: datetime) -> list[tuple]:
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT ts, value_double, value_boolean, value_text, value_type, "
            "good, questionable, substituted "
            "FROM pi_samples_timescale "
            "WHERE tag_id = :t AND source_mode = 'RECORDED' "
            "AND ts >= :s AND ts < :e ORDER BY ts ASC"
        ), {"t": tag_id, "s": start, "e": end}).fetchall()
    return [(_utc(r[0]), _value(r), bool(r[5]), bool(r[6]), bool(r[7])) for r in rows]


def _utc(ts) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _value(row) -> Any:
    if row[4] == "double" and row[1] is not None:
        return float(row[1])
    if row[4] == "boolean" and row[2] is not None:
        return bool(row[2])
    return row[3]


def compare_minute(tag_id: int, pi: list, db: list, minute: datetime) -> dict:
    pi_by_ts = {t[0]: t[1:] for t in pi}
    db_by_ts = {t[0]: t[1:] for t in db}
    dup_pi = [t for t, c in Counter(t[0] for t in pi).items() if c > 1]
    dup_db = [t for t, c in Counter(t[0] for t in db).items() if c > 1]
    mismatches = [
        {"ts": _fmt(t), "pi": str(pi_by_ts.get(t)), "db": str(db_by_ts.get(t))}
        for t in sorted(set(pi_by_ts) | set(db_by_ts))
        if pi_by_ts.get(t) != db_by_ts.get(t)
    ]
    return {
        "tag_id": tag_id,
        "minute": _fmt(minute),
        "pi_count": len(pi),
        "db_count": len(db),
        "missing_in_db": [_fmt(t) for t in sorted(set(pi_by_ts) - set(db_by_ts))],
        "extra_in_db": [_fmt(t) for t in sorted(set(db_by_ts) - set(pi_by_ts))],
        "value_or_quality_mismatches": mismatches,
        "pi_duplicates": [_fmt(t) for t in dup_pi],
        "db_duplicates": [_fmt(t) for t in dup_db],
        "equal": (pi_count := len(pi)) == len(db) and not mismatches
                 and not dup_pi and not dup_db,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag-ids", type=int, nargs="+", required=True)
    parser.add_argument("--start", required=True, help="ISO 8601 minute start (UTC)")
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--max-count", type=int,
                        default=get_settings().ingestion_recorded_max_points)
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start).astimezone(timezone.utc)
    provider = get_pi_data_provider()
    settings = get_settings()
    with SessionLocal() as db:
        tags = {t.id: t for t in db.query(PiTag).filter(PiTag.id.in_(args.tag_ids)).all()}

    print(json.dumps({"pi_base_url": settings.pi_web_api_base_url,  # host only, no creds
                      "tags": {tid: tags[tid].pi_tag_name for tid in args.tag_ids if tid in tags},
                      "window": [start.isoformat(), (start + timedelta(minutes=args.minutes)).isoformat()],
                      "mode": "RECORDED semi-open [m, m+1)"}))

    report: list[dict] = []
    precision_samples: list[dict] = []
    for i in range(args.minutes):
        minute = start + timedelta(minutes=i)
        end = minute + timedelta(minutes=1)
        for tag_id in args.tag_ids:
            tag = tags.get(tag_id)
            if tag is None or not tag.pi_web_id:
                report.append({"tag_id": tag_id, "minute": _fmt(minute), "error": "tag sem WebId"})
                continue
            try:
                pi = await fetch_pi_minute(provider, tag.pi_web_id, minute, end, args.max_count)
            except Exception as exc:
                report.append({"tag_id": tag_id, "minute": _fmt(minute),
                               "error": type(exc).__name__})
                continue
            db_rows = fetch_db_minute(tag_id, minute, end)
            report.append(compare_minute(tag_id, pi, db_rows, minute))
            for ts, *_ in pi[:5]:
                iso = ts.isoformat()
                if "." in iso:
                    digits = len(iso.split(".")[1].rstrip("0+"))
                    precision_samples.append({"raw_decimals": digits, "ts": iso})

    equal = sum(1 for r in report if r.get("equal"))
    errors = sum(1 for r in report if r.get("error"))
    print(json.dumps({"summary": {"minutes": args.minutes, "tags": len(args.tag_ids),
                                  "checks": len(report), "equal": equal,
                                  "divergent": len(report) - equal - errors,
                                  "errors": errors},
                      "precision": precision_samples[:20],
                      "divergences": [r for r in report if not r.get("equal") and not r.get("error")],
                      "errors_detail": [r for r in report if r.get("error")]},
                     indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())