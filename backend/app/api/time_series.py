"""Time series endpoints."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_long_range_service, get_pi_service, get_query_registry_dep
from app.core.config import settings as app_settings
from app.core.exceptions import QueryCancelledError, QueryLimitExceededError
from app.schemas.pi import (
    ComparisonContextResult,
    ComparisonMetadata,
    TimeSeries,
    TimeSeriesComparison,
    TimeSeriesComparisonRequest,
    TimeSeriesMode,
    TimeSeriesRequest,
)
from app.services.cache import VisualCache, WebIdCache
from app.services.pi_long_range_service import PiLongRangeService
from app.services.pi_service import PiService
from app.services.query_registry import QueryRegistry, get_query_registry

logger = logging.getLogger("pi_analytics_data.api.time_series")

router = APIRouter(prefix="/time-series", tags=["time-series"])


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _normalize_tag_ids(values: Union[List[int], List[str], None]) -> List[int]:
    if not values:
        return []
    result: List[int] = []
    for value in values:
        if isinstance(value, int):
            result.append(value)
            continue
        text = str(value).strip()
        if not text:
            continue
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            result.append(int(part))
    seen: set[int] = set()
    deduped: List[int] = []
    for tag_id in result:
        if tag_id in seen:
            continue
        seen.add(tag_id)
        deduped.append(tag_id)
    if not deduped:
        return []
    if len(deduped) > app_settings.pi_query_max_tags:
        raise QueryLimitExceededError(
            "Quantidade de tags excede o limite configurado.",
            details={"requested": len(deduped), "limit": app_settings.pi_query_max_tags},
        )
    return deduped


@router.post("/{query_id}/cancel", summary="Cancelar uma consulta em andamento")
async def cancel_time_series(
    query_id: str,
    registry: QueryRegistry = Depends(get_query_registry_dep),
):
    cancelled = await registry.cancel(query_id)
    if not cancelled:
        logger.info("Cancelamento para consulta inexistente/finalizada %s (idempotente, ignorado)", query_id)
    return {"query_id": query_id, "cancelled": cancelled, "message": "Consulta cancelada." if cancelled else "Consulta ja finalizada ou inexistente."}


@router.get("", response_model=TimeSeries, summary="Consultar series temporais no PI Web API")
async def get_time_series(
    tag_ids: List[Union[int, str]] = Query(
        ...,
        description=(
            "IDs das tags cadastradas. Aceita parametros repetidos "
            "(tag_ids=1&tag_ids=2) ou valores separados por virgula "
            "(tag_ids=1,2)."
        ),
    ),
    start_time: str = Query(..., description="Inicio do periodo (ISO 8601)."),
    end_time: str = Query(..., description="Fim do periodo (ISO 8601)."),
    mode: TimeSeriesMode = Query("recorded", description="Tipo de consulta."),
    interval: Optional[str] = Query(None, description="Intervalo (obrigatorio para interpolated)."),
    max_count: Optional[int] = Query(None, ge=1, le=1_000_000),
    resolution_mode: Optional[str] = Query(None, pattern="^(automatic|manual)$"),
    target_points_per_tag: Optional[int] = Query(None, ge=1000, le=50000),
    refresh: bool = Query(False, description="Ignorar cache visual e forçar nova consulta."),
    query_id: Optional[str] = Query(None, description="ID da consulta para cancelamento."),
    service: PiService = Depends(get_pi_service),
    long_service: PiLongRangeService = Depends(get_long_range_service),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> TimeSeries:
    ids = _normalize_tag_ids(tag_ids)
    qid = query_id or str(uuid.uuid4())
    ts_request = TimeSeriesRequest(
        tag_ids=ids,
        start_time=_parse_iso(start_time),
        end_time=_parse_iso(end_time),
        mode=mode,
        interval=interval,
        max_count=max_count,
        resolution_mode=resolution_mode,
        target_points_per_tag=target_points_per_tag,
    )

    if resolution_mode is None and target_points_per_tag is None:
        result = await service.fetch_time_series(ts_request)
        return result

    current_task = asyncio.current_task()
    await registry.register(qid, main_task=current_task)

    try:
        result = await long_service.fetch_time_series(
            ts_request, refresh=refresh, query_id=qid,
        )
        result.query_execution.query_id = qid
        return result
    except asyncio.CancelledError:
        raise QueryCancelledError(f"Consulta {qid} cancelada.")
    finally:
        await registry.unregister(qid)


@router.post("/comparison", response_model=TimeSeriesComparison, summary="Comparar dois contextos de series temporais")
async def compare_time_series(
    payload: TimeSeriesComparisonRequest,
    long_service: PiLongRangeService = Depends(get_long_range_service),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> TimeSeriesComparison:
    qid = payload.query_id or str(uuid.uuid4())
    started = time.monotonic()
    await registry.register(qid, main_task=asyncio.current_task())
    contexts: List[ComparisonContextResult] = []
    points_received: dict[str, int] = {}
    points_returned: dict[str, int] = {}
    durations: dict[str, int] = {}
    strategies: dict[str, Optional[str]] = {}
    cache_hits: dict[str, Optional[bool]] = {}
    pi_requests: dict[str, int] = {}

    try:
        for context in payload.contexts:
            context_started = time.monotonic()
            logger.info(
                "comparison_context_started query_id=%s comparison_type=%s context_id=%s "
                "tag_count=%d start_time=%s end_time=%s",
                qid, payload.comparison_type, context.context_id, len(context.tag_ids),
                context.start_time.isoformat(), context.end_time.isoformat(),
            )
            try:
                request = TimeSeriesRequest(
                    tag_ids=context.tag_ids,
                    start_time=context.start_time,
                    end_time=context.end_time,
                    mode=payload.mode,
                    interval=payload.interval,
                    max_count=payload.max_count,
                    resolution_mode=payload.resolution_mode,
                    target_points_per_tag=payload.target_points_per_tag,
                )
                result = await long_service.fetch_time_series(
                    request,
                    refresh=True,
                    query_id=qid,
                    store_cache=False,
                    preserve_all_points=True,
                )
                for series in result.series:
                    series.context_id = context.context_id
                    series.context_label = context.context_label
                    series.comparison_type = payload.comparison_type
                    series.series_instance_id = (
                        f"{context.context_id}-{series.tag_id}-"
                        f"{int(context.start_time.timestamp())}-{int(context.end_time.timestamp())}"
                    )
                    series.category = series.variable_type
                    series.original_start_time = context.start_time
                    series.original_end_time = context.end_time
                    if payload.comparison_type == "periods":
                        for point in series.points:
                            point.elapsed_ms = int(
                                (point.timestamp - context.start_time).total_seconds() * 1000
                            )
                execution = result.query_execution
                received = execution.pi_points_received if execution else None
                points_received[context.context_id] = received if received is not None else sum(
                    series.source_point_count or len(series.points) for series in result.series
                )
                points_returned[context.context_id] = sum(len(series.points) for series in result.series)
                durations[context.context_id] = int((time.monotonic() - context_started) * 1000)
                strategies[context.context_id] = execution.strategy if execution else None
                cache_hits[context.context_id] = execution.cache_hit if execution else None
                pi_requests[context.context_id] = (
                    (execution.pi_http_requests or execution.pi_request_count or 0) if execution else 0
                )
                complete = not result.errors and not bool(execution and execution.partial)
                contexts.append(ComparisonContextResult(
                    context_id=context.context_id,
                    context_label=context.context_label,
                    start_time=context.start_time,
                    end_time=context.end_time,
                    time_series=result,
                    complete=complete,
                ))
                logger.info(
                    "comparison_context_completed query_id=%s comparison_type=%s context_id=%s "
                    "strategy=%s duration_ms=%d points_received=%d points_returned=%d "
                    "cache_hit=%s complete=%s",
                    qid, payload.comparison_type, context.context_id,
                    strategies[context.context_id], durations[context.context_id],
                    points_received[context.context_id], points_returned[context.context_id],
                    cache_hits[context.context_id], complete,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "comparison_context_failed query_id=%s comparison_type=%s context_id=%s",
                    qid, payload.comparison_type, context.context_id,
                )
                durations[context.context_id] = int((time.monotonic() - context_started) * 1000)
                contexts.append(ComparisonContextResult(
                    context_id=context.context_id,
                    context_label=context.context_label,
                    start_time=context.start_time,
                    end_time=context.end_time,
                    error={
                        "code": getattr(exc, "code", "COMPARISON_CONTEXT_ERROR"),
                        "message": getattr(exc, "safe_message", "Falha ao consultar o contexto."),
                    },
                    complete=False,
                ))

        partial = any(not context.complete for context in contexts)
        series_count = sum(
            len(context.time_series.series) if context.time_series else 0 for context in contexts
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        metadata = ComparisonMetadata(
            comparison_type=payload.comparison_type,
            series_instance_count=series_count,
            points_received_by_context=points_received,
            points_returned_by_context=points_returned,
            duration_ms_by_context=durations,
            strategy_by_context=strategies,
            cache_hit_by_context=cache_hits,
            pi_requests_by_context=pi_requests,
            duration_ms=duration_ms,
            complete=not partial,
            partial=partial,
            query_id=qid,
        )
        logger.info(
            "comparison_completed query_id=%s comparison_type=%s context_count=2 "
            "series_instance_count=%d duration_ms=%d complete=%s partial=%s",
            qid, payload.comparison_type, series_count, duration_ms, not partial, partial,
        )
        return TimeSeriesComparison(
            comparison_type=payload.comparison_type,
            contexts=contexts,
            metadata=metadata,
        )
    except asyncio.CancelledError:
        logger.info(
            "comparison_cancelled query_id=%s comparison_type=%s context_count=2",
            qid, payload.comparison_type,
        )
        raise QueryCancelledError(f"Comparacao {qid} cancelada.")
    finally:
        await registry.unregister(qid)


@router.post("/export", summary="Exportar CSV completo por streaming")
async def export_time_series_csv(
    tag_ids: List[Union[int, str]] = Query(
        ...,
        description="IDs das tags. Aceita parametros repetidos ou CSV.",
    ),
    start_time: str = Query(..., description="Inicio do periodo (ISO 8601)."),
    end_time: str = Query(..., description="Fim do periodo (ISO 8601)."),
    mode: TimeSeriesMode = Query("recorded"),
    interval: Optional[str] = Query(None),
    max_count: Optional[int] = Query(None, ge=1, le=1_000_000),
    long_service: PiLongRangeService = Depends(get_long_range_service),
):
    ids = _normalize_tag_ids(tag_ids)

    if len(ids) > 10:
        raise HTTPException(status_code=400, detail="Maximo de 10 tags por exportacao.")

    parsed_start = _parse_iso(start_time)
    parsed_end = _parse_iso(end_time)

    max_days = app_settings.pi_query_max_period_days
    if (parsed_end - parsed_start).total_seconds() > max_days * 86400:
        raise HTTPException(
            status_code=400,
            detail=f"Periodo maximo de {max_days} dias excedido.",
        )

    return StreamingResponse(
        long_service.export_csv(
            tag_ids=ids,
            start_time=parsed_start,
            end_time=parsed_end,
            mode=mode,
            interval=interval,
            max_count=max_count,
        ),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=exportacao_completa_pi.csv",
            "X-Accel-Buffering": "no",
        },
    )
