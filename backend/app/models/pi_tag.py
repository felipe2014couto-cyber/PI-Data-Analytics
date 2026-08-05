"""PiTag ORM model.

The PiTag entity is administrated in this phase but does not contact the
PI Web API. Real validation/resolution will be implemented in a later phase.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class PiTagDataType(str, enum.Enum):
    NUMERIC = "NUMERIC"
    NON_NUMERIC = "NON_NUMERIC"


class PiTagValidationStatus(str, enum.Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    ERROR = "ERROR"


class PiTag(Base, TimestampMixin):
    __tablename__ = "pi_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    variable_type_id: Mapped[int] = mapped_column(
        ForeignKey("variable_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pi_server: Mapped[str] = mapped_column(String(128), nullable=False)
    pi_tag_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lower_limit_tag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    upper_limit_tag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pi_web_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    engineering_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    data_type: Mapped[PiTagDataType] = mapped_column(
        Enum(PiTagDataType, name="pi_tag_data_type", native_enum=False, length=32),
        nullable=False,
        default=PiTagDataType.NUMERIC,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    validation_status: Mapped[PiTagValidationStatus] = mapped_column(
        Enum(PiTagValidationStatus, name="pi_tag_validation_status", native_enum=False, length=16),
        nullable=False,
        default=PiTagValidationStatus.PENDING,
        server_default=PiTagValidationStatus.PENDING.value,
    )
    validation_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)

    equipment: Mapped["Equipment"] = relationship(  # noqa: F821
        "Equipment",
        back_populates="pi_tags",
        lazy="joined",
    )
    section: Mapped["Section"] = relationship(  # noqa: F821
        "Section",
        back_populates="pi_tags",
        lazy="joined",
    )
    variable_type: Mapped["VariableType"] = relationship(  # noqa: F821
        "VariableType",
        back_populates="pi_tags",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("pi_server", "pi_tag_name", name="uq_pi_tags_server_tag"),
        Index("ix_pi_tags_equipment_id", "equipment_id"),
        Index("ix_pi_tags_section_id", "section_id"),
        Index("ix_pi_tags_variable_type_id", "variable_type_id"),
        Index("ix_pi_tags_pi_tag_name", "pi_tag_name"),
        Index("ix_pi_tags_active", "active"),
        Index("ix_pi_tags_validation_status", "validation_status"),
    )

    def __repr__(self) -> str:
        return f"PiTag(id={self.id}, pi_server={self.pi_server!r}, pi_tag_name={self.pi_tag_name!r})"
