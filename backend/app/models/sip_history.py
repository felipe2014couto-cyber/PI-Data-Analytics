"""SIP samples persisted in TimescaleDB and non-temporal database tags."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.base import TimestampMixin


class SipSample(Base):
    __tablename__ = "sip_samples_timescale"
    source_id: Mapped[int] = mapped_column(ForeignKey("sip_sources.id", ondelete="CASCADE"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value_double: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_boolean: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_sip_samples_source_ts", "source_id", "ts"),)


class SipReloadJob(Base, TimestampMixin):
    __tablename__ = "sip_reload_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sip_sources.id", ondelete="RESTRICT"), nullable=False)
    target_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("ix_sip_reload_jobs_status_id", "status", "id"),)


class SipCoverage(Base):
    __tablename__ = "sip_coverage"
    source_id: Mapped[int] = mapped_column(ForeignKey("sip_sources.id", ondelete="CASCADE"), primary_key=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class SipDatabaseTag(Base, TimestampMixin):
    __tablename__ = "sip_database_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipments.id", ondelete="RESTRICT"), nullable=False)
    section_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sections.id", ondelete="RESTRICT"), nullable=True)
    variable_type_id: Mapped[int] = mapped_column(ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_column: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
