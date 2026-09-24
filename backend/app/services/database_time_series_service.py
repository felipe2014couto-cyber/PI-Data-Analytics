"""Coverage-aware TimescaleDB/PI resolver for the time-series endpoint."""
from __future__ import annotations

import asyncio
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
from app.models.sip_source import SipSource
from app.models.postgres import PiIngestionState, PiSample
from app.models.section_analysis_tag import SectionAnalysisTag
from app.models.variable_type import VariableFilterDataType
from app.repositories.pi_tag_repository import PiTagRepository
from app.schemas.pi import AnalysisFilterRequest, QueryExecutionMetadata, TimeSeries, TimeSeriesPoint, TimeSeriesRequest, TimeSeriesSeries
from app.services.cache import LruCache
from app.services.coverage_service import CoverageService, normalize_mode
from app.services.string_filter_parser import ExactMatch, RangeMatch, WildcardMatch, parse_string_filter
from app.services.sip_oracle_service import SipOracleService

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


@dataclass(frozen=True)
class PlotReadResult:
    points: list[TimeSeriesPoint]
    segments: list[dict[str, Any]]
    uncovered: list[dict[str, Any]]


_timescaledb_query_cache = LruCache[tuple[Any, ...], TimeSeries](
    max_size=settings.timescaledb_query_cache_max_entries,
    default_ttl_seconds=settings.timescaledb_query_cache_ttl_seconds,
)


