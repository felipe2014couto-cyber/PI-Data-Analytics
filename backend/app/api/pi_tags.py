"""PiTag API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_pi_service
from app.api.pagination import build_paginated_response
from app.api.query_params import pagination_params
from app.models.pi_tag import PiTagValidationStatus
from app.schemas.pi import PiTagValidationBatchRequest, PiTagValidationBatchResponse, PiTagValidationResult
from app.schemas.pi_tag import PiTagCreate, PiTagResponse, PiTagUpdate
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
