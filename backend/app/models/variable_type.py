"""VariableType ORM model."""
import enum
from typing import List, Optional

from sqlalchemy import Boolean, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class VariableFilterDataType(str, enum.Enum):
    REAL = "REAL"
    STRING = "STRING"
    DIGITAL = "DIGITAL"


class VariableType(Base, TimestampMixin):
    __tablename__ = "variable_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    filter_data_type: Mapped[VariableFilterDataType] = mapped_column(
        Enum(VariableFilterDataType, native_enum=False, length=16),
        nullable=False,
        default=VariableFilterDataType.REAL,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    pi_tags: Mapped[List["PiTag"]] = relationship(  # noqa: F821
        "PiTag",
        back_populates="variable_type",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    cep_variables: Mapped[List["CepVariable"]] = relationship(  # noqa: F821
        "CepVariable",
        back_populates="variable_type",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    section_analysis_tags: Mapped[List["SectionAnalysisTag"]] = relationship(  # noqa: F821
        "SectionAnalysisTag",
        back_populates="variable_type",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_variable_types_active", "active"),
    )

    def __repr__(self) -> str:
        return f"VariableType(id={self.id}, code={self.code!r}, name={self.name!r})"
