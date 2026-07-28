"""Owned and versioned visual configurations."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class VisualConfiguration(Base, TimestampMixin):
    __tablename__ = "visual_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    versions: Mapped[list["VisualConfigurationVersion"]] = relationship(back_populates="configuration", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("current_version >= 1", name="ck_visual_configurations_version_positive"),
        Index("ix_visual_configurations_owner_updated", "owner_id", "updated_at"),
    )


class VisualConfigurationVersion(Base):
    __tablename__ = "visual_configuration_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    configuration_id: Mapped[str] = mapped_column(ForeignKey("visual_configurations.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.current_timestamp())
    configuration: Mapped[VisualConfiguration] = relationship(back_populates="versions")
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_visual_configuration_versions_positive"),
        UniqueConstraint("configuration_id", "version", name="uq_visual_configuration_versions_number"),
        Index("ix_visual_configuration_versions_config_created", "configuration_id", "created_at"),
    )
