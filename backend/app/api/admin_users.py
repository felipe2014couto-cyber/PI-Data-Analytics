from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.api.deps import get_db_session, require_admin, validate_csrf
from app.schemas.auth import ResetPasswordRequest, UserCreate, UserPublic, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/admin/users", tags=["admin-users"], dependencies=[Depends(require_admin), Depends(validate_csrf)])

@router.get("", response_model=list[UserPublic])
def list_users(db: Session = Depends(get_db_session)): return UserService(db).list()

@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db_session)): return UserService(db).create(payload)

@router.get("/{user_id}", response_model=UserPublic)
def get_user(user_id: str, db: Session = Depends(get_db_session)): return UserService(db).get(user_id)

@router.put("/{user_id}", response_model=UserPublic)
def update_user(user_id: str, payload: UserUpdate, db: Session = Depends(get_db_session)): return UserService(db).update(user_id, payload)

@router.post("/{user_id}/reset-password", response_model=UserPublic)
def reset_password(user_id: str, payload: ResetPasswordRequest, db: Session = Depends(get_db_session)): return UserService(db).reset_password(user_id, payload.new_password)

@router.post("/{user_id}/activate", response_model=UserPublic)
def activate(user_id: str, db: Session = Depends(get_db_session)): return UserService(db).update(user_id, UserUpdate(is_active=True))

@router.post("/{user_id}/deactivate", response_model=UserPublic)
def deactivate(user_id: str, db: Session = Depends(get_db_session)): return UserService(db).update(user_id, UserUpdate(is_active=False))
