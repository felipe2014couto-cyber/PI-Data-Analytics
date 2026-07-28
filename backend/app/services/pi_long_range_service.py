"""Long-range query service with adaptive chunking, global concurrency,
automatic interval, visual sampling, streaming CSV export,
WebId cache, visual cache, and StreamSet batch support."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import (
    NotFoundError,
    PiNotConfiguredError,
    QueryCancelledError,
    QueryLimitExceeded,
    QueryLimitExceededError,
    TagInactiveError,
    TimeRangeInvalidError,
)
from app.integrations.pi.errors import (
    PiIntegrationError,
    PiTagNotFoundError,
)
from app.integrations.pi.manager import get_pi_data_provider
from app.integrations.pi.provider import (
    PiDataProvider,
    PiValue,
)
from app.integrations.pi.webapi_provider import get_global_semaphore
from app.models.pi_tag import PiTag
from app.repositories.pi_tag_repository import PiTagRepository
from app.schemas.pi import (
    QueryExecutionMetadata,
    TimeSeries,
    TimeSeriesPoint,
    TimeSeriesRequest,
    TimeSeriesSeries,
)
from app.services.cache import VisualCache, VisualCacheKey, WebIdCache, _webid_cache_key
from app.services.pi_query_planner import (
    QueryPlan,
    build_plan_for_visual,
    compute_interpolated_chunks,
    estimate_interpolated_points,
    split_chunk,
    split_period_into_chunks,
    validate_period,
    validate_visual_budget,
)
from app.services.query_registry import get_query_registry
from app.services.streamset_client import (
    build_web_ids_version,
    detect_missing_series,
    fetch_recorded_streamsets_batch,
    fetch_streamset_batch,
)
from app.services.timing import QueryTimings, measure

logger = logging.getLogger("pi_analytics_data.service.long_range")

_webid_cache = WebIdCache(
    max_size=settings.pi_cache_webid_max_entries,
    default_ttl_seconds=settings.pi_cache_webid_ttl_seconds,
)
_visual_cache = VisualCache(
    max_entries=settings.pi_cache_visual_max_entries,
    max_total_points=settings.pi_cache_visual_max_total_points,
    max_points_per_entry=settings.pi_cache_visual_max_points_per_entry,
    recent_ttl_seconds=settings.pi_cache_visual_recent_ttl_seconds,
    historical_ttl_seconds=settings.pi_cache_visual_historical_ttl_seconds,
    recent_window_seconds=settings.pi_cache_visual_recent_window_seconds,
)


class PiLongRangeService:
    """Service for long-range queries with chunking, concurrency, and sampling."""

    def __init__(self, db, provider: Optional[PiDataProvider] = None) -> None:
        self.db = db
        self.provider = provider
        self.repo = PiTagRepository(db)

    def _resolve_provider(self) -> PiDataProvider:
        if self.provider is None:
            self.provider = get_pi_data_provider()
        if self.provider is None:
            raise PiNotConfiguredError()
        return self.provider

    async def _check_cancelled(self, query_id: Optional[str] = None) -> None:
        if query_id:
            await get_query_registry().check_cancelled(query_id)

    async def _check_pi_limit(
        self, query_id: Optional[str] = None
    ) -> None:
        if not query_id:
            return
        count = await get_query_registry().get_pi_request_count(query_id)
        if count >= settings.pi_visual_max_requests_per_query:
            raise QueryLimitExceeded(
                f"Limite de {settings.pi_visual_max_requests_per_query} requisicoes PI "
                f"atingido para consulta {query_id}.",
                details={"query_id": query_id, "limit": settings.pi_visual_max_requests_per_query},
            )

    def _validate_request(self, request: TimeSeriesRequest) -> None:
        validate_period(request.start_time, request.end_time)
        if request.mode == "interpolated" and not request.interval:
            raise TimeRangeInvalidError(
                "O intervalo e obrigatorio no modo interpolated.",
                details={"mode": request.mode},
            )

    def _load_tags(self, tag_ids: List[int]) -> List[PiTag]:
        if not tag_ids:
            raise TimeRangeInvalidError(
                "A lista de tag_ids nao pode estar vazia.",
                details={"tag_ids": tag_ids},
            )
        max_tags = settings.pi_query_max_tags
        if len(tag_ids) > max_tags:
            raise QueryLimitExceededError(
                "Quantidade de tags excede o limite configurado.",
                details={"requested": len(tag_ids), "limit": max_tags},
            )
        tags: List[PiTag] = []
        for tag_id in tag_ids:
            tag = self.repo.get(tag_id)
            if tag is None:
                raise NotFoundError(
                    "Tag local nao encontrada.",
                    details={"pi_tag_id": tag_id},
                )
            if not tag.active:
                raise TagInactiveError(
                    "A tag esta inativa e nao pode ser consultada.",
                    details={"pi_tag_id": tag.id},
                )
            tags.append(tag)
        return tags

    async def _ensure_web_id(self, tag: PiTag) -> Optional[str]:
        if tag.pi_web_id:
            return tag.pi_web_id
        provider = self._resolve_provider()
        path = f"\\\\{tag.pi_server}\\{tag.pi_tag_name}"
        key = _webid_cache_key(tag.pi_server, tag.pi_tag_name)

        cached = _webid_cache.peek(tag.pi_server, tag.pi_tag_name)
        if cached is not None:
            return cached

        async def _fetch_webid(_key) -> str:
            point = await provider.resolve_point(path)
            if point is None:
                raise PiTagNotFoundError()
            tag.pi_web_id = point.web_id
            self.db.commit()
            self.db.refresh(tag)
            return point.web_id

        try:
            return await _webid_cache.resolve(
                tag.pi_server, tag.pi_tag_name, _fetch_webid
            )
        except PiTagNotFoundError:
            return None
        except PiIntegrationError:
            return None

    async def _resolve_web_ids(
        self, tags: List[PiTag], timings: QueryTimings, query_id: Optional[str] = None
    ) -> Tuple[List[Tuple[PiTag, str]], List[dict], Dict[str, str], int, int]:
        web_ids: List[Tuple[PiTag, str]] = []
        errors: List[dict] = []
        web_id_map: Dict[str, str] = {}
        hits = 0
        misses = 0

        with measure() as resolve_timing:
            for tag in tags:
                await self._check_cancelled(query_id)
                cached = _webid_cache.peek(tag.pi_server, tag.pi_tag_name)
                if cached is not None:
                    hits += 1
                    web_ids.append((tag, cached))
                    web_id_map[str(tag.id)] = cached
                    continue
                misses += 1
                wid = await self._ensure_web_id(tag)
                if wid:
                    web_ids.append((tag, wid))
                    web_id_map[str(tag.id)] = wid
                else:
                    errors.append({
                        "tag_id": tag.id,
                        "code": "PI_TAG_NOT_FOUND",
                        "message": "WebId nao disponivel para a tag.",
                    })

        timings.resolve_ms = resolve_timing.elapsed_ms
        return web_ids, errors, web_id_map, hits, misses

    async def fetch_time_series(
        self, request: TimeSeriesRequest, refresh: bool = False, query_id: Optional[str] = None,
        store_cache: bool = True, preserve_all_points: bool = False,
    ) -> TimeSeries:
        self._validate_request(request)
        await self._check_cancelled(query_id)
        tags = self._load_tags(request.tag_ids)
        started_at = time.monotonic()
        timings = QueryTimings()

        resolution_mode = request.resolution_mode or "automatic"
        target_per_tag = request.target_points_per_tag or settings.pi_query_visual_default_points_per_tag
        effective_per_tag, _ = validate_visual_budget(len(tags), target_per_tag)

        logger.info(
            "Query %s started: %d tags, %s - %s, mode=%s, resolution=%s",
            query_id or "?",
            len(tags),
            request.start_time.isoformat(),
            request.end_time.isoformat(),
            request.mode,
            resolution_mode,
        )

        plan = build_plan_for_visual(
            tag_count=len(tags),
            start_time=request.start_time,
            end_time=request.end_time,
            mode=request.mode,
            resolution_mode=resolution_mode,
            interval=request.interval,
            target_points_per_tag=target_per_tag,
        )

        provider = self._resolve_provider()
        semaphore = get_global_semaphore()

        await self._check_cancelled(query_id)
        web_ids, errors, web_id_map, webid_cache_hits, webid_cache_misses = (
            await self._resolve_web_ids(tags, timings, query_id=query_id)
        )

        if not web_ids:
            elapsed = time.monotonic() - started_at
            return TimeSeries(
                start_time=request.start_time.astimezone(timezone.utc),
                end_time=request.end_time.astimezone(timezone.utc),
                mode=request.mode,
                series=[],
                errors=errors,
                query_execution=QueryExecutionMetadata(
                    resolution_mode=resolution_mode,
                    partial=True,
                    duration_ms=int(elapsed * 1000),
                ),
            )

        visual_key = VisualCacheKey(
            data_server=provider.data_server if hasattr(provider, 'data_server') else settings.pi_data_server_name or "",
            tag_ids=tuple(request.tag_ids),
            web_ids_version=build_web_ids_version([w for _, w in web_ids]),
            start_time=request.start_time,
            end_time=request.end_time,
            mode=request.mode,
            interval=request.interval,
            resolution_mode=resolution_mode,
            target_points_per_tag=effective_per_tag,
            max_visual_points_total=settings.pi_query_visual_max_total_points,
            recorded_window_max_points=settings.pi_recorded_window_max_points,
            recorded_group_size=settings.pi_streamset_recorded_max_webids,
        )

        cache_hit = False
        cache_age_ms: Optional[int] = None

        if not refresh:
            cached = _visual_cache.peek(visual_key)
            if cached is not None:
                cache_ms = int((time.monotonic() - started_at) * 1000)
                cached.query_execution.cache_hit = True
                cached.query_execution.cache_age_ms = cache_ms
                cached.query_execution.webid_cache_hits = webid_cache_hits
                cached.query_execution.webid_cache_misses = webid_cache_misses
                cached.query_execution.query_id = query_id
                logger.info("Query %s cache hit (%d ms)", query_id or "?", cache_ms)
                return cached

        await self._check_cancelled(query_id)
        series_list: List[TimeSeriesSeries] = []
        total_pi_requests = 0
        total_subdivided = 0
        total_visual_points = 0
        total_retries = 0
        all_sampled = False
        all_partial = False
        streamset_used = False
        streamset_mode: Optional[str] = None
        batch_count = 0
        batch_size = 0
        individual_fallback = 0
        recorded_metrics = None

        with measure() as fetch_timing:
            if request.mode == "recorded" and hasattr(provider, "_safe_request") and hasattr(provider, "base_url"):
                recorded_result = await fetch_recorded_streamsets_batch(
                    [wid for _, wid in web_ids],
                    request.start_time,
                    request.end_time,
                    provider,
                    query_id=query_id,
                    cancel_check=(lambda: self._check_cancelled(query_id)),
                )
                recorded_metrics = recorded_result.metrics
                total_pi_requests = recorded_metrics.pi_http_requests
                total_subdivided = recorded_metrics.window_split_count
                total_retries = recorded_metrics.retry_count
                streamset_used = recorded_metrics.streamset_used
                streamset_mode = "recorded" if streamset_used else None
                batch_count = recorded_metrics.batch_count
                batch_size = settings.pi_batch_max_requests
                individual_fallback = recorded_metrics.individual_fallback_requests
                all_partial = recorded_metrics.partial or bool(recorded_result.errors)

                for tag, wid in web_ids:
                    await self._check_cancelled(query_id)
                    if wid in recorded_result.errors:
                        exc = recorded_result.errors[wid]
                        errors.append({
                            "tag_id": tag.id,
                            "code": exc.code,
                            "message": exc.safe_message,
                        })
                        continue
                    exact_values = sorted(
                        recorded_result.values.get(wid, []), key=lambda value: value.timestamp
                    )
                    exact_values = _remove_boundary_duplicates(exact_values)
                    series = self._build_series(tag, request, exact_values)
                    series.source_point_count = len(exact_values)
                    series.returned_point_count = len(exact_values)
                    series.sampled = False
                    series.truncated = wid in recorded_result.truncated_web_ids
                    series.chunk_count = None
                    series_list.append(series)
                    total_visual_points += len(exact_values)
            elif request.mode == "interpolated" and len(web_ids) > 1:
                interval = plan.effective_interval or request.interval or "1m"
                streamset_mode = "interpolated"
                stream_results, req_count, used = await fetch_streamset_batch(
                    [w for _, w in web_ids],
                    request.start_time,
                    request.end_time,
                    "interpolated",
                    interval,
                    settings.pi_query_chunk_max_points,
                    provider,
                )
                streamset_used = used
                if used:
                    batch_count = max(1, (len(web_ids) + settings.pi_query_streamset_batch_size - 1) // settings.pi_query_streamset_batch_size)
                    batch_size = settings.pi_query_streamset_batch_size
                    total_pi_requests += req_count
                    if query_id:
                        for _ in range(req_count):
                            await get_query_registry().increment_pi_requests(query_id)
                            await self._check_pi_limit(query_id)
                    missing = detect_missing_series(
                        [w for _, w in web_ids], stream_results
                    )
                    for tag, wid in web_ids:
                        await self._check_cancelled(query_id)
                        if wid in stream_results and stream_results[wid]:
                            deduped = _remove_boundary_duplicates(stream_results[wid])
                            source_count = len(deduped)
                            target = plan.estimated_points_per_chunk or settings.pi_query_visual_default_points_per_tag
                            sampled_flag = False
                            if not preserve_all_points and len(deduped) > target:
                                sampled_flag = True
                                deduped = _sample_series(deduped, target)
                            series = self._build_series(tag, request, deduped)
                            series.source_point_count = source_count
                            series.returned_point_count = len(deduped)
                            series.sampled = sampled_flag
                            series_list.append(series)
                            total_visual_points += len(deduped)
                            if sampled_flag:
                                all_sampled = True
                        elif wid in missing:
                            individual_fallback += 1
                            total_pi_requests += 1
                            if query_id:
                                await get_query_registry().increment_pi_requests(query_id)
                                await self._check_pi_limit(query_id)
                            async with semaphore:
                                try:
                                    response = await provider.get_interpolated_values(
                                        wid,
                                        request.start_time,
                                        request.end_time,
                                        interval=interval,
                                        max_count=settings.pi_query_chunk_max_points,
                                    )
                                except PiIntegrationError:
                                    errors.append({
                                        "tag_id": tag.id,
                                        "code": "PI_TAG_NOT_FOUND",
                                        "message": "Serie ausente no StreamSet e falha no fallback.",
                                    })
                                    all_partial = True
                                    continue
                            deduped = _remove_boundary_duplicates(response.values)
                            source_count = len(deduped)
                            target = plan.estimated_points_per_chunk or settings.pi_query_visual_default_points_per_tag
                            sampled_flag = False
                            if not preserve_all_points and len(deduped) > target:
                                sampled_flag = True
                                deduped = _sample_series(deduped, target)
                            series = self._build_series(tag, request, deduped)
                            series.source_point_count = source_count
                            series.returned_point_count = len(deduped)
                            series.sampled = sampled_flag
                            series_list.append(series)
                            total_visual_points += len(deduped)
                            if sampled_flag:
                                all_sampled = True
                            if wid in web_id_map:
                                logger.info(
                                    "StreamSet missing series for webId %s, individual fallback succeeded",
                                    wid
                                )
                else:
                    for tag, wid in web_ids:
                        await self._check_cancelled(query_id)
                        try:
                            series, pi_req_count, subdivided, sampled, truncated = (
                                await self._fetch_interpolated_visual(
                                    tag, wid, request, plan, semaphore, query_id=query_id,
                                    preserve_all_points=preserve_all_points,
                                )
                            )
                            total_pi_requests += pi_req_count
                            total_subdivided += subdivided
                            total_visual_points += len(series.points)
                            if sampled:
                                all_sampled = True
                            if truncated:
                                all_partial = True
                                series.truncated = True
                            series_list.append(series)
                        except PiIntegrationError as exc:
                            errors.append({
                                "tag_id": tag.id,
                                "code": exc.code,
                                "message": exc.safe_message,
                            })
                            all_partial = True
            else:
                for tag, wid in web_ids:
                    await self._check_cancelled(query_id)
                    try:
                        if request.mode == "recorded":
                            series, pi_req_count, subdivided, sampled, truncated = (
                                await self._fetch_recorded_visual(
                                    tag, wid, request, plan, semaphore, query_id=query_id,
                                    preserve_all_points=preserve_all_points,
                                )
                            )
                        else:
                            series, pi_req_count, subdivided, sampled, truncated = (
                                await self._fetch_interpolated_visual(
                                    tag, wid, request, plan, semaphore, query_id=query_id,
                                    preserve_all_points=preserve_all_points,
                                )
                            )
                        total_pi_requests += pi_req_count
                        total_subdivided += subdivided
                        total_visual_points += len(series.points)
                        if sampled:
                            all_sampled = True
                        if truncated:
                            all_partial = True
                            series.truncated = True
                        series_list.append(series)
                    except PiIntegrationError as exc:
                        errors.append({
                            "tag_id": tag.id,
                            "code": exc.code,
                            "message": exc.safe_message,
                        })
                        all_partial = True
                    except Exception:
                        logger.exception("Erro inesperado ao consultar serie temporal.")
                        errors.append({
                            "tag_id": tag.id,
                            "code": "INTERNAL_ERROR",
                            "message": "Falha ao consultar a serie temporal.",
                        })
                        all_partial = True

        timings.fetch_ms = fetch_timing.elapsed_ms

        total_ms = (time.monotonic() - started_at) * 1000
        timings.total_ms = total_ms

        metadata = QueryExecutionMetadata(
            strategy=(recorded_metrics.strategy if recorded_metrics else None),
            resolution_mode=resolution_mode,
            requested_target_points_per_tag=target_per_tag,
            effective_target_points_per_tag=effective_per_tag,
            effective_interval=plan.effective_interval,
            chunk_count=plan.total_chunks,
            subdivided_chunk_count=total_subdivided,
            pi_request_count=total_pi_requests,
            visual_total_points=total_visual_points,
            sampled=all_sampled,
            partial=all_partial,
            duration_ms=int(total_ms),
            cache_hit=cache_hit,
            cache_age_ms=cache_age_ms,
            webid_cache_hits=webid_cache_hits,
            webid_cache_misses=webid_cache_misses,
            streamset_used=streamset_used or None,
            streamset_mode=streamset_mode,
            batch_count=batch_count if (recorded_metrics or streamset_used) else None,
            batch_size=batch_size if (recorded_metrics or streamset_used) else None,
            individual_fallback_requests=individual_fallback if (recorded_metrics or streamset_used) else None,
            retry_count=total_retries or None,
            batch_used=(recorded_metrics.batch_used if recorded_metrics else None),
            streamset_group_count=(recorded_metrics.streamset_group_count if recorded_metrics else None),
            batch_subrequest_count=(recorded_metrics.batch_subrequest_count if recorded_metrics else None),
            initial_window_count=(recorded_metrics.initial_window_count if recorded_metrics else None),
            window_split_count=(recorded_metrics.window_split_count if recorded_metrics else None),
            pi_http_requests=(recorded_metrics.pi_http_requests if recorded_metrics else total_pi_requests),
            pi_points_received=(recorded_metrics.pi_points_received if recorded_metrics else None),
            points_returned=total_visual_points,
            rate_limit_count=(recorded_metrics.rate_limit_count if recorded_metrics else None),
            complete=not all_partial,
            truncated=(recorded_metrics.truncated if recorded_metrics else any(s.truncated for s in series_list)),
            queue_wait_ms=timings.queue_wait_ms or None,
            resolve_ms=round(timings.resolve_ms, 1) if timings.resolve_ms else None,
            fetch_ms=round(timings.fetch_ms, 1) if timings.fetch_ms else None,
            processing_ms=round(timings.processing_ms, 1) if timings.processing_ms else None,
            total_ms=round(timings.total_ms, 1) if timings.total_ms else None,
            query_id=query_id,
        )

        logger.info(
            "Query %s completed in %.1fs (%d PI requests, %d visual points, %d errors)",
            query_id or "?",
            total_ms / 1000,
            total_pi_requests,
            total_visual_points,
            len(errors),
        )

        await self._check_cancelled(query_id)
        result = TimeSeries(
            start_time=request.start_time.astimezone(timezone.utc),
            end_time=request.end_time.astimezone(timezone.utc),
            mode=request.mode,
            series=series_list,
            errors=errors,
            query_execution=metadata,
        )

        await self._check_cancelled(query_id)
        if store_cache and not errors:
            _visual_cache.store(visual_key, result)

        return result

    async def _fetch_recorded_visual(
        self,
        tag: PiTag,
        web_id: str,
        request: TimeSeriesRequest,
        plan: QueryPlan,
        semaphore: asyncio.Semaphore,
        query_id: Optional[str] = None,
        preserve_all_points: bool = False,
    ) -> Tuple[TimeSeriesSeries, int, int, bool, bool]:
        provider = self._resolve_provider()
        all_values: List[PiValue] = []
        pi_request_count = 0
        subdivided_count = 0
        truncated = False

        chunks_to_process = list(plan.chunks)

        while chunks_to_process:
            await self._check_cancelled(query_id)
            chunk = chunks_to_process.pop(0)
            async with semaphore:
                try:
                    if query_id:
                        await get_query_registry().increment_pi_requests(query_id)
                        await self._check_pi_limit(query_id)
                    response = await provider.get_recorded_values(
                        web_id,
                        chunk.start_time,
                        chunk.end_time,
                        max_count=settings.pi_query_chunk_max_points,
                    )
                    pi_request_count += 1
                except PiIntegrationError:
                    raise

            values = response.values
            if len(values) >= settings.pi_query_chunk_max_points:
                if chunk.depth < settings.pi_query_max_split_depth:
                    left, right = split_chunk(chunk)
                    chunks_to_process.insert(0, right)
                    chunks_to_process.insert(0, left)
                    subdivided_count += 1
                else:
                    all_values.extend(values)
                    truncated = True
            else:
                all_values.extend(values)

        all_values.sort(key=lambda v: v.timestamp)
        deduped = _remove_boundary_duplicates(all_values)
        source_count = len(deduped)

        sampled_flag = False
        target = plan.total_estimated_points or settings.pi_query_visual_default_points_per_tag
        if not preserve_all_points and len(deduped) > target:
            sampled_flag = True
            deduped = _sample_series(deduped, target)

        series = self._build_series(tag, request, deduped)
        series.source_point_count = source_count
        series.returned_point_count = len(deduped)
        series.sampled = sampled_flag
        series.truncated = truncated
        series.chunk_count = pi_request_count

        return series, pi_request_count, subdivided_count, sampled_flag, truncated

    async def _fetch_interpolated_visual(
        self,
        tag: PiTag,
        web_id: str,
        request: TimeSeriesRequest,
        plan: QueryPlan,
        semaphore: asyncio.Semaphore,
        query_id: Optional[str] = None,
        preserve_all_points: bool = False,
    ) -> Tuple[TimeSeriesSeries, int, int, bool, bool]:
        provider = self._resolve_provider()
        all_values: List[PiValue] = []
        pi_request_count = 0
        interval = plan.effective_interval or request.interval or "1m"

        chunks = compute_interpolated_chunks(
            request.start_time, request.end_time, interval
        )

        for chunk in chunks:
            await self._check_cancelled(query_id)
            async with semaphore:
                try:
                    if query_id:
                        await get_query_registry().increment_pi_requests(query_id)
                        await self._check_pi_limit(query_id)
                    response = await provider.get_interpolated_values(
                        web_id,
                        chunk.start_time,
                        chunk.end_time,
                        interval=interval,
                        max_count=settings.pi_query_chunk_max_points,
                    )
                    pi_request_count += 1
                except PiIntegrationError:
                    raise
            all_values.extend(response.values)

        deduped = _remove_boundary_duplicates(all_values)
        source_count = len(deduped)

        sampled_flag = False
        visual_target = plan.estimated_points_per_chunk or settings.pi_query_visual_default_points_per_tag
        if not preserve_all_points and len(deduped) > visual_target:
            sampled_flag = True
            deduped = _sample_series(deduped, visual_target)

        series = self._build_series(tag, request, deduped)
        series.source_point_count = source_count
        series.returned_point_count = len(deduped)
        series.sampled = sampled_flag
        series.truncated = False
        series.chunk_count = pi_request_count

        return series, pi_request_count, 0, sampled_flag, False

    def _build_series(
        self,
        tag: PiTag,
        request: TimeSeriesRequest,
        values: List[PiValue],
    ) -> TimeSeriesSeries:
        points = [
            TimeSeriesPoint(
                timestamp=v.timestamp.astimezone(timezone.utc),
                value=v.value,
                good=v.good,
                questionable=v.questionable,
                substituted=v.substituted,
            )
            for v in values
        ]
        equipment = tag.equipment
        section = tag.section
        variable_type = tag.variable_type
        return TimeSeriesSeries(
            tag_id=tag.id,
            tag_name=tag.pi_tag_name,
            display_name=tag.display_name,
            equipment=equipment.code if equipment else None,
            section=section.code if section else None,
            variable_type=variable_type.code if variable_type else None,
            unit=tag.engineering_unit,
            points=points,
        )

    async def export_csv(
        self,
        tag_ids: List[int],
        start_time: datetime,
        end_time: datetime,
        mode: str,
        interval: Optional[str] = None,
        max_count: Optional[int] = None,
    ) -> AsyncIterator[str]:
        validate_period(start_time, end_time)
        tags = self._load_tags(tag_ids)
        provider = self._resolve_provider()
        semaphore = get_global_semaphore()

        header = (
            "TagId;Tag;DisplayName;Timestamp;Value;ValueType;Good;Questionable;Substituted;Unit\r\n"
        )
        yield "\ufeff" + header

        for tag in tags:
            web_id = await self._ensure_web_id(tag)
            if not web_id:
                continue

            if mode == "recorded":
                chunks = split_period_into_chunks(
                    start_time, end_time, settings.pi_query_initial_chunk_days
                )
                chunks_to_process = list(chunks)
                all_values: List[PiValue] = []

                while chunks_to_process:
                    chunk = chunks_to_process.pop(0)
                    async with semaphore:
                        try:
                            response = await provider.get_recorded_values(
                                web_id,
                                chunk.start_time,
                                chunk.end_time,
                                max_count=settings.pi_query_chunk_max_points,
                            )
                        except PiIntegrationError:
                            continue

                    vals = response.values
                    if len(vals) >= settings.pi_query_chunk_max_points and chunk.depth < settings.pi_query_max_split_depth:
                        left, right = split_chunk(chunk)
                        chunks_to_process.insert(0, right)
                        chunks_to_process.insert(0, left)
                    else:
                        all_values.extend(vals)

                all_values.sort(key=lambda v: v.timestamp)
                deduped = _remove_boundary_duplicates(all_values)
            else:
                eff_interval = interval or "1m"
                chunks = compute_interpolated_chunks(start_time, end_time, eff_interval)
                all_values = []
                for chunk in chunks:
                    async with semaphore:
                        try:
                            response = await provider.get_interpolated_values(
                                web_id,
                                chunk.start_time,
                                chunk.end_time,
                                interval=eff_interval,
                                max_count=max_count or settings.pi_query_chunk_max_points,
                            )
                        except PiIntegrationError:
                            continue
                    all_values.extend(response.values)
                deduped = _remove_boundary_duplicates(all_values)

            for v in deduped:
                yield _format_csv_row(tag, v)


def _remove_boundary_duplicates(values: List[PiValue]) -> List[PiValue]:
    if not values:
        return values
    result: List[PiValue] = [values[0]]
    for i in range(1, len(values)):
        prev = values[i - 1]
        curr = values[i]
        if (
            prev.timestamp == curr.timestamp
            and prev.value == curr.value
            and prev.good == curr.good
            and prev.questionable == curr.questionable
            and prev.substituted == curr.substituted
            and prev.units == curr.units
        ):
            continue
        result.append(curr)
    return result


def _sample_series(values: List[PiValue], target: int) -> List[PiValue]:
    if len(values) <= target or target < 2:
        return values

    first_type = _detect_series_type(values)

    if first_type == "numeric":
        return _lttb_sample(values, target)
    elif first_type == "textual":
        return _compact_textual(values, target)
    else:
        return _deterministic_reduce(values, target)


def _detect_series_type(values: List[PiValue]) -> str:
    num_count = 0
    text_count = 0
    for v in values[:100]:
        if isinstance(v.value, (int, float)):
            num_count += 1
        elif isinstance(v.value, (str, bool)):
            text_count += 1
    if num_count > text_count * 2:
        return "numeric"
    elif text_count > num_count * 2:
        return "textual"
    return "mixed"


def _lttb_sample(values: List[PiValue], target: int) -> List[PiValue]:
    if len(values) <= target or target < 3:
        return values

    data = [(v.timestamp.timestamp(), v.value if isinstance(v.value, (int, float)) else 0.0) for v in values]
    sampled_indices = _lttb_indices(data, target)
    return [values[i] for i in sampled_indices]


def _lttb_indices(data: List[Tuple[float, float]], target: int) -> List[int]:
    n = len(data)
    if target >= n:
        return list(range(n))
    if target < 3:
        return [0, n - 1] if target == 2 else [0]

    indices = [0]
    bucket_size = (n - 2) / (target - 2)

    for i in range(1, target - 1):
        bucket_start = int((i - 1) * bucket_size) + 1
        bucket_end = int(i * bucket_size) + 1
        avg_x = 0.0
        avg_y = 0.0
        count = 0
        for j in range(bucket_start, bucket_end):
            if j < n - 1:
                avg_x += data[j][0]
                avg_y += data[j][1]
                count += 1
        if count > 0:
            avg_x /= count
            avg_y /= count
        else:
            avg_x = data[bucket_start][0] if bucket_start < n - 1 else data[n - 2][0]
            avg_y = data[bucket_start][1] if bucket_start < n - 1 else data[n - 2][1]

        point_a = data[indices[-1]]
        max_area = -1.0
        max_j = bucket_start
        for j in range(bucket_start, bucket_end):
            if j >= n - 1:
                break
            point_b = data[j]
            area = abs(
                (avg_x - point_a[0]) * (point_b[1] - point_a[1])
                - (avg_y - point_a[1]) * (point_b[0] - point_a[0])
            )
            if area > max_area:
                max_area = area
                max_j = j
        indices.append(max_j)

    indices.append(n - 1)
    return indices


def _compact_textual(values: List[PiValue], target: int) -> List[PiValue]:
    if len(values) <= target:
        return values

    result: List[PiValue] = [values[0]]
    for v in values[1:-1]:
        if v.value != result[-1].value:
            result.append(v)
    result.append(values[-1])

    if len(result) > target:
        return _deterministic_reduce(result, target)
    return result


def _deterministic_reduce(values: List[PiValue], target: int) -> List[PiValue]:
    if len(values) <= target or target < 2:
        return values
    step = (len(values) - 1) / (target - 1)
    result: List[PiValue] = [values[0]]
    for i in range(1, target - 1):
        idx = int(i * step)
        result.append(values[min(idx, len(values) - 1)])
    result.append(values[-1])
    return result


def _format_csv_row(tag: PiTag, v: PiValue) -> str:
    value_str: str
    if v.value is None:
        value_str = ""
    elif isinstance(v.value, bool):
        value_str = "true" if v.value else "false"
    elif isinstance(v.value, str):
        escaped = v.value.replace('"', '""')
        value_str = f'"{escaped}"'
    else:
        value_str = str(v.value)

    timestamp_str = v.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    unit_str = v.units or tag.engineering_unit or ""
    if v.value is None:
        value_type = "null"
    elif isinstance(v.value, bool):
        value_type = "boolean"
    elif isinstance(v.value, (int, float)):
        value_type = "number"
    else:
        value_type = "string"

    return (
        f"{tag.id};{tag.pi_tag_name};{tag.display_name};"
        f"{timestamp_str};{value_str};{value_type};"
        f"{'true' if v.good else 'false'};"
        f"{'true' if v.questionable else 'false'};"
        f"{'true' if v.substituted else 'false'};"
        f"{unit_str}\r\n"
    )
