"""PiTag API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_norm_limits_service, get_pi_service
from app.api.pagination import build_paginated_response
from app.api.query_params import pagination_params
from app.models.pi_tag import PiTagKind, PiTagValidationStatus
from app.schemas.pi import (
    PiTagNormLimitsResponse,
    PiTagValidationBatchRequest,
    PiTagValidationBatchResponse,
    PiTagValidationResult,
    TimeSeriesMode,
)
from app.schemas.pi_tag import PiTagCreate, PiTagResponse, PiTagUpdate
from app.services.pi_norm_limits_service import PiNormLimitsService
from app.services.pi_service import PiService
from app.services.pi_tag_service import PiTagService

router = APIRouter(prefix="/pi-tags", tags=["pi-tags"])


@router.get("", summary="Listar tags PI")
def list_pi_tags(
    search: Optional[str] = None,
    equipment_id: Optional[int] = None,
    section_id: Optional[int] = None,
    variable_type_id: Optional[int] = None,
    active: Optional[bool] = None,
    validation_status: Optional[PiTagValidationStatus] = None,
    include_dependencies: bool = False,
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db_session),
):
    service = PiTagService(db)
    items, total = service.list(
        search=search,
        equipment_id=equipment_id,
        section_id=section_id,
        variable_type_id=variable_type_id,
        active=active,
        validation_status=validation_status,
        tag_kind=None if include_dependencies else PiTagKind.PRIMARY,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )
    response_items = [PiTagResponse.model_validate(item).model_dump(mode="json") for item in items]
    return build_paginated_response(
        items=response_items,
        page=pagination["page"],
        page_size=pagination["page_size"],
        total=total,
    )


@router.get("/{pi_tag_id}", summary="Obter tag PI")
def get_pi_tag(pi_tag_id: int, db: Session = Depends(get_db_session)) -> PiTagResponse:
    service = PiTagService(db)
    item = service.get(pi_tag_id)
    return PiTagResponse.model_validate(item)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Criar tag PI")
def create_pi_tag(
    payload: PiTagCreate,
    db: Session = Depends(get_db_session),
) -> PiTagResponse:
    service = PiTagService(db)
    item = service.create(payload)
    return PiTagResponse.model_validate(item)


@router.put("/{pi_tag_id}", summary="Atualizar tag PI")
def update_pi_tag(
    pi_tag_id: int,
    payload: PiTagUpdate,
    db: Session = Depends(get_db_session),
) -> PiTagResponse:
    service = PiTagService(db)
    item = service.update(pi_tag_id, payload)
    return PiTagResponse.model_validate(item)


@router.delete("/{pi_tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir tag PI")
def delete_pi_tag(pi_tag_id: int, db: Session = Depends(get_db_session)) -> None:
    service = PiTagService(db)
    service.delete(pi_tag_id)
    return None


@router.post(
    "/validate",
    response_model=PiTagValidationBatchResponse,
    summary="Validar varias tags no PI Web API",
)
async def validate_tags(
    payload: Optional[PiTagValidationBatchRequest] = None,
    service: PiService = Depends(get_pi_service),
) -> PiTagValidationBatchResponse:
    tag_ids = payload.tag_ids if payload else None
    result = await service.validate_tags(tag_ids)
    return PiTagValidationBatchResponse(
        total=result["summary"]["total"],
        valid=result["summary"].get("valid", 0),
        invalid=result["summary"].get("invalid", 0),
        error=result["summary"].get("error", 0),
        results=result["results"],
    )


@router.post(
    "/{pi_tag_id}/validate",
    response_model=PiTagValidationResult,
    summary="Validar uma tag especifica no PI Web API",
)
async def validate_pi_tag(
    pi_tag_id: int,
    service: PiService = Depends(get_pi_service),
) -> PiTagValidationResult:
    return await service.validate_tag(pi_tag_id)


@router.get(
    "/{pi_tag_id}/norm-limits",
    response_model=PiTagNormLimitsResponse,
    summary="Consultar limites de norma (inferior e superior) da tag",
)
async def get_norm_limits(
    pi_tag_id: int,
    start_time: str = Query(..., description="Inicio do periodo (ISO 8601)."),
    end_time: str = Query(..., description="Fim do periodo (ISO 8601)."),
    mode: TimeSeriesMode = Query("recorded", description="Tipo de consulta."),
    interval: Optional[str] = Query(None, description="Intervalo (obrigatorio para interpolated)."),
    max_count: Optional[int] = Query(None, ge=1, le=1_000_000),
    service: PiNormLimitsService = Depends(get_norm_limits_service),
) -> PiTagNormLimitsResponse:
    from datetime import datetime

    def _parse(value: str) -> datetime:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)

    return await service.fetch_norm_limits(
        source_tag_id=pi_tag_id,
        start_time=_parse(start_time),
        end_time=_parse(end_time),
        mode=mode,
        interval=interval,
        max_count=max_count,
    )
