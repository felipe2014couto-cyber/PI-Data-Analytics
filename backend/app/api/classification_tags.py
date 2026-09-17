"""Classification tag API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.classification_tag import (
    ClassificationTagCreate,
    ClassificationTagResponse,
)
from app.services.classification_tag_service import ClassificationTagService

router = APIRouter(prefix="/classification-tags", tags=["classification-tags"])


@router.get("", summary="Listar tags de classificacao")
def list_classification_tags(
    search: Optional[str] = None,
    db: Session = Depends(get_db_session),
) -> list[ClassificationTagResponse]:
    service = ClassificationTagService(db)
    return [
        ClassificationTagResponse.model_validate(tag)
        for tag in service.list(search=search)
    ]


@router.get("/{tag_id}", summary="Obter tag de classificacao")
def get_classification_tag(
    tag_id: int,
    db: Session = Depends(get_db_session),
) -> ClassificationTagResponse:
    service = ClassificationTagService(db)
    return ClassificationTagResponse.model_validate(service.get(tag_id))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Criar tag de classificacao")
def create_classification_tag(
    payload: ClassificationTagCreate,
    db: Session = Depends(get_db_session),
) -> ClassificationTagResponse:
    service = ClassificationTagService(db)
    return ClassificationTagResponse.model_validate(service.create(payload.name))


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir tag de classificacao")
def delete_classification_tag(
    tag_id: int,
    db: Session = Depends(get_db_session),
) -> None:
    service = ClassificationTagService(db)
    service.delete(tag_id)
    return None
