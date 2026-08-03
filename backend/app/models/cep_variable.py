"""CepVariable ORM model — explicit grouping of PI tags for CEP analysis."""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class CepVariable(Base, TimestampMixin):
    """A monitored variable that groups a reading tag with its limit tags."""

    __tablename__ = "cep_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipments.id", ondelete="RESTRICT"), nullable=False,
    )
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), nullable=False,
    )
    variable_type_id: Mapped[int] = mapped_column(
        ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False,
    )
    reading_tag_id: Mapped[int] = mapped_column(
        ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False,
    )
    lower_limit_tag_id: Mapped[int] = mapped_column(
        ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False,
    )
    upper_limit_tag_id: Mapped[int] = mapped_column(
        ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False,
    )
    target_tag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    # Relationships
    equipment = relationship("Equipment", back_populates="cep_variables", lazy="joined")
    section = relationship("Section", back_populates="cep_variables", lazy="joined")
    variable_type = relationship("VariableType", back_populates="cep_variables", lazy="joined")
    reading_tag = relationship("PiTag", foreign_keys=[reading_tag_id], lazy="joined")
    lower_limit_tag = relationship("PiTag", foreign_keys=[lower_limit_tag_id], lazy="joined")
    upper_limit_tag = relationship("PiTag", foreign_keys=[upper_limit_tag_id], lazy="joined")
    target_tag = relationship("PiTag", foreign_keys=[target_tag_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint("equipment_id", "code", name="uq_cep_variables_equip_code"),
        Index("ix_cep_variables_equipment_id", "equipment_id"),
        Index("ix_cep_variables_section_id", "section_id"),
        Index("ix_cep_variables_active", "active"),
    )

    def __repr__(self) -> str:
        return f"CepVariable(id={self.id}, code={self.code!r}, name={self.name!r})"
