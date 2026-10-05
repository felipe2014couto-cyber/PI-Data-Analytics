"""Bounded materialization of unfiltered, complete UM occurrences.

Coverage changes committed with ingestion/backfill are the invalidation source.
No raw inserts, updates, deletions or filter-result cache are performed here.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from app.models.production_unit import ProductionUnitMaterialization, ProductionUnitStoredSegment, ProductionUnitTagStats
from app.schemas.production_unit import ProductionUnitSegment
from app.models.pi_tag import PiTag

STAT_FIELDS = ("raw_sample_count", "filtered_sample_count", "sample_count", "excluded_quality_count", "average", "minimum", "maximum", "first_timestamp", "last_timestamp", "first_value", "last_value")


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def available(db):
    return isinstance(db, Session) and inspect(db.connection()).has_table("production_unit_materializations")


def versions(db, um_tag_id, tags, start, end):
    ids = [um_tag_id] + [tag.id for tag in tags]
    if db.get_bind().dialect.name == "postgresql":
        rows = db.execute(text("""
            SELECT tag_id, count(*) AS n, max(updated_at) AS modified, max(created_at) AS created
            FROM pi_ingestion_coverage WHERE tag_id = ANY(CAST(:ids AS integer[]))
              AND mode='RECORDED' AND interval_seconds IS NULL
              AND range_start <= :end AND (tag_id=:um OR range_end > :start)
            GROUP BY tag_id
        """), {"ids": ids, "um": um_tag_id, "start": start, "end": end}).mappings().all()
    else:
        from app.models.postgres import PiIngestionCoverage
        from sqlalchemy import func, or_
        query = db.query(PiIngestionCoverage.tag_id.label("tag_id"), func.count().label("n"), func.max(PiIngestionCoverage.updated_at).label("modified"), func.max(PiIngestionCoverage.created_at).label("created")).filter(
            PiIngestionCoverage.tag_id.in_(ids), PiIngestionCoverage.mode == "RECORDED", PiIngestionCoverage.interval_seconds.is_(None), PiIngestionCoverage.range_start <= end,
            or_(PiIngestionCoverage.tag_id == um_tag_id, PiIngestionCoverage.range_end > start)).group_by(PiIngestionCoverage.tag_id)
        rows = db.execute(query.statement).mappings().all()
    types = {tag.id: str(tag.data_type) for tag in tags}
    return {str(row.tag_id if hasattr(row, 'tag_id') else row['tag_id']): hashlib.sha256(json.dumps([str(value) for value in (row['n'], row['modified'], row['created'], types.get(row['tag_id']))]).encode()).hexdigest() for row in rows}


class ProductionUnitStore:
    def __init__(self, db):
        self.db = db

    def load(self, equipment_id, section_id, um_tag, tags, start, end, allow_stats):
        """Return a valid structure plus stats for exact complete occurrences."""
        if not available(self.db):
            return None
        windows = self.db.query(ProductionUnitMaterialization).filter(
            ProductionUnitMaterialization.equipment_id == equipment_id,
            ProductionUnitMaterialization.section_id == section_id,
            ProductionUnitMaterialization.um_tag_id == um_tag.id,
            ProductionUnitMaterialization.start_ts <= start,
            ProductionUnitMaterialization.end_ts >= end,
        ).order_by(ProductionUnitMaterialization.calculated_at.desc()).limit(10).all()
        for window in windows:
            current = versions(self.db, um_tag.id, tags, utc(window.start_ts), utc(window.end_ts))
            if not current.get(str(um_tag.id)) or current[str(um_tag.id)] != window.source_versions.get(str(um_tag.id)):
                continue
            segments = []
            quality_by_bounds = {}
            for data in window.segments:
                segment = ProductionUnitSegment.model_validate(data)
                quality_by_bounds[(segment.start_time, segment.end_time)] = data.get("quality_counts", {})
                left, right = max(segment.start_time, start), min(segment.end_time, end)
                if left >= right:
                    continue
                if left != segment.start_time:
                    segment.start_reason = "QUERY_START"
                if right != segment.end_time:
                    segment.end_reason = "QUERY_END"
                segment.start_time, segment.end_time = left, right
                segment.duration_seconds = (right - left).total_seconds()
                segment.segment_id = f"{um_tag.id}:{left.isoformat()}"
                segments.append(segment)
            cached = []
            if allow_stats:
                records = self.db.query(ProductionUnitStoredSegment, ProductionUnitTagStats).join(ProductionUnitTagStats, ProductionUnitTagStats.segment_id == ProductionUnitStoredSegment.id).filter(
                    ProductionUnitStoredSegment.um_tag_id == um_tag.id,
                    ProductionUnitStoredSegment.start_ts >= start,
                    ProductionUnitStoredSegment.start_ts < end,
                    ProductionUnitTagStats.tag_id.in_([tag.id for tag in tags]),
                ).all()
                by_bounds = {(utc(s.start_ts), utc(s.end_ts), stats.tag_id): stats for s, stats in records if s.end_ts is not None}
                for index, segment in enumerate(segments):
                    for tag in tags:
                        record = by_bounds.get((segment.start_time, segment.end_time, tag.id))
                        signature = current.get(str(tag.id))
                        if record is None or not signature or record.source_version != signature:
                            continue
                        cached.append(dict(segment_index=index, tag_id=tag.id, tag_name=tag.pi_tag_name,
                            display_name=tag.display_name, data_type=tag.data_type.value, unit=tag.engineering_unit,
                            quality_counts=quality_by_bounds.get((segment.start_time, segment.end_time), {}).get(str(tag.id), {}),
                            **{field: getattr(record, field) for field in STAT_FIELDS}))
            return segments, cached
        return None

    def rebuild(self, equipment_id, section_id, tag_ids, start, end):
        """Explicit small-window rebuild. Caller owns transaction/commit."""
        from app.services.production_unit_service import ProductionUnitService
        if self.db.get_bind().dialect.name == "postgresql":
            self.db.execute(text("SELECT pg_advisory_xact_lock(741904, :id)"), {"id": equipment_id})
        service = ProductionUnitService(self.db)
        um_tag = service.resolve_um_tag(equipment_id, section_id)
        tags = self.db.query(PiTag).filter(PiTag.id.in_(tag_ids), PiTag.id != um_tag.id).all()
        before = versions(self.db, um_tag.id, tags, start, end)
        response = service.analyze(section_id, tag_ids, start, end, equipment_id=equipment_id, use_store=False, collect_quality_counts=True)
        if before != versions(self.db, um_tag.id, tags, start, end):
            raise RuntimeError("RECORDED mudou durante o rebuild; repita em uma transação REPEATABLE READ.")
        if not before.get(str(um_tag.id)) or any(str(tag.id) not in before for tag in tags):
            raise RuntimeError("A cobertura RECORDED é necessária para invalidar derivados com segurança.")
        window = self.db.query(ProductionUnitMaterialization).filter_by(equipment_id=equipment_id, section_id=section_id, um_tag_id=um_tag.id, start_ts=start, end_ts=end).first()
        if window is None:
            window = ProductionUnitMaterialization(equipment_id=equipment_id, section_id=section_id, um_tag_id=um_tag.id, start_ts=start, end_ts=end)
            self.db.add(window)
        window.segments = [segment.model_dump(mode="json", exclude={"variables"}) | {"variables": [], "quality_counts": {
            str(row["tag_id"]): {str(mask): row[f"quality_count_{mask}"] for mask in range(8)}
            for row in service.last_aggregate_rows if row["segment_index"] == index and segment.start_reason != "QUERY_START" and segment.end_reason != "QUERY_END"
        }} for index, segment in enumerate(response.segments)]
        window.source_versions = before
        # Rebuilds always publish complete metadata for this requested tag set.
        window.calculated_at = datetime.now(timezone.utc)
        # Replace occurrences inside the bounded rebuild, including removed transitions.
        old = self.db.query(ProductionUnitStoredSegment).filter(ProductionUnitStoredSegment.um_tag_id == um_tag.id, ProductionUnitStoredSegment.start_ts >= start, ProductionUnitStoredSegment.start_ts < end).all()
        starts = {segment.start_time for segment in response.segments if segment.start_reason != "QUERY_START"}
        for segment in old:
            if utc(segment.start_ts) not in starts:
                self.db.query(ProductionUnitTagStats).filter_by(segment_id=segment.id).delete()
                self.db.delete(segment)
        for segment in response.segments:
            if segment.start_reason == "QUERY_START":
                continue  # A clipped boundary is not the true occurrence identity.
            stored = self.db.query(ProductionUnitStoredSegment).filter_by(um_tag_id=um_tag.id, start_ts=segment.start_time).first()
            if stored is None:
                stored = ProductionUnitStoredSegment(equipment_id=equipment_id, um_tag_id=um_tag.id, start_ts=segment.start_time)
                self.db.add(stored)
            if segment.end_reason == "QUERY_END" and stored.end_ts is not None:
                # A query cut does not reopen an occurrence already closed by
                # a real UM transition, nor replace its complete statistics.
                continue
            changed_bounds = stored.end_ts is not None and utc(stored.end_ts) != segment.end_time
            stored.um_value, stored.status, stored.state_ts = segment.um_value, segment.status, segment.state_source_timestamp
            stored.end_ts = segment.end_time if segment.end_reason != "QUERY_END" else None
            stored.end_reason = segment.end_reason
            self.db.flush()
            stats_query = self.db.query(ProductionUnitTagStats).filter_by(segment_id=stored.id)
            if not changed_bounds:
                stats_query = stats_query.filter(ProductionUnitTagStats.tag_id.in_([tag.id for tag in tags]))
            stats_query.delete()
            if stored.end_ts is not None:
                for variable in segment.variables:
                    self.db.add(ProductionUnitTagStats(segment_id=stored.id, tag_id=variable.tag_id, source_version=before[str(variable.tag_id)], **{field: getattr(variable, field) for field in STAT_FIELDS}))
        self.db.flush()
        return response

    def refresh(self, materialization_id):
        """Incremental refresh of registered periods; no automatic history scan.

        Coverage can merge ranges, so a dirty range can conservatively encompass
        the full registered window. That fallback is bounded to 31 days.
        """
        from app.models.postgres import PiIngestionCoverage
        from sqlalchemy import or_
        window = self.db.get(ProductionUnitMaterialization, materialization_id)
        if window is None:
            raise ValueError("Materialização não encontrada.")
        from app.services.production_unit_service import ProductionUnitService
        um_tag = ProductionUnitService(self.db).resolve_um_tag(window.equipment_id, window.section_id)
        if um_tag.id != window.um_tag_id:
            return {"status": "obsolete_configuration", "updated": False}
        tag_ids = [int(key) for key in window.source_versions if int(key) != um_tag.id]
        tags = self.db.query(PiTag).filter(PiTag.id.in_(tag_ids), PiTag.active.is_(True)).all()
        current = versions(self.db, um_tag.id, tags, utc(window.start_ts), utc(window.end_ts))
        changed = [int(key) for key, version in current.items() if window.source_versions.get(key) != version]
        if not changed:
            return {"status": "current", "updated": False}
        dirty = self.db.query(PiIngestionCoverage).filter(
            PiIngestionCoverage.tag_id.in_(changed), PiIngestionCoverage.mode == "RECORDED",
            PiIngestionCoverage.updated_at > window.calculated_at,
            PiIngestionCoverage.range_start <= window.end_ts,
            or_(PiIngestionCoverage.tag_id == um_tag.id, PiIngestionCoverage.range_end > window.start_ts),
        ).all()
        # Deletions, metadata changes and changed UM seeds require rebuilding
        # the bounded registration rather than guessing an affected range.
        structure_changed = um_tag.id in changed
        if not dirty or (structure_changed and any(utc(row.range_start) < utc(window.start_ts) for row in dirty if row.tag_id == um_tag.id)):
            self.rebuild(window.equipment_id, window.section_id, tag_ids, utc(window.start_ts), utc(window.end_ts))
            return {"status": "bounded_rebuild", "updated": True}
        left = max(utc(window.start_ts), min(utc(row.range_start) for row in dirty))
        right = min(utc(window.end_ts), max(utc(row.range_end) for row in dirty))
        affected = [data for data in window.segments if datetime.fromisoformat(data["start_time"]) <= right and datetime.fromisoformat(data["end_time"]) >= left]
        if not affected:
            return {"status": "current", "updated": False}
        left = datetime.fromisoformat(affected[0]["start_time"])
        right = datetime.fromisoformat(affected[-1]["end_time"])
        old_segments = list(window.segments)
        changed_stats = tag_ids if structure_changed else changed
        self.rebuild(window.equipment_id, window.section_id, changed_stats, left, right)
        partial = self.db.query(ProductionUnitMaterialization).filter_by(equipment_id=window.equipment_id, section_id=window.section_id, um_tag_id=um_tag.id, start_ts=left, end_ts=right).first()
        old_metadata = {data["start_time"]: data for data in old_segments}
        merged = []
        for data in partial.segments:
            previous = old_metadata.get(data["start_time"], {})
            data = dict(data)
            data["quality_counts"] = previous.get("quality_counts", {}) | data.get("quality_counts", {})
            merged.append(data)
        prefix = [data for data in old_segments if datetime.fromisoformat(data["end_time"]) <= left]
        suffix = [data for data in old_segments if datetime.fromisoformat(data["start_time"]) >= right]
        window.segments = prefix + merged + suffix
        window.source_versions = current
        window.calculated_at = datetime.now(timezone.utc)
        # Unaffected occurrences keep their values. Only their covering-window
        # validation token changes after the affected interval was rebuilt.
        segment_ids = self.db.query(ProductionUnitStoredSegment.id).filter(ProductionUnitStoredSegment.um_tag_id == um_tag.id, ProductionUnitStoredSegment.start_ts >= window.start_ts, ProductionUnitStoredSegment.start_ts < window.end_ts)
        for tag_id in changed_stats:
            self.db.query(ProductionUnitTagStats).filter(ProductionUnitTagStats.segment_id.in_(segment_ids), ProductionUnitTagStats.tag_id == tag_id).update({"source_version": current[str(tag_id)]}, synchronize_session=False)
        if partial.id != window.id:
            self.db.delete(partial)
        self.db.flush()
        return {"status": "incremental", "updated": True, "start": left.isoformat(), "end": right.isoformat(), "tag_ids": changed_stats}
