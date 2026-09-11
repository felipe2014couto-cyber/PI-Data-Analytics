"""Resolved auxiliary PI points used by CEP variables."""
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class CepVariableTagDependency(Base, TimestampMixin):
    __tablename__ = "cep_variable_tag_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variable_id: Mapped[int] = mapped_column(ForeignKey("cep_variables.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pi_tags.id", ondelete="SET NULL"), nullable=True)
    dependency_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    pi_web_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    variable = relationship("CepVariable", lazy="joined")
    tag = relationship("PiTag", lazy="joined")

    __table_args__ = (
        UniqueConstraint("variable_id", "dependency_type", name="uq_cep_variable_dependency_type"),
        Index("ix_cep_dependency_tag", "tag_id"),
        Index("ix_cep_dependency_status", "status"),
    )
