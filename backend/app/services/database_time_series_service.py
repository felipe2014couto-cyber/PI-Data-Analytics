"""Coverage-aware TimescaleDB/PI resolver for the time-series endpoint."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import HistoricalDataNotLoadedError, QueryLimitExceededError, TimeRangeInvalidError, ValidationError
from app.models.pi_tag import PiTag
from app.models.postgres import PiIngestionState, PiSample
from app.repositories.pi_tag_repository import PiTagRepository
from app.schemas.pi import TimeSeries, TimeSeriesPoint, TimeSeriesRequest, TimeSeriesSeries
from app.services.cache import LruCache
from app.services.coverage_service import CoverageService, normalize_mode

logger = logging.getLogger("pi_analytics_data.service.timescaledb")

_PLOT_AGGREGATES: tuple[tuple[int, str, str], ...] = (
    (10, "pi_recorded_plot_10s", "10s"),
    (60, "pi_recorded_plot_1m", "1m"),
    (300, "pi_recorded_plot_5m", "5m"),
    (3600, "pi_recorded_plot_hourly", "1h"),
    (86400, "pi_recorded_plot_daily", "1d"),
)
_WEIGHTED_PLOT_AVERAGE_SQL = (
    "sum(avg_value * sample_count) / NULLIF(sum(sample_count), 0)"
)


@dataclass(frozen=True)
class DynamicPlotPlan:
    view_name: Optional[str]
    source_bucket_seconds: Optional[int]
    display_bucket_seconds: Optional[int]
    use_raw: bool
    raw_point_count: int


_timescaledb_query_cache = LruCache[tuple[Any, ...], TimeSeries](
    max_size=settings.timescaledb_query_cache_max_entries,
    default_ttl_seconds=settings.timescaledb_query_cache_ttl_seconds,
)


def _interval_seconds(interval: Optional[str]) -> Optional[int]:
    if not interval:
        return None
    unit = interval[-1]
    amount = int(interval[:-1])
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _format_interval(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _plot_aggregate_for(request: TimeSeriesRequest, *, postgres: bool) -> tuple[str, str] | None:
    """Select the Plot aggregate used for every visual query on Postgres."""
    if not postgres:
        return None
    duration = request.end_time - request.start_time
    if duration <= timedelta(hours=6):
        return "pi_recorded_plot_10s", "10s"
    if duration <= timedelta(days=2):
        return "pi_recorded_plot_1m", "1m"
    if duration <= timedelta(days=14):
        return "pi_recorded_plot_5m", "5m"
    if duration <= timedelta(days=31):
        return "pi_recorded_plot_hourly", "1h"
    return "pi_recorded_plot_daily", "1d"


def _dynamic_plot_plan(
    duration: timedelta,
    target_points_per_tag: int,
    raw_point_count: int,
    raw_point_limit: int,
    available_aggregates: tuple[tuple[int, str, str], ...] = _PLOT_AGGREGATES,
) -> DynamicPlotPlan:
    """Choose raw data or the closest lossless aggregate below the ideal bucket."""
    ideal_seconds = max(1, int(math.ceil(duration.total_seconds() / target_points_per_tag)))
    if raw_point_count <= raw_point_limit:
        return DynamicPlotPlan(None, None, None, True, raw_point_count)

    if not available_aggregates:
        return DynamicPlotPlan(None, None, None, True, raw_point_count)
    eligible = [entry for entry in _PLOT_AGGREGATES if entry[0] <= ideal_seconds]
    expected = max(eligible or [_PLOT_AGGREGATES[0]], key=lambda entry: entry[0])
    if expected in available_aggregates:
        source_seconds, view_name, _ = expected
    else:
        # A canonical level may be absent while its migration is pending. Use
        # the closest installed level instead of failing or multiplying the
        # response size by selecting an arbitrarily fine source.
        source_seconds, view_name, _ = min(
            available_aggregates,
            key=lambda entry: abs(math.log(entry[0] / ideal_seconds)),
        )
    return DynamicPlotPlan(
        view_name=view_name,
        source_bucket_seconds=source_seconds,
        # Source buckets are indivisible. Splitting a 300s bucket across a
        # 404s display boundary misassigns extrema and loses their timestamps.
        display_bucket_seconds=source_seconds * max(1, math.ceil(ideal_seconds / source_seconds)),
        use_raw=False,
        raw_point_count=raw_point_count,
    )


class DatabaseTimeSeriesService:
    """Read-only historical resolver backed exclusively by TimescaleDB.

    PI Web API acquisition belongs to ingestion/backfill workers. A missing
    coverage interval is an explicit administrative-reload request, never a
    reason to synchronously call PI from a user query.
    """

    def __init__(self, db: Session, pi_service: Optional[object] = None):
        self.db = db
        self.repo = PiTagRepository(db)

    def _available_plot_aggregates(self) -> tuple[tuple[int, str, str], ...]:
        if self.db.bind is None or self.db.bind.dialect.name != "postgresql":
            return ()
        names = tuple(row[0] for row in self.db.execute(text("""
            SELECT name
            FROM (VALUES
              ('pi_recorded_plot_10s'),
              ('pi_recorded_plot_1m'),
              ('pi_recorded_plot_5m'),
              ('pi_recorded_plot_hourly'),
              ('pi_recorded_plot_daily')
            ) AS candidates(name)
            WHERE to_regclass(name) IS NOT NULL
        """)).fetchall())
        return tuple(entry for entry in _PLOT_AGGREGATES if entry[1] in names)

    async def fetch_time_series(self, request: TimeSeriesRequest, **_kwargs: Any) -> TimeSeries:
        if request.start_time >= request.end_time:
            raise TimeRangeInvalidError("O inicio deve ser anterior ao fim.")
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

        postgres = self.db.bind is not None and self.db.bind.dialect.name == "postgresql"
        available_plot_aggregates = self._available_plot_aggregates() if postgres else ()
        plot_aggregate = _plot_aggregate_for(request, postgres=postgres)
        if plot_aggregate and plot_aggregate[0] not in {entry[1] for entry in available_plot_aggregates}:
            desired_seconds = _interval_seconds(plot_aggregate[1]) or 1
            replacement = min(
                available_plot_aggregates,
                key=lambda entry: abs(math.log(entry[0] / desired_seconds)),
                default=None,
            )
            plot_aggregate = (replacement[1], replacement[2]) if replacement else None
        dynamic_requested = postgres and request.target_points_per_tag is not None

        # Plot aggregates are the only visual read path. RECORDED remains the
        # internal source populated by the ingestion worker.
        if plot_aggregate:
            requested_mode, interval_seconds = "RECORDED", None
        elif request.mode == "recorded":
            requested_mode, interval_seconds = "RECORDED", None
        else:
            try:
                requested_interval = _interval_seconds(request.interval)
                if requested_interval is not None and requested_interval < 10:
                    raise QueryLimitExceededError("O intervalo mínimo para interpolação é de 10 segundos.")
                # API clients that omit resolution_mode retain the historical
                # exact-interval contract; the UI sends "automatic" explicitly.
                resolution_mode = (request.resolution_mode or "manual").lower()
                if resolution_mode == "automatic":
                    # The frontend used to send 1m for automatic requests.
                    # Ignore that hint and choose only persisted canonical
                    # resolutions.  A candidate is usable only when every tag
                    # has complete coverage for the whole period.
                    target = request.target_points_per_tag or settings.pi_query_visual_default_points_per_tag
                    required_seconds = max(1, int(math.ceil(
                        (request.end_time - request.start_time).total_seconds() / target
                    )))
                    candidates = [seconds for seconds in (10, 300) if seconds >= required_seconds]
                    if not candidates:
                        candidates = [300]
                    requested_mode, interval_seconds = "", None
                    for candidate in candidates:
                        candidate_mode = f"INTERPOLATED_{candidate}S"
                        if all(not CoverageService.get_missing_intervals(
                            self.db, tag.id, request.start_time, request.end_time,
                            candidate_mode, candidate,
                        ) for tag in tags):
                            requested_mode, interval_seconds = candidate_mode, candidate
                            break
                    if not requested_mode:
                        # Use the coarsest canonical resolution in the error so
                        # the administrative reload has an actionable target.
                        interval_seconds = candidates[-1]
                        requested_mode = f"INTERPOLATED_{interval_seconds}S"
                else:
                    requested_mode, interval_seconds = normalize_mode("INTERPOLATED", requested_interval)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValidationError(
                    "Modo ou resolução de série inválidos.",
                    details={"mode": request.mode, "interval": request.interval},
                ) from exc

        effective_end = request.end_time
        freshness_metadata: dict[str, Any] = {}
        if request.relative_period:
            effective_end, freshness_metadata = self._resolve_relative_end(
                request,
                tags,
                requested_mode,
                interval_seconds,
                allow_stale=plot_aggregate is not None,
                check_coverage=plot_aggregate is None,
            )

        effective_target_points: Optional[int] = None
        dynamic_plan: Optional[DynamicPlotPlan] = None
        raw_visual = False
        cache_key: Optional[tuple[Any, ...]] = None
        if dynamic_requested:
            effective_target_points = min(
                max(100, request.target_points_per_tag or settings.pi_query_visual_default_points_per_tag),
                settings.pi_query_visual_max_points_per_tag,
                max(1, settings.pi_query_visual_max_total_points // len(tags)),
            )
            cache_key = (
                "timescaledb-dynamic-v1",
                tuple(sorted(request.tag_ids)),
                request.start_time.astimezone(timezone.utc),
                effective_end.astimezone(timezone.utc),
                effective_target_points,
                request.max_count,
            )
            if not bool(_kwargs.get("refresh")):
                cached = _timescaledb_query_cache.get(cache_key)
                if cached is not None:
                    # LruCache.get already returns an isolated deep copy.
                    result = cached
                    if result.query_execution is not None:
                        result.query_execution.cache_hit = True
                    return result

            raw_point_count = self._count_qualified_raw_points(
                request.tag_ids,
                request.start_time,
                effective_end,
                settings.timescaledb_dynamic_raw_point_limit,
            )
            dynamic_plan = _dynamic_plot_plan(
                effective_end - request.start_time,
                effective_target_points,
                raw_point_count,
                settings.timescaledb_dynamic_raw_point_limit,
                available_plot_aggregates,
            )
            raw_visual = dynamic_plan.use_raw
            if dynamic_plan.view_name is not None and dynamic_plan.display_bucket_seconds is not None:
                plot_aggregate = (
                    dynamic_plan.view_name,
                    _format_interval(dynamic_plan.display_bucket_seconds) or "1s",
                )
            else:
                plot_aggregate = None

        effective_interval = (
            "recorded" if raw_visual
            else plot_aggregate[1] if plot_aggregate
            else _format_interval(interval_seconds)
        )

        series: list[TimeSeriesSeries] = []
        missing_details: list[dict[str, Any]] = []
        total_returned_points = 0

        for tag in tags:
            if raw_visual:
                missing = CoverageService.get_missing_intervals(
                    self.db, tag.id, request.start_time, effective_end,
                    "RECORDED", None,
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
                all_points = self._get_qualified_raw_points(tag.id, request.start_time, effective_end)
                # Apply visual bucketing when raw points exceed reasonable display limit
                max_visual_points = 2000
                if len(all_points) > max_visual_points:
                    points = self._downsample_for_visual(all_points, max_visual_points)
                else:
                    points = all_points
            elif plot_aggregate:
                points = self._get_from_plot(
                    tag.id,
                    request.start_time,
                    effective_end,
                    plot_aggregate[0],
                    display_bucket_seconds=(
                        dynamic_plan.display_bucket_seconds if dynamic_plan is not None else None
                    ),
                )
            else:
                covered = CoverageService.get_coverage(
                    self.db, tag.id, request.start_time, effective_end,
                    requested_mode, interval_seconds,
                )
                missing = CoverageService.get_missing_intervals(
                    self.db, tag.id, request.start_time, effective_end,
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
            if not dynamic_requested and request.max_count and len(points) > request.max_count:
                points = points[:request.max_count]
            total_returned_points += len(points)
            if total_returned_points > settings.pi_query_visual_max_total_points:
                raise QueryLimitExceededError(
                    "Quantidade de pontos excede o limite visual da requisição.",
                    details={
                        "returned": total_returned_points,
                        "limit": settings.pi_query_visual_max_total_points,
                    },
                )
            series.append(self._build_series(tag, points))

        if missing_details:
            raise HistoricalDataNotLoadedError(details={
                "affected_tags": missing_details,
                "mode": request.mode,
                "resolution": effective_interval,
                "requested_resolution": request.interval if request.mode == "interpolated" else "10s",
                "effective_resolution": effective_interval,
                "canonical_resolutions": ["10s", "5m"] if request.mode == "interpolated" and (request.resolution_mode or "").lower() == "automatic" else None,
                "requested_period": {
                    "start": request.start_time.astimezone(timezone.utc).isoformat(),
                    "end": request.end_time.astimezone(timezone.utc).isoformat(),
                },
                "reload_available": True,
            })

        query_execution: dict[str, Any] = {
            "strategy": "timescaledb_continuous_aggregate" if plot_aggregate else "timescaledb_direct",
            "source": "timescaledb",
            "effective_source_mode": "RECORDED" if plot_aggregate or raw_visual else requested_mode,
            "complete": True,
            "partial": False,
            "effective_interval": effective_interval,
            "points_returned": total_returned_points,
            "cache_hit": False if dynamic_requested else None,
        }
        if plot_aggregate:
            query_execution.update({
                "plot_aggregate": plot_aggregate[0],
                "sampled": True,
            })
        if dynamic_plan is not None:
            query_execution.update({
                "effective_target_points_per_tag": effective_target_points,
                "raw_point_count": dynamic_plan.raw_point_count,
                "dynamic_bucket_seconds": dynamic_plan.display_bucket_seconds,
                "sampled": not dynamic_plan.use_raw,
            })
        query_execution.update(freshness_metadata)

        result = TimeSeries(
            start_time=request.start_time.astimezone(timezone.utc),
            end_time=effective_end.astimezone(timezone.utc),
            mode="recorded",
            series=series,
            errors=[],
            query_execution=query_execution,
        )
        if cache_key is not None:
            _timescaledb_query_cache.set(
                cache_key,
                result.model_copy(deep=True),
                ttl_seconds=settings.timescaledb_query_cache_ttl_seconds,
            )
        return result

    def _resolve_relative_end(
        self,
        request: TimeSeriesRequest,
        tags: list[PiTag],
        mode: str,
        interval_seconds: Optional[int],
        *,
        allow_stale: bool = False,
        check_coverage: bool = True,
    ) -> tuple[datetime, dict[str, Any]]:
        """Validate a relative period against the common ingestion watermark.

        Relative requests may end at the last common watermark only when the
        covered prefix is continuous and the worker is within its configured
        freshness tolerance. Absolute requests never use this shortening path.
        """
        requested_end = request.end_time.astimezone(timezone.utc)
        rows: list[PiIngestionState] = []
        try:
            for tag in tags:
                query = self.db.query(PiIngestionState).filter(PiIngestionState.tag_id == tag.id)
                if hasattr(PiIngestionState, "source_mode"):
                    query = query.filter(PiIngestionState.source_mode == mode)
                row = query.order_by(PiIngestionState.updated_at.desc()).first()
                if row is None or row.watermark_ts is None:
                    raise HistoricalDataNotLoadedError(details={"reload_available": True, "reason": "INGESTION_WATERMARK_UNAVAILABLE"})
                rows.append(row)
        except HistoricalDataNotLoadedError:
            raise
        except Exception as exc:
            logger.warning("Could not read ingestion watermark for relative query: %s", exc)
            raise HistoricalDataNotLoadedError(details={"reload_available": True, "reason": "INGESTION_WATERMARK_UNAVAILABLE"}) from exc

        watermark = min(row.watermark_ts.astimezone(timezone.utc) for row in rows)
        effective_end = min(requested_end, watermark)
        lag_seconds = max(0.0, (requested_end - watermark).total_seconds())
        stale = lag_seconds > settings.ingestion_freshness_tolerance_seconds
        internal_missing: list[dict[str, Any]] = []
        if check_coverage and effective_end > request.start_time:
            for tag in tags:
                missing = CoverageService.get_missing_intervals(
                    self.db, tag.id, request.start_time, effective_end, mode, interval_seconds,
                )
                if missing:
                    internal_missing.append({"tag_id": tag.id, "intervals": [
                        {"start": start.isoformat(), "end": end.isoformat()}
                        for start, end in missing
                    ]})
        if (stale and not allow_stale) or internal_missing or effective_end <= request.start_time:
            raise HistoricalDataNotLoadedError(details={
                "reload_available": True,
                "reason": "STALE_INGESTION" if stale else "INTERNAL_COVERAGE_GAP" if internal_missing else "INGESTION_WATERMARK_UNAVAILABLE",
                "affected_tags": internal_missing,
                "requested_end": requested_end.isoformat(),
                "data_available_until": watermark.isoformat(),
                "freshness_lag_seconds": lag_seconds,
            })
        return effective_end, {
            "requested_end": requested_end,
            "effective_end": effective_end,
            "data_available_until": watermark,
            "freshness_lag_seconds": lag_seconds,
            "is_stale": stale,
        }

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

    def _count_qualified_raw_points(
        self,
        tag_ids: list[int],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> int:
        """Count only far enough to decide whether the raw visual path is safe."""
        return int(self.db.execute(text("""
            SELECT count(*)
            FROM (
                SELECT 1
                FROM pi_samples_timescale
                WHERE tag_id = ANY(CAST(:tag_ids AS integer[]))
                  AND ts >= :start
                  AND ts < :end
                  AND source_mode = 'RECORDED'
                  AND value_type IN ('double', 'float', 'int')
                  AND value_double IS NOT NULL
                  AND good IS TRUE
                  AND questionable IS FALSE
                  AND substituted IS FALSE
                LIMIT :probe_limit
            ) AS qualified
        """), {
            "tag_ids": tag_ids,
            "start": start,
            "end": end,
            "probe_limit": limit + 1,
        }).scalar_one())

    def _get_qualified_raw_points(
        self,
        tag_id: int,
        start: datetime,
        end: datetime,
    ) -> list[TimeSeriesPoint]:
        rows = self.db.execute(text("""
            SELECT ts, value_double, good, questionable, substituted
            FROM pi_samples_timescale
            WHERE tag_id = :tag_id
              AND ts >= :start
              AND ts < :end
              AND source_mode = 'RECORDED'
              AND value_type IN ('double', 'float', 'int')
              AND value_double IS NOT NULL
              AND good IS TRUE
              AND questionable IS FALSE
              AND substituted IS FALSE
            ORDER BY ts ASC
        """), {"tag_id": tag_id, "start": start, "end": end}).fetchall()
        return [
            TimeSeriesPoint(
                timestamp=row[0],
                value=float(row[1]),
                good=bool(row[2]),
                questionable=bool(row[3]),
                substituted=bool(row[4]),
            )
            for row in rows
        ]

    def _get_from_plot(
        self,
        tag_id: int,
        start: datetime,
        end: datetime,
        view_name: str,
        *,
        display_bucket_seconds: Optional[int] = None,
    ) -> list[TimeSeriesPoint]:
        """Read Plot aggregates with PI-style query-time interpolation.

        The materialized aggregates remain sparse and faithful to RecordedValues.
        ``time_bucket_gapfill`` creates display buckets. Empty numeric buckets
        are linearly interpolated between the surrounding RecordedValues, which
        matches the PI Web API Plot boundary behavior. The view name and interval
        are selected from a fixed allow-list above this method.
        """
        source_interval_seconds = {
            "pi_recorded_plot_10s": 10,
            "pi_recorded_plot_1m": 60,
            "pi_recorded_plot_5m": 300,
            "pi_recorded_plot_hourly": 3600,
            "pi_recorded_plot_daily": 86400,
        }.get(view_name)
        if source_interval_seconds is None:
            raise ValueError(f"Unsupported Plot aggregate: {view_name}")
        bucket_seconds = max(source_interval_seconds, int(display_bucket_seconds or source_interval_seconds))
        interval = f"{bucket_seconds} seconds"
        rows = self.db.execute(text(f"""
            WITH seed AS (
                SELECT value_double AS last_value, ts AS last_ts
                FROM pi_samples_timescale
                WHERE tag_id = :tag_id
                  AND ts < CAST(:start AS timestamptz)
                  AND source_mode = 'RECORDED'
                  AND value_type IN ('double', 'float', 'int')
                  AND value_double IS NOT NULL
                  AND good IS TRUE
                  AND questionable IS FALSE
                  AND substituted IS FALSE
                ORDER BY ts DESC
                LIMIT 1
            ), gapfilled AS (
              SELECT
                time_bucket_gapfill(
                    INTERVAL '{interval}',
                    bucket,
                    start => CAST(:start AS timestamptz),
                    finish => CAST(:end AS timestamptz)
                ) AS bucket,
                min(min_value) AS min_value,
                max(max_value) AS max_value,
                first(first_value, bucket) FILTER (WHERE sample_count > 0) AS first_value,
                last(last_value, bucket) FILTER (WHERE sample_count > 0) AS last_value,
                {_WEIGHTED_PLOT_AVERAGE_SQL} AS avg_value,
                min(first_ts) AS first_ts,
                max(last_ts) AS last_ts,
                COALESCE(sum(sample_count), 0) AS sample_count
              FROM {view_name}
              WHERE tag_id = :tag_id
                AND bucket >= CAST(:start AS timestamptz)
                AND bucket < CAST(:end AS timestamptz)
              GROUP BY time_bucket_gapfill(
                  INTERVAL '{interval}',
                  bucket,
                  start => CAST(:start AS timestamptz),
                  finish => CAST(:end AS timestamptz)
              )
            ), grouped AS (
              SELECT
                gapfilled.*,
                count(last_value) FILTER (WHERE sample_count > 0)
                  OVER (ORDER BY bucket ASC) AS previous_group,
                count(first_value) FILTER (WHERE sample_count > 0)
                  OVER (ORDER BY bucket DESC) AS following_group
              FROM gapfilled
            ), neighbors AS (
              SELECT
                grouped.*,
                COALESCE(
                  max(last_ts) OVER (PARTITION BY previous_group),
                  (SELECT last_ts FROM seed)
                ) AS previous_ts,
                COALESCE(
                  max(last_value) OVER (PARTITION BY previous_group),
                  (SELECT last_value FROM seed)
                ) AS previous_value,
                max(first_ts) OVER (PARTITION BY following_group) AS following_ts,
                max(first_value) OVER (PARTITION BY following_group) AS following_value
              FROM grouped
            ), filled AS (
              SELECT
                neighbors.*,
                CASE
                  WHEN sample_count <> 0 THEN NULL
                  WHEN previous_ts IS NOT NULL
                   AND following_ts IS NOT NULL
                   AND following_ts > previous_ts
                    THEN previous_value + (following_value - previous_value) *
                      EXTRACT(EPOCH FROM (bucket - previous_ts)) /
                      NULLIF(EXTRACT(EPOCH FROM (following_ts - previous_ts)), 0)
                  ELSE COALESCE(previous_value, following_value)
                END AS interpolated_value
              FROM neighbors
            ), display_buckets AS (
              SELECT
                bucket,
                CASE WHEN sample_count = 0 THEN interpolated_value ELSE min_value END AS min_value,
                CASE WHEN sample_count = 0 THEN interpolated_value ELSE max_value END AS max_value,
                CASE WHEN sample_count = 0 THEN interpolated_value ELSE first_value END AS first_value,
                CASE WHEN sample_count = 0 THEN interpolated_value ELSE last_value END AS last_value,
                CASE WHEN sample_count = 0 THEN interpolated_value ELSE avg_value END AS avg_value,
                first_ts,
                last_ts,
                sample_count,
                sample_count = 0 AS is_gapfilled
              FROM filled
            ), extrema AS (
              SELECT
                display_buckets.bucket,
                min(sample.ts) FILTER (WHERE sample.value_double = display_buckets.min_value) AS min_ts,
                min(sample.ts) FILTER (WHERE sample.value_double = display_buckets.max_value) AS max_ts
              FROM display_buckets
              JOIN pi_samples_timescale AS sample
                ON time_bucket(INTERVAL '{interval}', sample.ts) = display_buckets.bucket
              WHERE display_buckets.sample_count > 0
                AND sample.tag_id = :tag_id
                AND sample.source_mode = 'RECORDED'
                AND sample.value_type IN ('double', 'float', 'int')
                AND sample.value_double IS NOT NULL
                AND sample.good IS TRUE
                AND sample.questionable IS FALSE
                AND sample.substituted IS FALSE
                AND sample.ts >= CAST(:start AS timestamptz)
                AND sample.ts < CAST(:end AS timestamptz)
              GROUP BY display_buckets.bucket
            )
            SELECT
              display_buckets.*,
              extrema.min_ts,
              extrema.max_ts,
              (SELECT COUNT(*) > 0 FROM seed) AS has_previous_value
            FROM display_buckets
            LEFT JOIN extrema ON extrema.bucket = display_buckets.bucket
            ORDER BY display_buckets.bucket ASC
        """), {"tag_id": tag_id, "start": start, "end": end}).fetchall()
        points: list[TimeSeriesPoint] = []
        for row in rows:
            avg_value = float(row[5]) if row[5] is not None else None
            points.append(TimeSeriesPoint(
                timestamp=row[0],
                value=avg_value if avg_value is not None else row[4],
                plot_min=float(row[1]) if row[1] is not None else None,
                plot_max=float(row[2]) if row[2] is not None else None,
                plot_first=float(row[3]) if row[3] is not None else None,
                plot_last=float(row[4]) if row[4] is not None else None,
                plot_avg=avg_value,
                plot_first_ts=row[6],
                plot_last_ts=row[7],
                plot_sample_count=int(row[8]) if row[8] is not None else None,
                is_gapfilled=bool(row[9]),
                plot_min_ts=row[10],
                plot_max_ts=row[11],
                has_previous_value=bool(row[12]) if row[12] is not None else None,
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
        points = list({point.timestamp.astimezone(timezone.utc): point for point in points}.values())
        if not points:
            CoverageService.record_coverage(self.db, tag.id, start, end, mode, interval_seconds, pi_web_id=tag.pi_web_id)
            return
        records = [self._record(tag.id, point, mode) for point in points]
        insert_factory = pg_insert if self.db.bind is not None and self.db.bind.dialect.name == "postgresql" else sqlite_insert
        for offset in range(0, len(records), 500):
            stmt = insert_factory(PiSample).values(records[offset:offset + 500])
            stmt = stmt.on_conflict_do_update(
                index_elements=["tag_id", "ts", "source_mode"],
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
