"""Coverage-aware TimescaleDB/PI resolver for the time-series endpoint."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.pi_tag import PiTag
from app.models.postgres import PiSample
from app.schemas.pi import TimeSeries, TimeSeriesPoint, TimeSeriesRequest, TimeSeriesSeries
from app.services.coverage_service import CoverageService, normalize_mode
from app.services.pi_service import PiService

logger = logging.getLogger("pi_analytics_data.service.timescaledb")


def _interval_seconds(interval: Optional[str]) -> Optional[int]:
    if not interval:
        return None
    unit = interval[-1]
    amount = int(interval[:-1])
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


class DatabaseTimeSeriesService:
    def __init__(self, db: Session, pi_service: Optional[PiService] = None):
        self.db = db
        self.pi_service = pi_service

    async def fetch_time_series(self, request: TimeSeriesRequest) -> TimeSeries:
        if request.start_time >= request.end_time:
            raise ValueError("O inicio deve ser anterior ao fim.")
        if self.pi_service is None:
            raise RuntimeError("PiService e obrigatorio para resolver lacunas")

        requested_mode, interval_seconds = normalize_mode(
            request.mode, _interval_seconds(request.interval)
        )
        tags = self.pi_service._load_tags(request.tag_ids)
        series: list[TimeSeriesSeries] = []
        errors: list[dict[str, Any]] = []
        saw_db = False
        saw_pi = False

        for tag in tags:
            tag_id = tag.id
            covered = CoverageService.get_coverage(
                self.db, tag.id, request.start_time, request.end_time,
                requested_mode, interval_seconds,
            )
            missing = CoverageService.get_missing_intervals(
                self.db, tag.id, request.start_time, request.end_time,
                requested_mode, interval_seconds,
            )
            points = self._get_from_db(tag.id, covered, requested_mode)
            gap_failed = bool(missing)
            if covered:
                saw_db = True

            for gap_start, gap_end in missing:
                saw_pi = True
                try:
                    pi_result = await self.pi_service.fetch_time_series(TimeSeriesRequest(
                        tag_ids=[tag.id],
                        start_time=gap_start,
                        end_time=gap_end,
                        mode=request.mode,
                        interval=request.interval,
                        max_count=request.max_count,
                    ))
                except Exception as exc:
                    logger.exception("PI gap resolution failed tag_id=%s start=%s end=%s", tag.id, gap_start, gap_end)
                    errors.append({"tag_id": tag.id, "code": "PI_GAP_ERROR", "message": "Falha ao resolver lacuna no PI Web API."})
                    continue

                if pi_result.errors:
                    errors.extend(pi_result.errors)
                if not pi_result.series:
                    continue
                gap_series = pi_result.series[0]
                gap_points = self._clip_points(gap_series.points, gap_start, gap_end)
                points.extend(gap_points)
                if gap_points:
                    gap_failed = False
                saw_pi = True
                complete = not pi_result.errors and not any(
                    bool(s.truncated) for s in pi_result.series
                )
                if complete:
                    self._store_gap(tag, gap_points, gap_start, gap_end, requested_mode, interval_seconds)

            unique = {point.timestamp.astimezone(timezone.utc): point for point in points}
            ordered = [unique[key] for key in sorted(unique)]
            if gap_failed and not ordered:
                continue
            series.append(self._build_series(tag, ordered))

        self.db.commit()
        if saw_db and saw_pi:
            source = "hybrid"
        elif saw_db:
            source = "timescaledb"
        else:
            source = "pi_web_api"
        return TimeSeries(
            start_time=request.start_time.astimezone(timezone.utc),
            end_time=request.end_time.astimezone(timezone.utc),
            mode=request.mode,
            series=series,
            errors=errors,
            query_execution={
                "strategy": "timescaledb_direct" if source == "timescaledb" else source,
                "source": source,
                "complete": not errors,
                "partial": bool(errors),
            },
        )

    def _get_from_db(self, tag_id: int, intervals: list[tuple[datetime, datetime]], mode: str) -> list[TimeSeriesPoint]:
        if not intervals:
            return []
        points: list[TimeSeriesPoint] = []
        for start, end in intervals:
            rows = self.db.execute(text(
                """
                SELECT ts, value_double, value_boolean, value_text, value_type,
                       good, questionable, substituted
                FROM pi_samples_timescale
                WHERE tag_id = :tag_id AND source_mode = :mode
                  AND ts >= :start AND ts < :end
                ORDER BY ts ASC
                """
            ), {"tag_id": tag_id, "mode": mode, "start": start, "end": end}).fetchall()
            for row in rows:
                points.append(TimeSeriesPoint(
                    timestamp=row[0],
                    value=self._value(row[1], row[2], row[3], row[4]),
                    good=bool(row[5]),
                    questionable=bool(row[6]),
                    substituted=bool(row[7]),
                ))
        return points

    @staticmethod
    def _value(value_double: Any, value_boolean: Any, value_text: Any, value_type: str) -> Any:
        if value_type == "boolean":
            return bool(value_boolean) if value_boolean is not None else None
        if value_type in {"double", "float", "int"}:
            return float(value_double) if value_double is not None else None
        return str(value_text) if value_text is not None else None

    def _store_gap(
        self,
        tag: PiTag,
        points: list[TimeSeriesPoint],
        start: datetime,
        end: datetime,
        mode: str,
        interval_seconds: Optional[int],
    ) -> None:
        points = self._clip_points(points, start, end)
        if not points:
            CoverageService.record_coverage(self.db, tag.id, start, end, mode, interval_seconds, pi_web_id=tag.pi_web_id)
            return
        records = [self._record(tag.id, point, mode) for point in points]
        insert_factory = pg_insert if self.db.bind is not None and self.db.bind.dialect.name == "postgresql" else sqlite_insert
        stmt = insert_factory(PiSample).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tag_id", "ts"],
            set_={
                "value_type": stmt.excluded.value_type,
                "value_double": stmt.excluded.value_double,
                "value_text": stmt.excluded.value_text,
                "value_boolean": stmt.excluded.value_boolean,
                "good": stmt.excluded.good,
                "questionable": stmt.excluded.questionable,
                "substituted": stmt.excluded.substituted,
                "source_mode": stmt.excluded.source_mode,
                "ingested_at": stmt.excluded.ingested_at,
            },
        )
        self.db.execute(stmt)
        CoverageService.record_coverage(self.db, tag.id, start, end, mode, interval_seconds, pi_web_id=tag.pi_web_id)

    @staticmethod
    def _clip_points(
        points: list[TimeSeriesPoint],
        start: datetime,
        end: datetime,
    ) -> list[TimeSeriesPoint]:
        """Keep returned points aligned with the half-open coverage interval."""
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        return [
            point for point in points
            if start_utc <= point.timestamp.astimezone(timezone.utc) < end_utc
        ]

    @staticmethod
    def _record(tag_id: int, point: TimeSeriesPoint, mode: str) -> dict[str, Any]:
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

    @staticmethod
    def _build_series(tag: PiTag, points: list[TimeSeriesPoint]) -> TimeSeriesSeries:
        return TimeSeriesSeries(
            tag_id=tag.id,
            tag_name=tag.pi_tag_name,
            display_name=tag.display_name,
            equipment=tag.equipment.code if tag.equipment else None,
            section=tag.section.code if tag.section else None,
            variable_type=tag.variable_type.code if tag.variable_type else None,
            unit=getattr(tag, "_meta_unit", None) or tag.engineering_unit,
            points=points,
            source_point_count=len(points),
            returned_point_count=len(points),
            sampled=False,
            truncated=False,
        )
