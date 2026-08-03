"""Owned versioned visual configuration endpoints."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.schemas.visual_configuration import (
    VisualConfigurationCreate, VisualConfigurationPublic, VisualConfigurationRename,
    VisualConfigurationRestore, VisualConfigurationUpdate, VisualConfigurationVersionPublic,
)
from app.services.visual_configuration_service import VisualConfigurationService

router = APIRouter(prefix="/visual-configurations", tags=["visual-configurations"])


def service(db: Session, user: User) -> VisualConfigurationService: return VisualConfigurationService(db, user)
def public(item, document=None): return VisualConfigurationPublic(id=item.id, name=item.name, description=item.description, current_version=item.current_version, created_at=item.created_at, updated_at=item.updated_at, document=document)
def version_public(item): return VisualConfigurationVersionPublic(id=item.id, version=item.version, document=item.snapshot, operation=item.operation, created_at=item.created_at)


@router.post("", response_model=VisualConfigurationPublic, status_code=status.HTTP_201_CREATED)
def create(payload: VisualConfigurationCreate, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    item = service(db, user).create(payload); return public(item, payload.document)


@router.get("", response_model=list[VisualConfigurationPublic])
def list_all(db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    return [public(item) for item in service(db, user).list_all()]


@router.get("/{config_id}", response_model=VisualConfigurationPublic)
def get_one(config_id: str, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    item, version = service(db, user).get(config_id); return public(item, version.snapshot)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_one(config_id: str, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)) -> None:
    service(db, user).delete(config_id)
    return None


@router.put("/{config_id}", response_model=VisualConfigurationPublic)
def update_one(config_id: str, payload: VisualConfigurationUpdate, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    item = service(db, user).update(config_id, payload.expected_version, payload.document.model_dump()); return public(item, payload.document)


@router.post("/{config_id}/rename", response_model=VisualConfigurationPublic)
def rename(config_id: str, payload: VisualConfigurationRename, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    svc = service(db, user); item = svc.rename(config_id, payload.expected_version, payload.name); _, current = svc.get(config_id); return public(item, current.snapshot)


@router.get("/{config_id}/history", response_model=list[VisualConfigurationVersionPublic])
def history(config_id: str, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    return [version_public(item) for item in service(db, user).history(config_id)]


@router.get("/{config_id}/history/{version}", response_model=VisualConfigurationVersionPublic)
def get_version(config_id: str, version: int, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    return version_public(service(db, user).get_version(config_id, version))


@router.post("/{config_id}/restore", response_model=VisualConfigurationPublic)
def restore(config_id: str, payload: VisualConfigurationRestore, db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    svc = service(db, user); item = svc.restore(config_id, payload.expected_version, payload.version); _, current = svc.get(config_id); return public(item, current.snapshot)
