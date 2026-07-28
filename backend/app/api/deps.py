"""API dependencies."""
from typing import Generator, Optional

import hmac
from fastapi import Depends, Request
import jwt
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.integrations.pi.manager import (
    PiDataProvider,
    get_pi_data_provider,
)
from app.services.pi_long_range_service import PiLongRangeService
from app.services.pi_service import PiService
from app.services.query_registry import QueryRegistry, get_query_registry
from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError, PasswordChangeRequiredError
from app.core.security import decode_access_token
from app.models.user import User, UserRole


def get_db_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_pi_provider() -> Optional[PiDataProvider]:
    return get_pi_data_provider()


def get_pi_service(
    db: Session = Depends(get_db_session),
    provider: Optional[PiDataProvider] = Depends(get_pi_provider),
) -> PiService:
    return PiService(db, provider=provider)


def get_long_range_service(
    db: Session = Depends(get_db_session),
    provider: Optional[PiDataProvider] = Depends(get_pi_provider),
) -> PiLongRangeService:
    return PiLongRangeService(db, provider=provider)


def get_query_registry_dep() -> QueryRegistry:
    return get_query_registry()


DbSession = Depends(get_db_session)


def get_authenticated_user(request: Request, db: Session = Depends(get_db_session)) -> User:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token: raise AuthenticationError()
    try: claims = decode_access_token(token)
    except (jwt.PyJWTError, ValueError): raise AuthenticationError()
    user = db.get(User, claims.get("sub"))
    if not user or not user.is_active or user.auth_version != claims.get("auth_version"): raise AuthenticationError()
    return user


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    if user.must_change_password: raise PasswordChangeRequiredError()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN: raise AuthorizationError()
    return user


def validate_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}: return
    cookie = request.cookies.get(settings.auth_csrf_cookie_name, "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not header or not hmac.compare_digest(cookie, header): raise AuthorizationError("Token CSRF invalido.")
