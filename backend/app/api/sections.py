"""Section API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.pagination import build_paginated_response
from app.api.query_params import pagination_params
from app.schemas.section import SectionCreate, SectionResponse, SectionUpdate
from app.services.section_service import SectionService

router = APIRouter(prefix="/sections", tags=["sections"])


@router.get("", summary="Listar secoes")
def list_sections(
    search: Optional[str] = None,
    equipment_id: Optional[int] = None,
    active: Optional[bool] = None,
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db_session),
):
    service = SectionService(db)
    items, total = service.list(
        search=search,
        equipment_id=equipment_id,
        active=active,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )
    response_items = [SectionResponse.model_validate(item).model_dump() for item in items]
    return build_paginated_response(
        items=response_items,
        page=pagination["page"],
        page_size=pagination["page_size"],
        total=total,
    )


@router.get("/{section_id}", summary="Obter secao")
def get_section(section_id: int, db: Session = Depends(get_db_session)) -> SectionResponse:
    service = SectionService(db)
    item = service.get(section_id)
    return SectionResponse.model_validate(item)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Criar secao")
def create_section(
    payload: SectionCreate,
    db: Session = Depends(get_db_session),
) -> SectionResponse:
    service = SectionService(db)
    item = service.create(payload)
    return SectionResponse.model_validate(item)


@router.put("/{section_id}", summary="Atualizar secao")
def update_section(
    section_id: int,
    payload: SectionUpdate,
    db: Session = Depends(get_db_session),
) -> SectionResponse:
    service = SectionService(db)
    item = service.update(section_id, payload)
    return SectionResponse.model_validate(item)


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir secao")
def delete_section(section_id: int, db: Session = Depends(get_db_session)) -> None:
    service = SectionService(db)
    service.delete(section_id)
    return None
