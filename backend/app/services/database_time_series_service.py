"""Coverage-aware TimescaleDB/PI resolver for the time-series endpoint."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.exceptions import HistoricalDataNotLoadedError, QueryLimitExceededError, TimeRangeInvalidError, ValidationError
from app.models.pi_tag import PiTag
from app.models.postgres import PiSample
from app.repositories.pi_tag_repository import PiTagRepository
from app.schemas.pi import TimeSeries, TimeSeriesPoint, TimeSeriesRequest, TimeSeriesSeries
from app.services.coverage_service import CoverageService, normalize_mode

logger = logging.getLogger("pi_analytics_data.service.timescaledb")


def _interval_seconds(interval: Optional[str]) -> Optional[int]:
    if not interval:
        return None
    unit = interval[-1]
    amount = int(interval[:-1])
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


class DatabaseTimeSeriesService:
    """Read-only historical resolver backed exclusively by TimescaleDB.

    PI Web API acquisition belongs to ingestion/backfill workers. A missing
    coverage interval is an explicit administrative-reload request, never a
    reason to synchronously call PI from a user query.
    """

    def __init__(self, db: Session, pi_service: Optional[object] = None):
        self.db = db
        self.repo = PiTagRepository(db)

    async def fetch_time_series(self, request: TimeSeriesRequest, **_kwargs: Any) -> TimeSeries:
        if request.start_time >= request.end_time:
            raise TimeRangeInvalidError("O inicio deve ser anterior ao fim.")
        try:
            requested_mode, interval_seconds = normalize_mode(
                request.mode, _interval_seconds(request.interval)
            )
        except (ValueError, KeyError) as exc:
            raise ValidationError("Modo ou resolução de série inválidos.", details={"mode": request.mode, "interval": request.interval}) from exc
        if len(request.tag_ids) > 100:
            raise QueryLimitExceededError("Quantidade de tags excede o limite configurado.")
        tags = []
        for tag_id in request.tag_ids:
            tag = self.repo.get(tag_id)
            if tag is None:
                from app.core.exceptions import NotFoundError
                raise NotFoundError("Tag local nao encontrada.", details={"pi_tag_id": tag_id})
            if not tag.active:
                from app.core.exceptions import TagInactiveError
                raise TagInactiveError(details={"pi_tag_id": tag_id})
            tag._meta_unit = tag.engineering_unit or (tag.variable_type.default_unit if tag.variable_type else None)
            tags.append(tag)
        series: list[TimeSeriesSeries] = []
        missing_details: list[dict[str, Any]] = []

        for tag in tags:
            covered = CoverageService.get_coverage(
                self.db, tag.id, request.start_time, request.end_time,
                requested_mode, interval_seconds,
            )
            missing = CoverageService.get_missing_intervals(
                self.db, tag.id, request.start_time, request.end_time,
                requested_mode, interval_seconds,
            )
            if missing:
                missing_details.append({
                    "tag_id": tag.id,
                    "tag_name": tag.pi_tag_name,
                    "intervals": [
                        {"start": start.astimezone(timezone.utc).isoformat(), "end": end.astimezone(timezone.utc).isoformat()}
                        for start, end in missing
                    ],
                })
                continue
            points = self._get_from_db(tag.id, covered, requested_mode)
            if request.max_count and len(points) > request.max_count:
                points = points[:request.max_count]
            series.append(self._build_series(tag, points))

        if missing_details:
            raise HistoricalDataNotLoadedError(details={
                "affected_tags": missing_details,
                "mode": request.mode,
                "resolution": request.interval if request.mode == "interpolated" else None,
                "requested_period": {
                    "start": request.start_time.astimezone(timezone.utc).isoformat(),
                    "end": request.end_time.astimezone(timezone.utc).isoformat(),
                },
                "reload_available": True,
            })

        return TimeSeries(
            start_time=request.start_time.astimezone(timezone.utc),
            end_time=request.end_time.astimezone(timezone.utc),
            mode=request.mode,
            series=series,
            errors=[],
            query_execution={
                "strategy": "timescaledb_direct",
                "source": "timescaledb",
                "complete": True,
                "partial": False,
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
