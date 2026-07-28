from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_authenticated_user, get_db_session, validate_csrf
from app.core.config import settings
from app.core.security import create_access_token, create_csrf_token
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, UserPublic
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    response.set_cookie(settings.auth_cookie_name, token, httponly=True, secure=settings.auth_cookie_secure, samesite="lax", path="/api", max_age=settings.auth_jwt_expire_minutes * 60)
    # The SPA reads this non-secret double-submit token from its own routes.
    response.set_cookie(settings.auth_csrf_cookie_name, csrf, httponly=False, secure=settings.auth_cookie_secure, samesite="lax", path="/", max_age=settings.auth_jwt_expire_minutes * 60)


@router.post("/login", response_model=UserPublic)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db_session)):
    user = UserService(db).authenticate(payload.username, payload.password)
    _set_cookies(response, create_access_token(user.id, user.auth_version), create_csrf_token())
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(settings.auth_cookie_name, path="/api"); response.delete_cookie(settings.auth_csrf_cookie_name, path="/")


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_authenticated_user)): return user


@router.put("/change-password", response_model=UserPublic, dependencies=[Depends(validate_csrf)])
def change_password(payload: ChangePasswordRequest, response: Response, user: User = Depends(get_authenticated_user), db: Session = Depends(get_db_session)):
    UserService(db).change_password(user, payload.current_password, payload.new_password)
    _set_cookies(response, create_access_token(user.id, user.auth_version), create_csrf_token())
    return user
