"""Derived RECORDED data; raw samples remain authoritative."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


def now():
    return datetime.now(timezone.utc)


class ProductionUnitMaterialization(Base):
    __tablename__ = "production_unit_materializations"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipments.id", ondelete="CASCADE"))
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    um_tag_id: Mapped[int] = mapped_column(ForeignKey("pi_tags.id", ondelete="CASCADE"))
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Boundary metadata only: no filtered or partial-window statistics.
    segments: Mapped[list] = mapped_column(JSON)
    source_versions: Mapped[dict] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_production_unit_materialization_scope", "equipment_id", "um_tag_id", "start_ts", "end_ts"),)


class ProductionUnitStoredSegment(Base):
    __tablename__ = "production_unit_segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipments.id", ondelete="CASCADE"))
    um_tag_id: Mapped[int] = mapped_column(ForeignKey("pi_tags.id", ondelete="CASCADE"))
    um_value: Mapped[str | None] = mapped_column(String)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    state_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    # Scope is held in materializations: the same UM tag can serve two scopes.
    __table_args__ = (UniqueConstraint("um_tag_id", "start_ts", name="uq_production_unit_occurrence"),)


class ProductionUnitTagStats(Base):
    __tablename__ = "production_unit_tag_stats"
    segment_id: Mapped[int] = mapped_column(ForeignKey("production_unit_segments.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("pi_tags.id", ondelete="CASCADE"), primary_key=True)
    raw_sample_count: Mapped[int] = mapped_column(Integer)
    filtered_sample_count: Mapped[int] = mapped_column(Integer)
    sample_count: Mapped[int] = mapped_column(Integer)
    excluded_quality_count: Mapped[int] = mapped_column(Integer)
    average: Mapped[float | None] = mapped_column(Float)
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    first_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_value: Mapped[str | None] = mapped_column(String)
    last_value: Mapped[str | None] = mapped_column(String)
    source_version: Mapped[str] = mapped_column(String(64))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
