"""Reusable, read-only Oracle SIP data source for visualization."""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.base import TimestampMixin


class SipSource(Base, TimestampMixin):
    __tablename__ = "sip_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipments.id", ondelete="RESTRICT"), nullable=False)
    section_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sections.id", ondelete="RESTRICT"), nullable=True)
    variable_type_id: Mapped[int] = mapped_column(ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_column: Mapped[str] = mapped_column(String(128), nullable=False)
    value_column: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    __table_args__ = (
        Index("ix_sip_sources_equipment_id", "equipment_id"),
        Index("ix_sip_sources_section_id", "section_id"),
    )
