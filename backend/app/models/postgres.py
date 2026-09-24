from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, ForeignKey, Index, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.session import Base

class PiSample(Base):
    """Canonical PI sample table backed by a TimescaleDB hypertable.

    ``pi_samples`` is intentionally not mapped here: it is the legacy vanilla
    PostgreSQL table retained during the rollback window.
    """
    __tablename__ = "pi_samples_timescale"

    tag_id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime(timezone=True), primary_key=True, index=True)
    source_mode = Column(String(32), primary_key=True, default="RECORDED")

    value_type = Column(String(12), nullable=False) # 'double', 'boolean', 'string', 'int'

    value_double = Column(Float, nullable=True)
    value_boolean = Column(Boolean, nullable=True)
    value_text = Column(String, nullable=True)

    good = Column(Boolean, nullable=False, default=True)
    questionable = Column(Boolean, nullable=False, default=False)
    substituted = Column(Boolean, nullable=False, default=False)

    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

class PiIngestionCoverage(Base):
    """
    Tabela de rastreamento de cobertura.
    """
    __tablename__ = "pi_ingestion_coverage"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("pi_tags.id", ondelete="CASCADE"), nullable=False)
    range_start = Column(DateTime(timezone=True), nullable=False)
    range_end = Column(DateTime(timezone=True), nullable=False)
    mode = Column(String(50), nullable=False) # 'recorded', 'interpolated_10s' etc
    interval_seconds = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="COMPLETE")
    pi_web_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_pi_ingestion_coverage_tag_range", "tag_id", "range_start", "range_end"),
    )

class PiIngestionState(Base):
    __tablename__ = "pi_ingestion_state"

    tag_id = Column(Integer, ForeignKey("pi_tags.id", ondelete="CASCADE"), primary_key=True)
    source_mode = Column(String(32), primary_key=True, default="RECORDED", server_default="RECORDED")
    last_source_ts = Column(DateTime(timezone=True), nullable=True)
    watermark_ts = Column(DateTime(timezone=True), nullable=True)
    sampling_mode = Column(String(32), nullable=False, default="RECORDED")
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(255), nullable=True)
    last_error_message = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

class PiBackfillJob(Base):
    __tablename__ = "pi_backfill_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("pi_tags.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String(32), nullable=False, default="RECORDED", server_default="RECORDED")
    interval_seconds = Column(Integer, nullable=True)
    target_start = Column(DateTime(timezone=True), nullable=False)
    target_end = Column(DateTime(timezone=True), nullable=False)
    next_start = Column(DateTime(timezone=True), nullable=True)
    t0 = Column(DateTime(timezone=True), nullable=True)
    round_name = Column(String(8), nullable=True)
    stage = Column(String(32), nullable=False, default="PENDING")
    checkpoint_start = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False, default="PENDING")
    error_message = Column(String, nullable=True)
    materialization_status = Column(
        String(32), nullable=False, default="NOT_REQUESTED", server_default="NOT_REQUESTED"
    )
    materialization_error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class PiCaggRefreshJob(Base):
    __tablename__ = "pi_cagg_refresh_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backfill_job_id = Column(Integer, ForeignKey("pi_backfill_jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    tag_id = Column(Integer, ForeignKey("pi_tags.id", ondelete="CASCADE"), nullable=False)
    range_start = Column(DateTime(timezone=True), nullable=False)
    range_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    error_message = Column(String, nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class PiTagDeletionJob(Base):
    __tablename__ = "pi_tag_deletion_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("pi_tags.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    progress = Column(Float, default=0.0)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
