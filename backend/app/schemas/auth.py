from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.user import UserRole


def normalize_username(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Nome de usuario obrigatorio.")
    return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    _username = field_validator("username")(normalize_username)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=5, max_length=128)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=5, max_length=128)
    role: Literal["admin", "user"] = "user"
    is_active: bool = True
    _username = field_validator("username")(normalize_username)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(default=None, min_length=1, max_length=64)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    _username = field_validator("username")(lambda value: normalize_username(value) if value is not None else value)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(min_length=5, max_length=128)
