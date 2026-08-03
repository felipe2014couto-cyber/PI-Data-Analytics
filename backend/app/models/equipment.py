"""Equipment ORM model."""
from typing import List, Optional

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class Equipment(Base, TimestampMixin):
    __tablename__ = "equipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    sections: Mapped[List["Section"]] = relationship(  # noqa: F821
        "Section",
        back_populates="equipment",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    pi_tags: Mapped[List["PiTag"]] = relationship(  # noqa: F821
        "PiTag",
        back_populates="equipment",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    cep_variables: Mapped[List["CepVariable"]] = relationship(  # noqa: F821
        "CepVariable",
        back_populates="equipment",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_equipments_active", "active"),
    )

    def __repr__(self) -> str:
        return f"Equipment(id={self.id}, code={self.code!r}, name={self.name!r})"
