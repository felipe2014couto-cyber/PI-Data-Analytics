"""VariableType API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.pagination import build_paginated_response
from app.api.query_params import pagination_params
from app.schemas.variable_type import VariableTypeCreate, VariableTypeResponse, VariableTypeUpdate
from app.services.variable_type_service import VariableTypeService

router = APIRouter(prefix="/variable-types", tags=["variable-types"])


@router.get("", summary="Listar tipos de variavel")
def list_variable_types(
    search: Optional[str] = None,
    active: Optional[bool] = None,
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db_session),
):
    service = VariableTypeService(db)
    items, total = service.list(
        search=search,
        active=active,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )
    response_items = [VariableTypeResponse.model_validate(item).model_dump() for item in items]
    return build_paginated_response(
        items=response_items,
        page=pagination["page"],
        page_size=pagination["page_size"],
        total=total,
    )


@router.get("/{variable_type_id}", summary="Obter tipo de variavel")
def get_variable_type(variable_type_id: int, db: Session = Depends(get_db_session)) -> VariableTypeResponse:
    service = VariableTypeService(db)
    item = service.get(variable_type_id)
    return VariableTypeResponse.model_validate(item)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Criar tipo de variavel")
def create_variable_type(
    payload: VariableTypeCreate,
    db: Session = Depends(get_db_session),
) -> VariableTypeResponse:
    service = VariableTypeService(db)
    item = service.create(payload)
    return VariableTypeResponse.model_validate(item)


@router.put("/{variable_type_id}", summary="Atualizar tipo de variavel")
def update_variable_type(
    variable_type_id: int,
    payload: VariableTypeUpdate,
    db: Session = Depends(get_db_session),
) -> VariableTypeResponse:
    service = VariableTypeService(db)
    item = service.update(variable_type_id, payload)
    return VariableTypeResponse.model_validate(item)


@router.delete(
    "/{variable_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir tipo de variavel",
)
def delete_variable_type(variable_type_id: int, db: Session = Depends(get_db_session)) -> None:
    service = VariableTypeService(db)
    service.delete(variable_type_id)
    return None
