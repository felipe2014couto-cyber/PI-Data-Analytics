"""CEP analysis endpoints.

Provides three endpoints for asynchronous CEP analysis:
- POST /api/cep/analyze — start analysis (returns 202)
- GET /api/cep/analyze/{query_id} — get status/result
- POST /api/cep/analyze/{query_id}/cancel — cancel operation
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_query_registry_dep
from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    HistoricalDataNotLoadedError,
    NotFoundError,
    TimeRangeInvalidError,
    ValidationError,
)
from app.database.session import SessionLocal
from app.models.cep_variable import CepVariable
from app.models.cep_variable_tag_dependency import CepVariableTagDependency
from app.models.pi_tag import PiTag
from app.schemas.cep_analysis import (
    CepAnalysisAccepted,
    CepAnalysisRequest,
    CepQueryCancelled,
    CepQueryPending,
    CepQueryResponse,
    CepQueryRunning,
    MaterializedAnalysisData,
    MaterializedTag,
    MaterializedVariable,
    CepVariableSeries,
)
from app.schemas.common import ErrorResponse
from app.services.cep_analysis_service import CepAnalysisService
from app.services.cep_query_store import (
    CancelResult,
    CepQueryStore,
    get_cep_query_store,
)
from app.services.query_registry import QueryRegistry
from app.services.coverage_service import CoverageService, normalize_mode
from app.services.timescale_cep_provider import TimescaleCepProvider

logger = logging.getLogger("pi_analytics_data.api.cep")

router = APIRouter(prefix="/cep", tags=["cep"])


async def _get_valid_entry(query_id: str, store: CepQueryStore, registry: QueryRegistry):
    timed_out_entry = await store.apply_timeout(query_id)
    if timed_out_entry is not None:
        await registry.cancel(query_id)
    entry = await store.get_or_remove_expired(query_id)
    if entry is None:
        raise NotFoundError("Análise não encontrada ou expirada.")
    return entry


def _validate_timezone(dt: datetime, field_name: str) -> None:
    """Reject naive timestamps."""
    if dt.tzinfo is None:
        raise ValidationError(
            f"O campo '{field_name}' deve possuir timezone explícito (Z ou offset).",
            details={"field": field_name},
        )


def _validate_period(start_time: datetime, end_time: datetime) -> None:
    """Validate period semantics."""
    if start_time >= end_time:
        raise TimeRangeInvalidError(
            "O início do período deve ser anterior ao fim.",
            details={"start_time": start_time.isoformat(), "end_time": end_time.isoformat()},
        )
    max_days = settings.pi_query_max_period_days
    duration_days = (end_time - start_time).total_seconds() / 86400
    if duration_days > max_days:
        raise TimeRangeInvalidError(
            f"O período excede o limite máximo de {max_days} dias.",
            details={"requested_days": duration_days, "limit_days": max_days},
        )


def _load_and_materialize(
    db: Session, request: CepAnalysisRequest
) -> MaterializedAnalysisData:
    """Load CepVariable from database and materialize to session-independent objects."""
    query = db.query(CepVariable).filter(CepVariable.active.is_(True))

    if request.equipment_id is not None:
        query = query.filter(CepVariable.equipment_id == request.equipment_id)
    if request.section_id is not None:
        query = query.filter(CepVariable.section_id == request.section_id)
    if request.variable_ids is not None:
        query = query.filter(CepVariable.id.in_(request.variable_ids))

    cep_variables = query.all()

    if not cep_variables:
        raise ValidationError(
            "Nenhuma configuração CEP ativa encontrada para os filtros informados.",
        )

    if len(cep_variables) > settings.pi_cep_max_variables:
        raise ValidationError(
            f"A seleção excede o limite de {settings.pi_cep_max_variables} variáveis.",
            details={"selected": len(cep_variables), "limit": settings.pi_cep_max_variables},
        )

    variables = []
    tag_variable_map: dict[int, list[int]] = {}
    unique_tags: dict[int, MaterializedTag] = {}
    dependency_rows = list(db.scalars(select(CepVariableTagDependency).where(
        CepVariableTagDependency.variable_id.in_([item.id for item in cep_variables]),
    )).all())
    dependencies_by_variable: dict[int, dict[str, CepVariableTagDependency]] = {}
    for dependency in dependency_rows:
        dependencies_by_variable.setdefault(dependency.variable_id, {})[dependency.dependency_type] = dependency

    def register_tag(tag: MaterializedTag, variable_id: int) -> None:
        unique_tags[tag.id] = tag
        tag_variable_map.setdefault(tag.id, []).append(variable_id)

    def grouped_limit_id(reading_tag_id: int, role: str) -> int:
        # Negative ids identify the two PI Points configured inside the grouped
        # PiTag record. Real database PiTag ids are positive.
        return -(reading_tag_id * 2) if role == "lower" else -(reading_tag_id * 2 + 1)

    for cv in cep_variables:
        reading_tag = cv.reading_tag
        if reading_tag is None:
            raise ValidationError(
                f"A variável CEP '{cv.code}' não possui tag de acompanhamento cadastrada.",
            )

        variable_dependencies = dependencies_by_variable.get(cv.id, {})
        lower_dependency = variable_dependencies.get("LOWER_LIMIT")
        upper_dependency = variable_dependencies.get("UPPER_LIMIT")
        has_grouped_limits = bool(reading_tag.lower_limit_tag and reading_tag.upper_limit_tag)
        lower_limit_tag_id = (
            lower_dependency.tag_id
            if lower_dependency is not None and lower_dependency.tag_id is not None
            else grouped_limit_id(reading_tag.id, "lower")
            if has_grouped_limits else cv.lower_limit_tag_id
        )
        upper_limit_tag_id = (
            upper_dependency.tag_id
            if upper_dependency is not None and upper_dependency.tag_id is not None
            else grouped_limit_id(reading_tag.id, "upper")
            if has_grouped_limits else cv.upper_limit_tag_id
        )

        variables.append(MaterializedVariable(
            id=cv.id, code=cv.code, name=cv.name,
            equipment_id=cv.equipment_id, section_id=cv.section_id,
            variable_type_id=cv.variable_type_id,
            reading_tag_id=reading_tag.id,
            lower_limit_tag_id=lower_limit_tag_id,
            upper_limit_tag_id=upper_limit_tag_id,
            target_tag_id=cv.target_tag_id,
        ))

        register_tag(MaterializedTag(
            id=reading_tag.id,
            pi_tag_name=reading_tag.pi_tag_name,
            pi_server=reading_tag.pi_server,
            pi_web_id=reading_tag.pi_web_id,
        ), cv.id)

        if has_grouped_limits:
            for dependency, fallback_id, name in (
                (lower_dependency, lower_limit_tag_id, reading_tag.lower_limit_tag),
                (upper_dependency, upper_limit_tag_id, reading_tag.upper_limit_tag),
            ):
                dependency_tag = db.get(PiTag, dependency.tag_id) if dependency is not None and dependency.tag_id else None
                register_tag(MaterializedTag(
                    id=dependency_tag.id if dependency_tag else fallback_id,
                    pi_tag_name=dependency_tag.pi_tag_name if dependency_tag else name,
                    pi_server=dependency_tag.pi_server if dependency_tag else reading_tag.pi_server,
                    pi_web_id=dependency_tag.pi_web_id if dependency_tag else None,
                ), cv.id)
        else:
            for limit_tag in [cv.lower_limit_tag, cv.upper_limit_tag]:
                register_tag(MaterializedTag(
                    id=limit_tag.id,
                    pi_tag_name=limit_tag.pi_tag_name,
                    pi_server=limit_tag.pi_server,
                    pi_web_id=limit_tag.pi_web_id,
                ), cv.id)

        if cv.target_tag is not None:
            register_tag(MaterializedTag(
                id=cv.target_tag.id,
                pi_tag_name=cv.target_tag.pi_tag_name,
                pi_server=cv.target_tag.pi_server,
                pi_web_id=cv.target_tag.pi_web_id,
            ), cv.id)

    return MaterializedAnalysisData(
        request=request,
        variables=variables,
        tag_variable_map=tag_variable_map,
        unique_tags=list(unique_tags.values()),
    )


def _validate_historical_coverage(db: Session, materialized: MaterializedAnalysisData) -> None:
    """Reject CEP requests whose required Timescale ranges are incomplete."""
    modes = [("interpolated", materialized.request.interpolated_interval)]
    if materialized.request.include_recorded:
        modes.append(("recorded", None))
    affected: list[dict] = []
    for mode, interval in modes:
        interval_seconds = None
        if interval:
            unit = interval[-1]
            interval_seconds = int(interval[:-1]) * {"s": 1, "m": 60, "h": 3600}[unit]
        requested_mode, interval_seconds = normalize_mode(mode, interval_seconds)
        for item in materialized.unique_tags:
            row = db.execute(
                text("SELECT id FROM pi_tags WHERE pi_server = :server AND pi_tag_name = :name"),
                {"server": item.pi_server, "name": item.pi_tag_name},
            ).first()
            if row is None:
                affected.append({"tag_id": item.id, "tag_name": item.pi_tag_name, "mode": mode, "intervals": []})
                continue
            missing = CoverageService.get_missing_intervals(
                db, int(row[0]), materialized.request.start_time, materialized.request.end_time,
                requested_mode, interval_seconds,
            )
            if missing:
                affected.append({
                    "tag_id": item.id,
                    "tag_name": item.pi_tag_name,
                    "mode": mode,
                    "intervals": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in missing],
                })
    if affected:
        raise HistoricalDataNotLoadedError(details={
            "affected_tags": affected,
            "mode": materialized.request.interpolated_interval,
            "requested_period": {
                "start": materialized.request.start_time.isoformat(),
                "end": materialized.request.end_time.isoformat(),
            },
            "reload_available": True,
        })


@router.post(
    "/analyze",
    status_code=202,
    response_model=CepAnalysisAccepted,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_analysis(
    payload: CepAnalysisRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> CepAnalysisAccepted | JSONResponse:
    """Start a new CEP analysis (asynchronous)."""
    # 1. Validate timezone (structural — 422)
    _validate_timezone(payload.start_time, "start_time")
    _validate_timezone(payload.end_time, "end_time")

    # 2. Validate period (semantic — 400)
    _validate_period(payload.start_time, payload.end_time)

    # 3. Normalize to UTC
    start_utc = payload.start_time.astimezone(UTC)
    end_utc = payload.end_time.astimezone(UTC)
    payload.start_time = start_utc
    payload.end_time = end_utc

    # 4. Load and materialize CepVariable (semantic — 422)
    materialized = _load_and_materialize(db, payload)
    _validate_historical_coverage(db, materialized)

    # 5. Generate query_id
    query_id = str(uuid.uuid4())

    # 6. Register in store (timeout starts here)
    total_work_units = len(materialized.variables) + 3 + (1 if payload.include_recorded else 0)
    entry = await store.register(
        query_id,
        payload,
        total_variables=len(materialized.variables),
        total_work_units=total_work_units,
    )

    # 7. Create async task (blocked by ready_event)
    service = CepAnalysisService(provider=TimescaleCepProvider(db, materialized.unique_tags, SessionLocal))
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )

    # 8. Register task in QueryRegistry (with rollback on failure)
    try:
        await registry.register(query_id, main_task=task)
    except Exception:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await store.remove_unaccepted(query_id)
        raise

    # 9. Release task execution
    entry.ready_event.set()

    # 10. Return 202
    return CepAnalysisAccepted(
        query_id=query_id,
        query_status="pending",
        message="Análise CEP aceita para processamento.",
        progress_percent=0,
        completed_variables=0,
        total_variables=len(materialized.variables),
    )


@router.get(
    "/analyze/{query_id}",
    response_model=CepQueryResponse,
    responses={
        200: {"model": CepQueryResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_analysis(
    query_id: str,
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> JSONResponse:
    """Get analysis status or result."""
    # 1. Apply operational timeout (atomic)
    entry = await _get_valid_entry(query_id, store, registry)

    # 3. Return based on status
    if entry.query_status == "pending":
        pending = CepQueryPending(
            query_id=query_id,
            query_status="pending",
            progress_percent=entry.progress_percent,
            completed_variables=entry.completed_variables,
            total_variables=entry.total_variables,
        )
        return JSONResponse(content=pending.model_dump(mode="json"))

    if entry.query_status == "running":
        running = CepQueryRunning(
            query_id=query_id,
            query_status="running",
            started_at=entry.started_at or datetime.now(UTC),
            progress_percent=entry.progress_percent,
            completed_variables=entry.completed_variables,
            total_variables=entry.total_variables,
        )
        return JSONResponse(content=running.model_dump(mode="json"))

    if entry.query_status == "cancelled":
        cancelled = CepQueryCancelled(
            query_id=query_id,
            query_status="cancelled",
            message="Operação cancelada.",
            progress_percent=entry.progress_percent,
            completed_variables=entry.completed_variables,
            total_variables=entry.total_variables,
        )
        return JSONResponse(content=cancelled.model_dump(mode="json"))

    # completed or failed
    result = entry.result
    if result is None:
        raise NotFoundError("Resultado não disponível.")

    include_recorded = entry.request.include_recorded if entry.request else False
    if not include_recorded:
        content = result.model_dump(mode="json", exclude={"recorded_series"})
        return JSONResponse(content=content)
    else:
        return JSONResponse(content=result.model_dump(mode="json"))


@router.get(
    "/analyze/{query_id}/variables/{variable_id}/series",
    response_model=CepVariableSeries,
    responses={404: {"model": ErrorResponse}},
)
async def get_variable_series(
    query_id: str,
    variable_id: int,
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> CepVariableSeries:
    """Return the Interpolated series retained for one completed execution."""
    entry = await _get_valid_entry(query_id, store, registry)
    series = entry.variable_series.get(variable_id)
    if series is None:
        raise NotFoundError("Variável não encontrada nesta análise.")
    return series


@router.post(
    "/analyze/{query_id}/cancel",
    response_model=CepQueryCancelled,
    responses={
        200: {"model": CepQueryCancelled},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def cancel_analysis(
    query_id: str,
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> CepQueryCancelled | JSONResponse:
    """Cancel a running analysis."""
    # 1. Apply operational timeout (atomic)
    timed_out_entry = await store.apply_timeout(query_id)
    if timed_out_entry is not None:
        await registry.cancel(query_id)
        raise ConflictError("Operação já finalizada e não pode ser cancelada.")

    # 2. Get entry, removing if terminal expired (atomic)
    entry = await store.get_or_remove_expired(query_id)
    if entry is None:
        raise NotFoundError("Análise não encontrada ou expirada.")

    # 3. Try to cancel (atomic)
    result = await store.set_cancelled(query_id)

    if result == CancelResult.NOT_FOUND:
        raise NotFoundError("Análise não encontrada ou expirada.")

    if result == CancelResult.ALREADY_TERMINAL:
        raise ConflictError("Operação já finalizada e não pode ser cancelada.")

    if result == CancelResult.CANCELLED:
        await registry.cancel(query_id)

    # ALREADY_CANCELLED → 200 idempotent
    return CepQueryCancelled(
        query_id=query_id,
        query_status="cancelled",
        message="Operação cancelada.",
        progress_percent=entry.progress_percent,
        completed_variables=entry.completed_variables,
        total_variables=entry.total_variables,
    )
