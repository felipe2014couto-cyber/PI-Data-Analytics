"""Durable lifecycle and result record for CEP analyses."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class CepQueryOperation(Base):
    """Persisted CEP state; active asyncio tasks remain process-local."""

    __tablename__ = "cep_query_operations"

    query_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    variable_series_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed_variables: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_variables: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_work_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_work_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_cep_query_operations_status", "status"),
        Index("ix_cep_query_operations_expires_at", "expires_at"),
    )
