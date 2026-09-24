import enum

from sqlalchemy import Enum, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.base import TimestampMixin


class SectionAnalysisFilterType(str, enum.Enum):
    SELECTION = "SELECTION"
    MIN_MAX = "MIN_MAX"
    TEXT = "TEXT"


class SectionAnalysisTag(Base, TimestampMixin):
    __tablename__ = "section_analysis_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
    )
    variable_type_id: Mapped[int] = mapped_column(
        ForeignKey("variable_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pi_tag_id: Mapped[int] = mapped_column(
        ForeignKey("pi_tags.id", ondelete="RESTRICT"),
        nullable=False,
    )
    filter_type: Mapped[SectionAnalysisFilterType] = mapped_column(
        Enum(SectionAnalysisFilterType, native_enum=False, length=16),
        nullable=False,
        default=SectionAnalysisFilterType.SELECTION,
        server_default=SectionAnalysisFilterType.SELECTION.value,
    )

    section: Mapped["Section"] = relationship(  # noqa: F821
        "Section",
        back_populates="analysis_tags",
    )
    variable_type: Mapped["VariableType"] = relationship(  # noqa: F821
        "VariableType",
        back_populates="section_analysis_tags",
        lazy="joined",
    )
    pi_tag: Mapped["PiTag"] = relationship(  # noqa: F821
        "PiTag",
        back_populates="section_analysis_tags",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("section_id", "variable_type_id", name="uq_section_analysis_tags_section_variable_type"),
        Index("ix_section_analysis_tags_section_id", "section_id"),
        Index("ix_section_analysis_tags_variable_type_id", "variable_type_id"),
        Index("ix_section_analysis_tags_pi_tag_id", "pi_tag_id"),
    )

    def __repr__(self) -> str:
        return (
            f"SectionAnalysisTag(id={self.id}, section_id={self.section_id}, "
            f"variable_type_id={self.variable_type_id}, pi_tag_id={self.pi_tag_id}, "
            f"filter_type={self.filter_type!r})"
        )
