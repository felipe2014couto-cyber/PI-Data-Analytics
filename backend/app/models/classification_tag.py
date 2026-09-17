"""Classification tag ORM models."""
from typing import List

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class ClassificationTag(Base, TimestampMixin):
    """A reusable classification label that can be attached to sections."""

    __tablename__ = "classification_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    sections: Mapped[List["Section"]] = relationship(  # noqa: F821
        "Section",
        secondary="section_classification_tags",
        back_populates="classification_tags",
        lazy="noload",
    )


class SectionClassificationTag(Base):
    """Association table between sections and classification tags."""

    __tablename__ = "section_classification_tags"

    section_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    classification_tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("classification_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        Index("ix_section_classification_tags_tag", "classification_tag_id"),
    )
