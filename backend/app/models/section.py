"""Section ORM model."""
from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class Section(Base, TimestampMixin):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    # These are validated as same-section PI tags by SectionService. They are
    # intentionally plain nullable IDs because pi_tags already references
    # sections; database foreign keys here would create a circular ORM/DDL
    # dependency and would complicate section/tag lifecycle operations.
    width_tag_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    um_tag_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thickness_tag_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    equipment: Mapped["Equipment"] = relationship(  # noqa: F821
        "Equipment",
        back_populates="sections",
        lazy="joined",
    )
    pi_tags: Mapped[List["PiTag"]] = relationship(  # noqa: F821
        "PiTag",
        back_populates="section",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    cep_variables: Mapped[List["CepVariable"]] = relationship(  # noqa: F821
        "CepVariable",
        back_populates="section",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("equipment_id", "code", name="uq_sections_equipment_code"),
        Index("ix_sections_equipment_id", "equipment_id"),
        Index("ix_sections_active", "active"),
        Index("ix_sections_width_tag_id", "width_tag_id"),
        Index("ix_sections_um_tag_id", "um_tag_id"),
        Index("ix_sections_thickness_tag_id", "thickness_tag_id"),
    )

    def __repr__(self) -> str:
        return f"Section(id={self.id}, equipment_id={self.equipment_id}, code={self.code!r})"