def invalidate_time_series_cache(tag_ids: list[int], start: datetime, end: datetime) -> int:
    """Invalidate cached visual queries intersecting persisted history."""
    affected = set(tag_ids)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    def intersects(key: tuple[Any, ...]) -> bool:
        if len(key) < 5 or not str(key[0]).startswith("timescaledb-dynamic-v"):
            return False
        cached_tags = set(key[1])
        cached_start, cached_end = key[2], key[3]
        return bool(affected & cached_tags) and cached_start < end_utc and cached_end > start_utc

    return _timescaledb_query_cache.remove_where(intersects)


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
        # Avoid artificial over-quantization: display bucket reproduces the target
        # resolution dynamically, bounded below by the source bucket resolution.
        display_bucket_seconds=max(source_seconds, ideal_seconds),
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

    async def _fetch_with_sip(self, request: TimeSeriesRequest, **kwargs: Any) -> TimeSeries:
        from app.core.exceptions import NotFoundError

        if request.mode != "recorded":
            raise ValidationError("Fontes SIP aceitam somente modo Recorded.")
        if request.analysis_filters:
            raise ValidationError("Filtros de análise da seção não são suportados para fontes SIP.")
        if request.start_time >= request.end_time:
            raise TimeRangeInvalidError("O início deve ser anterior ao fim.")
        pi_ids = [tag_id for tag_id in request.tag_ids if tag_id > 0]
        sip_ids = [tag_id for tag_id in request.tag_ids if tag_id < 0]
        pi_result = await self.fetch_time_series(request.model_copy(update={"tag_ids": pi_ids}), **kwargs) if pi_ids else None
        sip_series: list[TimeSeriesSeries] = []
        any_truncated = False
        for tag_id in sip_ids:
            source = self.db.get(SipSource, -tag_id)
            if source is None or not source.active:
                raise NotFoundError("Fonte SIP não encontrada.", details={"source_id": -tag_id})
            if request.section_id is not None and source.section_id not in (None, request.section_id):
                raise ValidationError("A fonte SIP não pertence à seção selecionada.")
            from app.services.sip_reload_service import has_coverage, stored_rows
            from app.services.sip_oracle_service import period_sql
            if has_coverage(self.db, source, request.start_time, request.end_time):
                row_limit = settings.sip_oracle_max_rows
                rows = stored_rows(self.db, source.id, request.start_time, request.end_time, row_limit + 1)
                truncated = len(rows) > row_limit
                if truncated:
                    rows = rows[-row_limit:]
            else:
                rows, truncated = await asyncio.to_thread(
                    SipOracleService().fetch_rows,
                    period_sql(source.sql_text),
                    source.timestamp_column,
                    source.value_column,
                    request.start_time,
                    request.end_time,
                )
            any_truncated = any_truncated or truncated
            sip_series.append(TimeSeriesSeries(
                tag_id=tag_id,
                tag_name=f"SIP:{source.id}",
                display_name=source.name,
                points=[TimeSeriesPoint(timestamp=timestamp, value=value) for timestamp, value in rows],
                source_point_count=len(rows),
                returned_point_count=len(rows),
                truncated=truncated,
            ))
        series_by_id = {series.tag_id: series for series in (pi_result.series if pi_result else []) + sip_series}
        metadata = pi_result.query_execution if pi_result else QueryExecutionMetadata()
        metadata.source = "hybrid" if pi_result else "sip"
        if not pi_result:
            metadata.effective_source_mode = "SIP_RECORDED"
            metadata.effective_interval = "recorded"
        metadata.visual_total_points = sum(len(item.points) for item in series_by_id.values())
        metadata.truncated = bool(metadata.truncated or any_truncated)
        return TimeSeries(
            start_time=request.start_time,
            end_time=request.end_time,
            mode=request.mode,
            series=[series_by_id[tag_id] for tag_id in request.tag_ids],
            errors=pi_result.errors if pi_result else [],
            query_execution=metadata,
        )

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
        if any(tag_id < 0 for tag_id in request.tag_ids):
            return await self._fetch_with_sip(request, **_kwargs)
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

        active_filters = [f for f in (request.analysis_filters or []) if self._is_filter_active(f)]

        postgres = self.db.bind is not None and self.db.bind.dialect.name == "postgresql"
        available_plot_aggregates = self._available_plot_aggregates() if postgres else ()
        plot_aggregate = _plot_aggregate_for(request, postgres=postgres) if not active_filters else None
        if plot_aggregate and plot_aggregate[0] not in {entry[1] for entry in available_plot_aggregates}:
            desired_seconds = _interval_seconds(plot_aggregate[1]) or 1
            replacement = min(
                available_plot_aggregates,
                key=lambda entry: abs(math.log(entry[0] / desired_seconds)),
                default=None,
            )
            plot_aggregate = (replacement[1], replacement[2]) if replacement else None
        dynamic_requested = postgres and request.target_points_per_tag is not None and not active_filters

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

        filter_sql = ""
        filter_params: dict[str, Any] = {}
        if active_filters:
            filter_sql, filter_params = self._build_dynamic_filters(
                request.section_id, active_filters, mode=requested_mode
            )

        effective_target_points: Optional[int] = None
        dynamic_plan: Optional[DynamicPlotPlan] = None
        raw_visual = False
        cache_key: Optional[tuple[Any, ...]] = None
        tag_plans: dict[int, DynamicPlotPlan] = {}
        raw_point_count_by_tag: dict[str, int] = {}
        source_aggregate_by_tag: dict[str, Optional[str]] = {}
        source_bucket_seconds_by_tag: dict[str, Optional[int]] = {}
        display_bucket_seconds_by_tag: dict[str, Optional[int]] = {}
        returned_points_by_tag: dict[str, int] = {}

        if dynamic_requested:
            effective_target_points = min(
                max(100, request.target_points_per_tag or settings.pi_query_visual_default_points_per_tag),
                settings.pi_query_visual_max_points_per_tag,
                max(1, settings.pi_query_visual_max_total_points // len(tags)),
            )
            cache_key = (
                "timescaledb-dynamic-v2",
                tuple(sorted(request.tag_ids)),
                request.start_time.astimezone(timezone.utc),
                effective_end.astimezone(timezone.utc),
                effective_target_points,
                request.max_count,
                requested_mode,
                request.resolution_mode,
                tuple(sorted((f.variable_type_id, f.min, f.max, f.expression, f.value) for f in active_filters)),
            )
            if not bool(_kwargs.get("refresh")):
                cached = _timescaledb_query_cache.get(cache_key)
                if cached is not None:
                    # LruCache.get already returns an isolated deep copy.
                    result = cached
                    if result.query_execution is not None:
                        result.query_execution.cache_hit = True
                    return result

            # Resolution is planned independently PER TAG so adding tags never degrades another tag's detail
            for tag in tags:
                tag_raw_count = self._count_qualified_raw_points(
                    [tag.id],
                    request.start_time,
                    effective_end,
                    settings.timescaledb_dynamic_raw_point_limit,
                )
                plan = _dynamic_plot_plan(
                    effective_end - request.start_time,
                    effective_target_points,
                    tag_raw_count,
                    settings.timescaledb_dynamic_raw_point_limit,
                    available_plot_aggregates,
                )
                tag_plans[tag.id] = plan
                raw_point_count_by_tag[tag.pi_tag_name] = tag_raw_count
                source_aggregate_by_tag[tag.pi_tag_name] = plan.view_name if not plan.use_raw else "pi_samples_timescale"
                source_bucket_seconds_by_tag[tag.pi_tag_name] = plan.source_bucket_seconds
                display_bucket_seconds_by_tag[tag.pi_tag_name] = plan.display_bucket_seconds

            # Backwards compatibility plan
            dynamic_plan = next(iter(tag_plans.values()), None)
            raw_visual = all(p.use_raw for p in tag_plans.values())
            primary_plan = next((p for p in tag_plans.values() if not p.use_raw), dynamic_plan)
            if primary_plan is not None and primary_plan.view_name is not None and primary_plan.display_bucket_seconds is not None:
                plot_aggregate = (
                    primary_plan.view_name,
                    _format_interval(primary_plan.display_bucket_seconds) or "1s",
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
        source_segments: list[dict[str, Any]] = []
        uncovered_intervals: list[dict[str, Any]] = []
        total_returned_points = 0
        total_real_points = 0
        total_null_points = 0

        for tag in tags:
            tag_plan = tag_plans.get(tag.id)
            if dynamic_requested and tag_plan is not None:
                if tag_plan.use_raw:
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
                    if len(all_points) > effective_target_points:
                        points = self._downsample_for_visual(all_points, effective_target_points, target_intervals=effective_target_points)
                    else:
                        points = all_points
                else:
                    plot_result = self._get_from_plot_coverage_aware(
                        tag.id,
                        request.start_time,
                        effective_end,
                        tag_plan.view_name,
                        display_bucket_seconds=tag_plan.display_bucket_seconds,
                    )
                    points = plot_result.points
                    source_segments.extend(plot_result.segments)
                    uncovered_intervals.extend(plot_result.uncovered)
                returned_points_by_tag[tag.pi_tag_name] = len(points)
            elif raw_visual:
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
                tag_target = effective_target_points or 2000
                if len(all_points) > tag_target:
                    points = self._downsample_for_visual(all_points, tag_target, target_intervals=tag_target)
                else:
                    points = all_points
                returned_points_by_tag[tag.pi_tag_name] = len(points)
            elif plot_aggregate:
                plot_result = self._get_from_plot_coverage_aware(
                    tag.id,
                    request.start_time,
                    effective_end,
                    plot_aggregate[0],
                    display_bucket_seconds=(
                        dynamic_plan.display_bucket_seconds if dynamic_plan is not None else None
                    ),
                )
                points = plot_result.points
                source_segments.extend(plot_result.segments)
                uncovered_intervals.extend(plot_result.uncovered)
                returned_points_by_tag[tag.pi_tag_name] = len(points)
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
                points = self._get_from_db(
                    tag.id,
                    covered,
                    requested_mode,
                    filter_sql=filter_sql,
                    filter_params=filter_params,
                )
                returned_points_by_tag[tag.pi_tag_name] = len(points)
            if not dynamic_requested and request.max_count and len(points) > request.max_count:
                # Manual (non-dynamic) mode keeps its documented max_count
                # contract; the dynamic path never reaches this truncation.
                points = points[:request.max_count]
            total_returned_points += len(points)
            total_real_points += sum(point.value is not None for point in points)
            total_null_points += sum(point.value is None for point in points)
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

        partial = bool(uncovered_intervals)
        has_cagg = bool(plot_aggregate) or any(not p.use_raw for p in tag_plans.values())
        has_raw = raw_visual or any(p.use_raw for p in tag_plans.values())
        query_execution: dict[str, Any] = {
            "strategy": "timescaledb_continuous_aggregate" if has_cagg else "timescaledb_direct",
            "source": "timescaledb",
            "effective_source_mode": "RECORDED" if (has_cagg or has_raw) else requested_mode,
            "complete": not partial,
            "partial": partial,
            "status": "PARTIAL" if partial else "COMPLETE",
            "effective_interval": effective_interval,
            "points_returned": total_returned_points,
            "real_points": total_real_points,
            "null_points": total_null_points,
            "source_segments": source_segments,
            "uncovered_intervals": uncovered_intervals,
            "cache_hit": False if dynamic_requested else None,
        }
        if plot_aggregate:
            query_execution.update({
                "plot_aggregate": plot_aggregate[0],
                "sampled": True,
            })
        if dynamic_plan is not None:
            query_execution.update({
                "requested_target_points_per_tag": request.target_points_per_tag,
                "effective_target_points_per_tag": effective_target_points,
                "raw_point_count": sum(raw_point_count_by_tag.values()),
                "dynamic_bucket_seconds": dynamic_plan.display_bucket_seconds,
                "sampled": any(not p.use_raw for p in tag_plans.values()),
                "raw_point_count_by_tag": raw_point_count_by_tag,
                "source_aggregate_by_tag": source_aggregate_by_tag,
                "source_bucket_seconds_by_tag": source_bucket_seconds_by_tag,
                "display_bucket_seconds_by_tag": display_bucket_seconds_by_tag,
                "returned_points_by_tag": returned_points_by_tag,
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

    def _downsample_for_visual(
        self,
        points: list[TimeSeriesPoint],
        max_points: int,
        target_intervals: Optional[int] = None,
    ) -> list[TimeSeriesPoint]:
        """Bucket reduction preserving real event timestamps.

        Each bucket contributes first, min, max and last events with their
        original timestamps; duplicates of the same event are collapsed and
        the result is ordered chronologically (not first->min->max->last).
        """
        if max_points <= 0 or len(points) <= max_points:
            return points
        # Sort a copy: never depend on implicit DB ordering.
        ordered = sorted(points, key=lambda p: p.timestamp)
        start = ordered[0].timestamp
        duration = (ordered[-1].timestamp - start).total_seconds()
        buckets = max(1, target_intervals if target_intervals is not None else max_points // 4)
        if duration <= 0:
            # Degenerate window: keep chronological first/last and extremes
            # with real timestamps; the timestamp map deduplicates events.
            width = 1e-9
        else:
            width = max(duration / buckets, 1e-9)
        selected: dict = {}
        for point in ordered:
            index = min(int((point.timestamp - start).total_seconds() / width), buckets - 1)
            current = selected.get(index)
            if current is None:
                selected[index] = {"first": point, "last": point, "min": point, "max": point}
                continue
            if point.timestamp < current["first"].timestamp:
                current["first"] = point
            if point.timestamp > current["last"].timestamp:
                current["last"] = point
            if isinstance(point.value, (int, float)) and not isinstance(point.value, bool) and (
                not isinstance(current["min"].value, (int, float))
                or isinstance(current["min"].value, bool)
                or point.value < current["min"].value
            ):
                current["min"] = point
            if isinstance(point.value, (int, float)) and not isinstance(point.value, bool) and (
                not isinstance(current["max"].value, (int, float))
                or isinstance(current["max"].value, bool)
                or point.value > current["max"].value
            ):
                current["max"] = point
        unique: dict = {}
        for bucket in selected.values():
            for point in (bucket["first"], bucket["min"], bucket["max"], bucket["last"]):
                unique[point.timestamp] = point
        return [unique[ts] for ts in sorted(unique)]

    @staticmethod
    def _is_filter_active(f: AnalysisFilterRequest) -> bool:
        if f.min is not None or f.max is not None:
            return True
        if f.expression is not None and f.expression.strip() and f.expression.strip() != "ALL":
            return True
        if f.value in ("ON", "OFF"):
            return True
        if f.value is not None and f.value.strip() and f.value.strip() != "ALL":
            return True
        return False

    def _build_dynamic_filters(
        self,
        section_id: Optional[int],
        active_filters: list[AnalysisFilterRequest],
        mode: str,
    ) -> tuple[str, dict[str, Any]]:
        if not section_id:
            raise ValidationError("section_id é obrigatório para filtros dinâmicos de análise.")

        filter_clauses: list[str] = []
        filter_params: dict[str, Any] = {}

        for idx, f in enumerate(active_filters):
            analysis_tag = (
                self.db.query(SectionAnalysisTag)
                .filter(
                    SectionAnalysisTag.section_id == section_id,
                    SectionAnalysisTag.variable_type_id == f.variable_type_id,
                )
                .first()
            )
            if not analysis_tag:
                raise ValidationError(
                    f"Tipo de variável (ID {f.variable_type_id}) não está vinculado à seção {section_id}.",
                    details={"variable_type_id": f.variable_type_id, "section_id": section_id},
                )

            filter_tag_id = analysis_tag.pi_tag_id
            vtype = analysis_tag.variable_type
            data_type = vtype.filter_data_type if vtype else VariableFilterDataType.REAL

            tag_param = f"f_tag_{idx}"
            filter_params[tag_param] = filter_tag_id

            if data_type == VariableFilterDataType.REAL:
                if f.min is not None and f.max is not None and f.min > f.max:
                    raise ValidationError("Valor mínimo não pode ser maior que o valor máximo.")
                real_clauses = ["value_double IS NOT NULL"]
                if f.min is not None:
                    pname = f"f_min_{idx}"
                    filter_params[pname] = f.min
                    real_clauses.append(f"value_double >= :{pname}")
                if f.max is not None:
                    pname = f"f_max_{idx}"
                    filter_params[pname] = f.max
                    real_clauses.append(f"value_double <= :{pname}")
                if f.min is None and f.max is None:
                    val_str = (f.value or f.expression or "").strip()
                    if val_str and val_str != "ALL":
                        try:
                            pname = f"f_exact_{idx}"
                            filter_params[pname] = float(val_str)
                            real_clauses.append(f"value_double = :{pname}")
                        except ValueError:
                            pass
                if len(real_clauses) == 1:
                    continue
                cond_sql = " AND ".join(real_clauses)

            elif data_type == VariableFilterDataType.DIGITAL:
                val = (f.value or f.expression or "").strip().upper()
                if val == "ON":
                    cond_sql = "value_boolean IS TRUE"
                elif val == "OFF":
                    cond_sql = "value_boolean IS FALSE"
                else:
                    continue

            elif data_type == VariableFilterDataType.STRING:
                expr = (f.value if (f.value and f.value != "ALL") else (f.expression or "")).strip()
                if not expr or expr == "ALL":
                    continue
                try:
                    ast_tokens = parse_string_filter(expr)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc

                str_clauses: list[str] = []
                for j, token in enumerate(ast_tokens):
                    if isinstance(token, ExactMatch):
                        pname = f"f_str_{idx}_{j}"
                        filter_params[pname] = token.value
                        str_clauses.append(f"LOWER(value_text) = LOWER(:{pname})")
                    elif isinstance(token, WildcardMatch):
                        pname = f"f_like_{idx}_{j}"
                        filter_params[pname] = token.pattern
                        str_clauses.append(f"LOWER(value_text) LIKE LOWER(:{pname}) ESCAPE '\\'")
                    elif isinstance(token, RangeMatch):
                        if token.values is not None:
                            val_pnames = []
                            for k, v in enumerate(token.values):
                                vpname = f"f_rng_{idx}_{j}_{k}"
                                filter_params[vpname] = v.lower()
                                val_pnames.append(f":{vpname}")
                            str_clauses.append(f"LOWER(value_text) IN ({', '.join(val_pnames)})")
                        else:
                            range_parts = []
                            if token.prefix:
                                pname = f"f_rpref_{idx}_{j}"
                                escaped = token.prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                                filter_params[pname] = escaped
                                range_parts.append(f"LOWER(value_text) LIKE LOWER(:{pname}) ESCAPE '\\'")
                            if token.padding > 0:
                                plen_name = f"f_rlen_{idx}_{j}"
                                filter_params[plen_name] = len(token.prefix) + token.padding
                                range_parts.append(f"LENGTH(value_text) = :{plen_name}")
                            pos_name = f"f_rpos_{idx}_{j}"
                            filter_params[pos_name] = len(token.prefix) + 1
                            s_name = f"f_rstart_{idx}_{j}"
                            filter_params[s_name] = token.start
                            e_name = f"f_rend_{idx}_{j}"
                            filter_params[e_name] = token.end
                            range_parts.append(f"CAST(SUBSTR(value_text, :{pos_name}) AS INTEGER) BETWEEN :{s_name} AND :{e_name}")
                            str_clauses.append(f"({' AND '.join(range_parts)})")

                if str_clauses:
                    cond_sql = f"value_text IS NOT NULL AND ({' OR '.join(str_clauses)})"
                else:
                    continue
            else:
                continue

            subquery = f"""
                AND ts IN (
                    SELECT ts FROM pi_samples_timescale
                    WHERE tag_id = :{tag_param}
                      AND source_mode = :mode
                      AND ts >= :start AND ts < :end
                      AND ({cond_sql})
                )
            """
            filter_clauses.append(subquery)

        return "\n".join(filter_clauses), filter_params

    def _get_from_db(
        self,
        tag_id: int,
        intervals: list[tuple[datetime, datetime]],
        mode: str,
        filter_sql: str = "",
        filter_params: Optional[dict[str, Any]] = None,
    ) -> list[TimeSeriesPoint]:
        if not intervals:
            return []
        points: list[TimeSeriesPoint] = []
        for start, end in intervals:
            params = {"tag_id": tag_id, "mode": mode, "start": start, "end": end}
            if filter_params:
                params.update(filter_params)
            rows = self.db.execute(text(
                f"""
                SELECT ts, value_double, value_boolean, value_text, value_type,
                       good, questionable, substituted
                FROM pi_samples_timescale
                WHERE tag_id = :tag_id AND source_mode = :mode
                  AND ts >= :start AND ts < :end
                  {filter_sql}
                ORDER BY ts ASC
                """
            ), params).fetchall()
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
        """Read only buckets that contain real qualified samples.

        Missing materialization and real event gaps are deliberately absent
        here.  The caller adds a minimal null marker at discontinuities; it
        never manufactures numeric values.
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
            WITH populated AS (
              SELECT
                time_bucket(INTERVAL '{interval}', bucket, origin := CAST(:start AS timestamptz)) AS bucket,
                min(min_value) AS min_value,
                max(max_value) AS max_value,
                first(first_value, bucket) FILTER (WHERE sample_count > 0) AS first_value,
                last(last_value, bucket) FILTER (WHERE sample_count > 0) AS last_value,
                {_WEIGHTED_PLOT_AVERAGE_SQL} AS avg_value,
                min(first_ts) AS first_ts,
                max(last_ts) AS last_ts,
                sum(sample_count) AS sample_count
              FROM {view_name}
              WHERE tag_id = :tag_id
                AND bucket >= CAST(:start AS timestamptz)
                AND bucket < CAST(:end AS timestamptz)
              GROUP BY time_bucket(INTERVAL '{interval}', bucket, origin := CAST(:start AS timestamptz))
            ), extrema AS (
              SELECT
                populated.bucket,
                min(sample.ts) FILTER (WHERE sample.value_double = populated.min_value) AS min_ts,
                min(sample.ts) FILTER (WHERE sample.value_double = populated.max_value) AS max_ts
              FROM populated
              JOIN pi_samples_timescale AS sample
                ON time_bucket(INTERVAL '{interval}', sample.ts, origin := CAST(:start AS timestamptz)) = populated.bucket
              WHERE populated.sample_count > 0
                AND sample.tag_id = :tag_id
                AND sample.source_mode = 'RECORDED'
                AND sample.value_type IN ('double', 'float', 'int')
                AND sample.value_double IS NOT NULL
                AND sample.good IS TRUE
                AND sample.questionable IS FALSE
                AND sample.substituted IS FALSE
                AND sample.ts >= CAST(:start AS timestamptz)
                AND sample.ts < CAST(:end AS timestamptz)
              GROUP BY populated.bucket
            )
            SELECT
              populated.*,
              extrema.min_ts,
              extrema.max_ts
            FROM populated
            LEFT JOIN extrema ON extrema.bucket = populated.bucket
            ORDER BY populated.bucket ASC
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
                is_gapfilled=False,
                plot_min_ts=row[9],
                plot_max_ts=row[10],
                has_previous_value=None,
            ))
        return points

    def _get_from_plot_coverage_aware(
        self,
        tag_id: int,
        start: datetime,
        end: datetime,
        preferred_view: str,
        *,
        display_bucket_seconds: Optional[int] = None,
    ) -> PlotReadResult:
        """Compose a preferred CAGG with coarser historical CAGGs.

        Each source is used only from its first real bucket onward.  Earlier
        history falls back to progressively coarser materialized aggregates.
        Any uncovered prefix/suffix is explicit and forces PARTIAL.
        """
        installed = list(self._available_plot_aggregates())
        by_name = {name: (seconds, label) for seconds, name, label in installed}
        if preferred_view not in by_name:
            return PlotReadResult([], [], [{"tag_id": tag_id, "start": start, "end": end, "reason": "aggregate_unavailable"}])
        preferred_seconds = by_name[preferred_view][0]
        candidates = [(s, n, l) for s, n, l in installed if s >= preferred_seconds]
        candidates.sort(key=lambda item: item[0])
        cursor = start
        collected: list[tuple[TimeSeriesPoint, int]] = []
        segments: list[dict[str, Any]] = []

        # Find real bounds once. A tag without buckets is not considered
        # covered merely because the aggregate has a global watermark.
        bounds: dict[str, tuple[datetime, datetime] | None] = {}
        for _, name, _ in candidates:
            row = self.db.execute(text(f"""
                SELECT min(bucket), max(bucket)
                FROM {name}
                WHERE tag_id = :tag_id AND bucket >= :start AND bucket < :end
            """), {"tag_id": tag_id, "start": start, "end": end}).one()
            bounds[name] = (row[0], row[1]) if row[0] is not None else None

        # Plan coverage segments from finest (preferred) to coarsest:
        # Finer preferred data takes precedence for its entire covered range.
        # Coarser sources cover older history only where the finer source has no data.
        uncovered_intervals: list[tuple[datetime, datetime]] = [(start, end)]
        planned_segments: list[tuple[datetime, datetime, int, str, str]] = []

        for seconds, name, label in candidates:
            bound = bounds.get(name)
            if not bound or bound[0] is None:
                continue
            c_start, c_end = bound
            cov_end = min(end, c_end + timedelta(seconds=seconds))
            new_uncovered: list[tuple[datetime, datetime]] = []
            for u_start, u_end in uncovered_intervals:
                seg_start = max(u_start, c_start)
                seg_end = min(u_end, cov_end)
                if seg_start < seg_end:
                    planned_segments.append((seg_start, seg_end, seconds, name, label))
                    if u_start < seg_start:
                        new_uncovered.append((u_start, seg_start))
                    if seg_end < u_end:
                        new_uncovered.append((seg_end, u_end))
                else:
                    new_uncovered.append((u_start, u_end))
            uncovered_intervals = new_uncovered

        # Any interval not covered by any materialized aggregate falls back to bounded raw plot
        for u_start, u_end in uncovered_intervals:
            if u_start < u_end:
                raw_bucket = max(preferred_seconds, int(display_bucket_seconds or preferred_seconds))
                raw_points = self._get_from_raw_plot(tag_id, u_start, u_end, raw_bucket)
                if raw_points:
                    collected.extend((point, raw_bucket) for point in raw_points)
                    segments.append({
                        "tag_id": tag_id,
                        "start": u_start,
                        "end": u_end,
                        "source": "pi_samples_timescale",
                        "interval": _format_interval(raw_bucket),
                    })

        # Query planned CAGG segments
        planned_segments.sort(key=lambda item: item[0])
        for seg_start, seg_end, seconds, name, label in planned_segments:
            read_bucket = display_bucket_seconds if name == preferred_view else seconds
            points = self._get_from_plot(tag_id, seg_start, seg_end, name, display_bucket_seconds=read_bucket)
            if not points:
                continue
            collected.extend((point, int(read_bucket or seconds)) for point in points)
            segments.append({
                "tag_id": tag_id,
                "start": seg_start,
                "end": seg_end,
                "source": name,
                "interval": _format_interval(read_bucket),
            })
            cursor = max(cursor, seg_end)

        collected = list({point.timestamp: (point, bucket) for point, bucket in collected}.values())
        collected.sort(key=lambda item: item[0].timestamp)
        uncovered: list[dict[str, Any]] = []
        if not collected:
            uncovered.append({"tag_id": tag_id, "start": start, "end": end, "reason": "no_materialized_buckets"})
            return PlotReadResult([], segments, uncovered)
        if collected[0][0].timestamp > start:
            uncovered.append({"tag_id": tag_id, "start": start, "end": collected[0][0].timestamp, "reason": "no_confirmed_source"})
        if collected[-1][0].timestamp + timedelta(seconds=collected[-1][1]) < end:
            uncovered.append({"tag_id": tag_id, "start": collected[-1][0].timestamp + timedelta(seconds=collected[-1][1]), "end": end, "reason": "no_confirmed_source"})

        # One null marker per discontinuity is enough for ECharts to break the
        # line. Do not materialize every empty display bucket.
        with_markers: list[TimeSeriesPoint] = []
        previous_bucket: Optional[int] = None
        for point, bucket_seconds in collected:
            threshold = max(previous_bucket or bucket_seconds, bucket_seconds) * 1.5
            if with_markers and (point.timestamp - with_markers[-1].timestamp).total_seconds() > threshold:
                marker_ts = with_markers[-1].timestamp + timedelta(microseconds=1)
                with_markers.append(TimeSeriesPoint(timestamp=marker_ts, value=None, good=False))
            with_markers.append(point)
            previous_bucket = bucket_seconds
        return PlotReadResult(with_markers, segments, uncovered)

    def _get_from_raw_plot(
        self, tag_id: int, start: datetime, end: datetime, bucket_seconds: int
    ) -> list[TimeSeriesPoint]:
        """Bounded raw fallback aggregated in SQL without gap filling."""
        interval = f"{max(1, bucket_seconds)} seconds"
        rows = self.db.execute(text(f"""
            SELECT time_bucket(INTERVAL '{interval}', ts, origin := CAST(:start AS timestamptz)) AS bucket,
                   min(value_double), max(value_double),
                   first(value_double, ts), last(value_double, ts),
                   avg(value_double), min(ts), max(ts), count(*)
            FROM pi_samples_timescale
            WHERE tag_id = :tag_id
              AND ts >= :start AND ts < :end
              AND source_mode = 'RECORDED'
              AND value_type IN ('double', 'float', 'int')
              AND value_double IS NOT NULL
              AND good IS TRUE AND questionable IS FALSE AND substituted IS FALSE
            GROUP BY time_bucket(INTERVAL '{interval}', ts, origin := CAST(:start AS timestamptz))
            ORDER BY bucket
        """), {"tag_id": tag_id, "start": start, "end": end}).fetchall()
        return [TimeSeriesPoint(
            timestamp=row[0], value=float(row[5]),
            plot_min=float(row[1]), plot_max=float(row[2]),
            plot_first=float(row[3]), plot_last=float(row[4]), plot_avg=float(row[5]),
            plot_first_ts=row[6], plot_last_ts=row[7], plot_sample_count=int(row[8]),
            is_gapfilled=False,
        ) for row in rows]

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
