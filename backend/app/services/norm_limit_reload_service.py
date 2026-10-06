"""Materialize active visual norm-limit PI RECORDED events locally."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.database.session import SessionLocal
from app.integrations.pi.manager import get_pi_data_provider
from app.services.coverage_service import CoverageService

logger = logging.getLogger("workers.norm_limits")


@dataclass(frozen=True)
class TagReloadResult:
    server: str
    tag_name: str
    status: str
    samples: int = 0
    seeded: bool = False
    error: str | None = None


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


async def _fetch_target(provider, source, start: datetime, end: datetime, max_count: int) -> tuple[int | None, list, bool]:
    server, name = source["pi_server"], source["tag_name"]
    with SessionLocal() as db:
        local = _local_tag(db, server, name)
        db.rollback()
    point = None
    if local is None or not local["pi_web_id"]:
        point = await provider.resolve_point(f"\\\\{server}\\{name.lstrip('\\\\')}")
        if point is None:
            raise LookupError(f"Tag PI {name!r} nao encontrada no servidor {server!r}.")
        web_id = point.web_id
    else:
        web_id = local["pi_web_id"]

    # PI boundaryType=Outside returns the preceding RECORDED event. Keep only
    # events strictly before the rolling window as the seed.
    boundary = await provider.get_recorded_values_boundary(
        web_id, start, start + timedelta(microseconds=1),
        boundary_type="Outside", max_count=2,
    )
    seeds = [p for p in boundary.values if p.timestamp.astimezone(timezone.utc) < start]
    seed = max(seeds, key=lambda p: p.timestamp) if seeds else None

    from app.workers.ingestion_worker import FetchStats, _fetch_complete_interval
    stats = FetchStats()
    points = await _fetch_complete_interval(
        provider, web_id, start, end, max_count=max_count,
        stats=stats, page_budget=1024,
    )
    if seed is not None:
        points = [seed, *points]

    with SessionLocal() as db:
        local = _local_tag(db, server, name)
        if local is None:
            tag_id = _register_dependency(db, source, name, web_id)
        else:
            tag_id = int(local["id"])
            if not local["pi_web_id"]:
                db.execute(text("UPDATE pi_tags SET pi_web_id=:web_id WHERE id=:id"), {"web_id": web_id, "id": tag_id})
        from app.workers.ingestion_worker import _persist_points
        _persist_points(db, tag_id, points, "RECORDED")
        CoverageService.record_coverage(
            db, tag_id, start, end, "RECORDED",
            status="COMPLETE" if points or seed else "EMPTY_CONFIRMED",
            pi_web_id=web_id,
        )
        db.commit()
    return tag_id, points, seed is not None


async def reload_norm_limits(*, provider=None, now: datetime | None = None) -> list[TagReloadResult]:
    """Run one isolated, idempotent 7-day reload for configured limit tags."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start, end = now - timedelta(days=7), now
    with SessionLocal() as db:
        targets = _configured_limit_refs(db)
        db.rollback()
    logger.info("norm_limit_reload_started tags=%d start=%s end=%s", len(targets), start.isoformat(), end.isoformat())
    if not targets:
        return []
    provider = provider or get_pi_data_provider()
    if provider is None:
        return [TagReloadResult(target["pi_server"], target["tag_name"], "FAILED",
                                error="PI Web API nao configurada") for target in targets]

    semaphore = asyncio.Semaphore(max(1, min(settings.pi_query_concurrency, 8)))

    async def run_one(source):
        async with semaphore:
            try:
                _, points, seeded = await _fetch_target(
                    provider, source, start, end, settings.ingestion_recorded_max_points,
                )
                result = TagReloadResult(source["pi_server"], source["tag_name"], "COMPLETE", len(points), seeded)
            except Exception as exc:  # one bad point must not abort its peers
                result = TagReloadResult(source["pi_server"], source["tag_name"], "FAILED", error=f"{type(exc).__name__}: {exc}"[:500])
            logger.info("norm_limit_reload_tag server=%s tag=%s status=%s samples=%d seed=%s error=%s",
                        result.server, result.tag_name, result.status, result.samples, result.seeded, result.error or "")
            return result

    return await asyncio.gather(*(run_one(source) for source in targets))
