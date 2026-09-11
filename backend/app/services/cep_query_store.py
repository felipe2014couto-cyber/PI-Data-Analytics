"""Durable CEP lifecycle store with an in-memory task/event cache."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import delete, select, update

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.cep_query_operation import CepQueryOperation
from app.schemas.cep_analysis import (
    CepAnalysisMetadata,
    CepAnalysisRequest,
    CepAnalysisResult,
    CepAnalysisSummary,
    CepDiagnostic,
    CepVariableSeries,
)

logger = logging.getLogger("pi_analytics_data.service.cep_query_store")


class CepPersistenceError(RuntimeError):
    """A persisted CEP payload could not be deserialized safely."""


@dataclass
class CepQueryEntry:
    query_id: str
    query_status: str
    created_at: float
    terminal_at: float | None = None
    started_at: datetime | None = None
    request: CepAnalysisRequest | None = None
    result: CepAnalysisResult | None = None
    variable_series: dict[int, CepVariableSeries] = field(default_factory=dict)
    completed_variables: int = 0
    total_variables: int = 0
    completed_work_units: int = 0
    total_work_units: int = 0
    progress_percent: int = 0
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    persisted_created_at: datetime | None = None
    persisted_terminal_at: datetime | None = None
    expires_at: datetime | None = None


class CancelResult(Enum):
    CANCELLED = "cancelled"
    ALREADY_CANCELLED = "already_cancelled"
    ALREADY_TERMINAL = "already_terminal"
    NOT_FOUND = "not_found"


@dataclass
class CleanupResult:
    expired: list[str]
    timed_out: list[str]


class CepQueryStore:
    """Persisted source of truth plus process-local events for active tasks.

    A store constructed without a session factory remains ephemeral for the
    low-level unit tests. The application singleton below always supplies the
    real SQLAlchemy ``SessionLocal`` factory.
    """

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory
        self._lock = asyncio.Lock()
        self._entries: dict[str, CepQueryEntry] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _entry_from_row(self, row: CepQueryOperation) -> CepQueryEntry:
        try:
            request = CepAnalysisRequest.model_validate(row.request_payload)
            result = CepAnalysisResult.model_validate(row.result_payload) if row.result_payload else None
            series = {
                int(key): CepVariableSeries.model_validate(value)
                for key, value in (row.variable_series_payload or {}).items()
            }
        except Exception as exc:
            logger.exception("CEP persisted payload invalid query_id=%s", row.query_id)
            raise CepPersistenceError(f"CEP payload invalid for query {row.query_id}") from exc

        created = self._utc(row.created_at) or self._now()
        terminal = self._utc(row.terminal_at)
        now = self._now()
        elapsed = max(0.0, (now - created).total_seconds())
        cached = self._entries.get(row.query_id)
        entry = cached or CepQueryEntry(
            query_id=row.query_id,
            query_status=row.status,
            created_at=time.monotonic() - elapsed,
        )
        entry.query_status = row.status
        entry.request = request
        entry.result = result
        entry.variable_series = series
        entry.completed_variables = row.completed_variables
        entry.total_variables = row.total_variables
        entry.completed_work_units = row.completed_work_units
        entry.total_work_units = row.total_work_units
        entry.progress_percent = row.progress_percent
        entry.started_at = self._utc(row.started_at)
        entry.persisted_created_at = created
        entry.persisted_terminal_at = terminal
        entry.expires_at = self._utc(row.expires_at)
        if cached is None and terminal is not None:
            entry.terminal_at = time.monotonic() - max(0.0, (now - terminal).total_seconds())
        if row.status in ("completed", "failed", "cancelled"):
            entry.ready_event.set()
        self._entries[row.query_id] = entry
        return entry

    async def register(self, query_id: str, request: CepAnalysisRequest, total_variables: int = 0, total_work_units: int | None = None) -> CepQueryEntry:
        async with self._lock:
            total_work = max(0, total_work_units if total_work_units is not None else total_variables)
            now = self._now()
            if self.session_factory:
                with self.session_factory() as session:
                    session.add(CepQueryOperation(
                        query_id=query_id,
                        status="pending",
                        request_payload=request.model_dump(mode="json"),
                        completed_variables=0,
                        total_variables=max(0, total_variables),
                        completed_work_units=0,
                        total_work_units=total_work,
                        progress_percent=0,
                        created_at=now,
                        updated_at=now,
                    ))
                    session.commit()
            entry = CepQueryEntry(
                query_id=query_id,
                query_status="pending",
                created_at=time.monotonic(),
                request=request,
                total_variables=max(0, total_variables),
                total_work_units=total_work,
                persisted_created_at=now,
            )
            self._entries[query_id] = entry
            logger.info("CEP query %s registered", query_id)
            return entry

    async def set_running(self, query_id: str) -> bool:
        async with self._lock:
            now = self._now()
            if self.session_factory:
                with self.session_factory() as session:
                    changed = session.execute(
                        update(CepQueryOperation)
                        .where(CepQueryOperation.query_id == query_id, CepQueryOperation.status == "pending")
                        .values(status="running", started_at=now, updated_at=now)
                    )
                    session.commit()
                    if changed.rowcount != 1:
                        return False
                    entry = self._entry_from_row(session.get(CepQueryOperation, query_id))
            else:
                entry = self._entries.get(query_id)
                if entry is None or entry.query_status != "pending":
                    return False
                entry.query_status = "running"
                entry.started_at = now
            entry.query_status = "running"
            entry.started_at = now
            logger.info("CEP query %s → running", query_id)
            return True

    async def set_progress(self, query_id: str, completed_variables: int, completed_work_units: int | None = None) -> bool:
        async with self._lock:
            entry = self._get_entry(query_id)
            if entry is None or entry.query_status in ("completed", "failed", "cancelled"):
                return False
            completed = min(max(0, completed_variables), entry.total_variables)
            entry.completed_variables = max(entry.completed_variables, completed)
            work = completed if completed_work_units is None else min(max(0, completed_work_units), entry.total_work_units)
            entry.completed_work_units = max(entry.completed_work_units, work)
            if entry.total_work_units:
                max_progress = 100 if completed_work_units is None else 99
                entry.progress_percent = max(entry.progress_percent, min(max_progress, round(entry.completed_work_units * 100 / entry.total_work_units)))
            if self.session_factory:
                with self.session_factory() as session:
                    session.execute(
                        update(CepQueryOperation)
                        .where(CepQueryOperation.query_id == query_id, CepQueryOperation.status.in_(("pending", "running")))
                        .values(completed_variables=entry.completed_variables, completed_work_units=entry.completed_work_units, progress_percent=entry.progress_percent, updated_at=self._now())
                    )
                    session.commit()
            return True

    def _get_entry(self, query_id: str) -> CepQueryEntry | None:
        if not self.session_factory:
            return self._entries.get(query_id)
        with self.session_factory() as session:
            row = session.get(CepQueryOperation, query_id)
            return None if row is None else self._entry_from_row(row)

    async def set_result(self, query_id: str, result: CepAnalysisResult, status: str, variable_series: dict[int, CepVariableSeries] | None = None) -> bool:
        async with self._lock:
            if self.session_factory:
                now = self._now()
                with self.session_factory() as session:
                    row = session.execute(select(CepQueryOperation).where(CepQueryOperation.query_id == query_id).with_for_update()).scalar_one_or_none()
                    if row is None or row.status in ("completed", "failed", "cancelled"):
                        return False
                    progress = 100 if status == "completed" else row.progress_percent
                    completed = row.total_variables if status == "completed" else row.completed_variables
                    work = row.total_work_units if status == "completed" else row.completed_work_units
                    persisted_result = result.model_copy(update={"progress_percent": progress, "completed_variables": completed, "total_variables": row.total_variables})
                    row.status = status
                    row.result_payload = persisted_result.model_dump(mode="json")
                    row.variable_series_payload = {str(key): value.model_dump(mode="json") for key, value in (variable_series or {}).items()}
                    row.completed_variables = completed
                    row.completed_work_units = work
                    row.progress_percent = progress
                    row.terminal_at = now
                    row.expires_at = now + timedelta(seconds=settings.pi_cep_result_ttl_seconds)
                    row.updated_at = now
                    session.commit()
                    entry = self._entry_from_row(row)
                    entry.terminal_at = time.monotonic()
            else:
                entry = self._entries.get(query_id)
                if entry is None or entry.query_status in ("completed", "failed", "cancelled"):
                    return False
                entry.query_status = status
                entry.terminal_at = time.monotonic()
                entry.result = result.model_copy(update={"progress_percent": 100 if status == "completed" else entry.progress_percent, "completed_variables": entry.total_variables if status == "completed" else entry.completed_variables, "total_variables": entry.total_variables})
                entry.variable_series = variable_series or {}
                if status == "completed":
                    entry.completed_variables = entry.total_variables
                    entry.completed_work_units = entry.total_work_units
                    entry.progress_percent = 100
            logger.info("CEP query %s → %s", query_id, status)
            return True

    async def set_cancelled(self, query_id: str) -> CancelResult:
        async with self._lock:
            now = self._now()
            if self.session_factory:
                with self.session_factory() as session:
                    row = session.execute(select(CepQueryOperation).where(CepQueryOperation.query_id == query_id).with_for_update()).scalar_one_or_none()
                    if row is None:
                        return CancelResult.NOT_FOUND
                    if row.status == "cancelled":
                        return CancelResult.ALREADY_CANCELLED
                    if row.status in ("completed", "failed"):
                        return CancelResult.ALREADY_TERMINAL
                    row.status = "cancelled"; row.terminal_at = now; row.expires_at = now + timedelta(seconds=settings.pi_cep_result_ttl_seconds); row.updated_at = now
                    session.commit()
                    self._entry_from_row(row).terminal_at = time.monotonic()
            else:
                entry = self._entries.get(query_id)
                if entry is None: return CancelResult.NOT_FOUND
                if entry.query_status == "cancelled": return CancelResult.ALREADY_CANCELLED
                if entry.query_status in ("completed", "failed"): return CancelResult.ALREADY_TERMINAL
                entry.query_status = "cancelled"; entry.terminal_at = time.monotonic()
            logger.info("CEP query %s → cancelled", query_id)
            return CancelResult.CANCELLED

    async def get(self, query_id: str) -> CepQueryEntry | None:
        async with self._lock:
            return self._get_entry(query_id)

    def _build_timeout_result(self, entry: CepQueryEntry, code: str = "OPERATION_TIMEOUT") -> CepAnalysisResult:
        now = self._now(); request = entry.request; start = request.start_time if request else now; end = request.end_time if request else now
        message = "A operação não pôde ser concluída após o reinício." if code == "CEP_INTERRUPTED_BY_RESTART" else "A operação excedeu o tempo limite configurado."
        return CepAnalysisResult(
            query_id=entry.query_id, query_status="failed",
            summary=CepAnalysisSummary(analysis_status="failed", total_variables=entry.total_variables, period_start=start, period_end=end),
            variables=[], diagnostics=[CepDiagnostic(tag_id=0, tag_name="", variable_ids=[], error_code=code, message=message)],
            metadata=CepAnalysisMetadata(), progress_percent=entry.progress_percent, completed_variables=entry.completed_variables, total_variables=entry.total_variables,
        )

    async def apply_timeout(self, query_id: str) -> CepQueryEntry | None:
        async with self._lock:
            entry = self._get_entry(query_id)
            if entry is None or entry.query_status not in ("pending", "running"):
                return None
            if time.monotonic() - entry.created_at <= settings.pi_cep_operation_timeout_seconds:
                return None
            result = self._build_timeout_result(entry)
            if self.session_factory:
                now = self._now()
                with self.session_factory() as session:
                    changed = session.execute(update(CepQueryOperation).where(CepQueryOperation.query_id == query_id, CepQueryOperation.status.in_(("pending", "running"))).values(status="failed", result_payload=result.model_dump(mode="json"), terminal_at=now, expires_at=now + timedelta(seconds=settings.pi_cep_result_ttl_seconds), updated_at=now))
                    session.commit()
                    if changed.rowcount != 1: return None
                    entry = self._entry_from_row(session.get(CepQueryOperation, query_id))
            else:
                entry.query_status = "failed"; entry.terminal_at = time.monotonic(); entry.result = result
            logger.warning("CEP query %s → failed (timeout)", query_id)
            return entry

    async def get_or_remove_expired(self, query_id: str) -> CepQueryEntry | None:
        async with self._lock:
            entry = self._get_entry(query_id)
            if entry is None: return None
            if entry.query_status in ("completed", "failed", "cancelled"):
                expired = (entry.terminal_at is not None and time.monotonic() - entry.terminal_at > settings.pi_cep_result_ttl_seconds) or (entry.expires_at is not None and entry.expires_at <= self._now())
                if expired:
                    if self.session_factory:
                        with self.session_factory() as session:
                            session.execute(delete(CepQueryOperation).where(CepQueryOperation.query_id == query_id)); session.commit()
                    self._entries.pop(query_id, None)
                    return None
            return entry

    async def remove_unaccepted(self, query_id: str) -> None:
        async with self._lock:
            if self.session_factory:
                with self.session_factory() as session:
                    session.execute(delete(CepQueryOperation).where(CepQueryOperation.query_id == query_id)); session.commit()
            self._entries.pop(query_id, None)

    async def recover_interrupted(self) -> int:
        if not self.session_factory: return 0
        async with self._lock:
            now = self._now(); count = 0
            with self.session_factory() as session:
                rows = session.execute(select(CepQueryOperation).where(CepQueryOperation.status.in_(("pending", "running"))).with_for_update()).scalars().all()
                for row in rows:
                    entry = self._entry_from_row(row); result = self._build_timeout_result(entry, "CEP_INTERRUPTED_BY_RESTART")
                    row.status = "failed"; row.result_payload = result.model_dump(mode="json"); row.terminal_at = now; row.expires_at = now + timedelta(seconds=settings.pi_cep_result_ttl_seconds); row.updated_at = now; count += 1
                    entry.query_status = "failed"; entry.result = result; entry.terminal_at = time.monotonic(); entry.expires_at = row.expires_at
                session.commit()
            if count: logger.warning("CEP recovery marked %d interrupted operation(s) as failed", count)
            return count

    async def cleanup_expired(self) -> CleanupResult:
        async with self._lock:
            if not self.session_factory:
                now = time.monotonic(); expired=[]; timed_out=[]
                for entry in list(self._entries.values()):
                    if entry.query_status in ("completed", "failed", "cancelled") and entry.terminal_at is not None and now-entry.terminal_at > settings.pi_cep_result_ttl_seconds: expired.append(entry.query_id)
                    elif entry.query_status in ("pending", "running") and now-entry.created_at > settings.pi_cep_operation_timeout_seconds: entry.query_status="failed"; entry.terminal_at=now; entry.result=self._build_timeout_result(entry); timed_out.append(entry.query_id)
                for qid in expired: self._entries.pop(qid, None)
                return CleanupResult(expired, timed_out)
            now = self._now(); expired=[]; timed_out=[]
            with self.session_factory() as session:
                expired = [row[0] for row in session.execute(select(CepQueryOperation.query_id).where(CepQueryOperation.status.in_(("completed", "failed", "cancelled")), CepQueryOperation.expires_at <= now)).all()]
                if expired: session.execute(delete(CepQueryOperation).where(CepQueryOperation.query_id.in_(expired)))
                rows = session.execute(select(CepQueryOperation).where(CepQueryOperation.status.in_(("pending", "running")), CepQueryOperation.created_at <= now - timedelta(seconds=settings.pi_cep_operation_timeout_seconds)).with_for_update()).scalars().all()
                for row in rows:
                    entry=self._entry_from_row(row); result=self._build_timeout_result(entry); row.status="failed"; row.result_payload=result.model_dump(mode="json"); row.terminal_at=now; row.expires_at=now+timedelta(seconds=settings.pi_cep_result_ttl_seconds); row.updated_at=now; entry.query_status="failed"; entry.result=result; entry.terminal_at=time.monotonic(); entry.expires_at=row.expires_at; timed_out.append(row.query_id)
                session.commit()
            for qid in expired: self._entries.pop(qid, None)
            return CleanupResult(expired, timed_out)


_cep_query_store = CepQueryStore(SessionLocal)


def get_cep_query_store() -> CepQueryStore:
    return _cep_query_store
