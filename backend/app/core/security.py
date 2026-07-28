"""Password hashing, JWT and CSRF primitives."""
from datetime import datetime, timedelta, timezone
import secrets

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.exceptions import AppError

JWT_ALGORITHM = "HS256"
PASSWORD_MIN_LENGTH = 5
PASSWORD_MAX_LENGTH = 128
_hasher = PasswordHasher()


class AuthConfigurationError(AppError):
    status_code = 503
    code = "AUTH_NOT_CONFIGURED"


def _secret() -> str:
    value = settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else ""
    if len(value) < 32:
        raise AuthConfigurationError("Autenticacao nao configurada com seguranca.")
    return value


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError(f"A senha deve possuir entre {PASSWORD_MIN_LENGTH} e {PASSWORD_MAX_LENGTH} caracteres.")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: str, auth_version: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.auth_jwt_expire_minutes), "jti": secrets.token_urlsafe(18), "auth_version": auth_version}, _secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM], options={"require": ["sub", "iat", "exp", "jti", "auth_version"]})


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)
