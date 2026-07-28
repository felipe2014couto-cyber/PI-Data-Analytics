"""Local application user."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        CheckConstraint("auth_version >= 1", name="ck_users_auth_version_positive"),
        Index("ix_users_active_role", "is_active", "role"),
    )
