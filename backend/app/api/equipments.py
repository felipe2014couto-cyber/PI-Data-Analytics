"""Equipment API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.pagination import build_paginated_response
from app.api.query_params import pagination_params
from app.schemas.equipment import EquipmentCreate, EquipmentResponse, EquipmentUpdate
from app.services.equipment_service import EquipmentService

router = APIRouter(prefix="/equipments", tags=["equipments"])


@router.get("", summary="Listar equipamentos")
def list_equipments(
    search: Optional[str] = None,
    active: Optional[bool] = None,
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db_session),
):
    service = EquipmentService(db)
    items, total = service.list(
        search=search,
        active=active,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )
    response_items = [EquipmentResponse.model_validate(item).model_dump() for item in items]
    return build_paginated_response(
        items=response_items,
        page=pagination["page"],
        page_size=pagination["page_size"],
        total=total,
    )


@router.get("/{equipment_id}", summary="Obter equipamento")
def get_equipment(equipment_id: int, db: Session = Depends(get_db_session)) -> EquipmentResponse:
    service = EquipmentService(db)
    item = service.get(equipment_id)
    return EquipmentResponse.model_validate(item)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Criar equipamento")
def create_equipment(
    payload: EquipmentCreate,
    db: Session = Depends(get_db_session),
) -> EquipmentResponse:
    service = EquipmentService(db)
    item = service.create(payload)
    return EquipmentResponse.model_validate(item)


@router.put("/{equipment_id}", summary="Atualizar equipamento")
def update_equipment(
    equipment_id: int,
    payload: EquipmentUpdate,
    db: Session = Depends(get_db_session),
) -> EquipmentResponse:
    service = EquipmentService(db)
    item = service.update(equipment_id, payload)
    return EquipmentResponse.model_validate(item)


@router.delete("/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir equipamento")
def delete_equipment(equipment_id: int, db: Session = Depends(get_db_session)) -> None:
    service = EquipmentService(db)
    service.delete(equipment_id)
    return None
