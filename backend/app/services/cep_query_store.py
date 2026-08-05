"""In-memory store for CEP analysis operations.

This module provides the CepQueryStore which tracks the lifecycle of
asynchronous CEP analysis operations. It is the single source of truth
for operation state, timeout, TTL, and cancellation status.

The store does NOT depend on QueryRegistry — coordination between the
two is done by the caller (endpoint or lifecycle).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from app.core.config import settings
from app.schemas.cep_analysis import (
    CepAnalysisMetadata,
    CepAnalysisRequest,
    CepAnalysisResult,
    CepAnalysisSummary,
    CepDiagnostic,
    CepVariableSeries,
)

logger = logging.getLogger("pi_analytics_data.service.cep_query_store")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CepQueryEntry:
    """A single CEP analysis operation tracked by the store."""

    query_id: str
    query_status: str  # pending, running, completed, failed, cancelled
    created_at: float  # time.monotonic() — for timeout
    terminal_at: float | None = None  # time.monotonic() — for TTL
    started_at: datetime | None = None  # datetime UTC — public response
    request: CepAnalysisRequest | None = None
    result: CepAnalysisResult | None = None
    variable_series: dict[int, CepVariableSeries] = field(default_factory=dict)
    completed_variables: int = 0
    total_variables: int = 0
    completed_work_units: int = 0
    total_work_units: int = 0
    progress_percent: int = 0
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)


class CancelResult(Enum):
    """Result of a cancel operation."""

    CANCELLED = "cancelled"  # pending/running → cancelled (HTTP 200)
    ALREADY_CANCELLED = "already_cancelled"  # already cancelled (HTTP 200 idempotent)
    ALREADY_TERMINAL = "already_terminal"  # completed/failed (HTTP 409)
    NOT_FOUND = "not_found"  # not found or expired (HTTP 404)


@dataclass
class CleanupResult:
    """Result of a cleanup pass."""

    expired: list[str]  # IDs removed (terminal TTL expired)
    timed_out: list[str]  # IDs that became failed (operation timeout)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class CepQueryStore:
    """In-memory store for CEP analysis operations.

    All public methods are atomic under self._lock.
    The store does NOT depend on QueryRegistry.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._entries: dict[str, CepQueryEntry] = {}

    # -- Registration --

    async def register(
        self, query_id: str, request: CepAnalysisRequest,
        total_variables: int = 0,
        total_work_units: int | None = None,
    ) -> CepQueryEntry:
        """Register a new operation in pending state.

        The operational timeout starts here.
        """
        async with self._lock:
            entry = CepQueryEntry(
                query_id=query_id,
                query_status="pending",
                created_at=time.monotonic(),
                request=request,
                total_variables=max(0, total_variables),
                total_work_units=max(
                    0,
                    total_work_units if total_work_units is not None else total_variables,
                ),
            )
            self._entries[query_id] = entry
            logger.info("CEP query %s registered", query_id)
            return entry

    # -- State transitions --

    async def set_running(self, query_id: str) -> bool:
        """Transition pending → running. Returns False if already terminal."""
        async with self._lock:
            entry = self._entries.get(query_id)
            if entry is None:
                return False
            if entry.query_status not in ("pending",):
                return False
            entry.query_status = "running"
            entry.started_at = datetime.now(UTC)
            logger.info("CEP query %s → running", query_id)
            return True

    async def set_progress(
        self,
        query_id: str,
        completed_variables: int,
        completed_work_units: int | None = None,
    ) -> bool:
        """Record completed variables and real processing checkpoints."""
        async with self._lock:
            entry = self._entries.get(query_id)
            if entry is None or entry.query_status in ("completed", "failed", "cancelled"):
                return False
            completed = min(max(0, completed_variables), entry.total_variables)
            entry.completed_variables = max(entry.completed_variables, completed)
            if completed_work_units is None:
                work_completed = completed
            else:
                work_completed = min(max(0, completed_work_units), entry.total_work_units)
            entry.completed_work_units = max(entry.completed_work_units, work_completed)
            if entry.total_work_units:
                max_progress = 100 if completed_work_units is None else 99
                entry.progress_percent = max(
                    entry.progress_percent,
                    min(max_progress, max(0, round(entry.completed_work_units * 100 / entry.total_work_units))),
                )
            return True

    async def set_result(
        self, query_id: str, result: CepAnalysisResult, status: str,
        variable_series: dict[int, CepVariableSeries] | None = None,
    ) -> bool:
        """Transition to completed or failed. Returns False if already terminal."""
        async with self._lock:
            entry = self._entries.get(query_id)
            if entry is None:
                return False
            if entry.query_status in ("completed", "failed", "cancelled"):
                return False
            entry.query_status = status
            entry.terminal_at = time.monotonic()
            entry.result = result
            entry.variable_series = variable_series or {}
            if status == "completed":
                entry.completed_variables = entry.total_variables
                entry.completed_work_units = entry.total_work_units
                entry.progress_percent = 100
            entry.result = result.model_copy(update={
                "progress_percent": entry.progress_percent,
                "completed_variables": entry.completed_variables,
                "total_variables": entry.total_variables,
            })
            logger.info("CEP query %s → %s", query_id, status)
            return True

    async def set_cancelled(self, query_id: str) -> CancelResult:
        """Atomically attempt to cancel an operation."""
        async with self._lock:
            entry = self._entries.get(query_id)
            if entry is None:
                return CancelResult.NOT_FOUND
            if entry.query_status == "cancelled":
                return CancelResult.ALREADY_CANCELLED
            if entry.query_status in ("completed", "failed"):
                return CancelResult.ALREADY_TERMINAL
            # pending or running → cancelled
            entry.query_status = "cancelled"
            entry.terminal_at = time.monotonic()
            logger.info("CEP query %s → cancelled", query_id)
            return CancelResult.CANCELLED

    # -- Queries --

    async def get(self, query_id: str) -> CepQueryEntry | None:
        """Get an entry by query_id. Returns None if not found."""
        async with self._lock:
            return self._entries.get(query_id)

    # -- Timeout --

    async def apply_timeout(self, query_id: str) -> CepQueryEntry | None:
        """Apply operational timeout if deadline has passed.

        Returns the entry if timeout was applied (state changed to failed),
        None otherwise (operation doesn't exist, already terminal, or not expired).
        All mutations occur under the lock.
        """
        async with self._lock:
            entry = self._entries.get(query_id)
            if entry is None:
                return None
            if entry.query_status not in ("pending", "running"):
                return None
            now = time.monotonic()
            if now - entry.created_at > settings.pi_cep_operation_timeout_seconds:
                entry.query_status = "failed"
                entry.terminal_at = now
                entry.result = self._build_timeout_result(entry)
                logger.warning("CEP query %s → failed (timeout)", query_id)
                return entry
            return None

    # -- TTL --

    async def get_or_remove_expired(
        self, query_id: str
    ) -> CepQueryEntry | None:
        """Atomically get entry, removing it if terminal and TTL expired.

        - If entry doesn't exist: returns None (→ 404)
        - If entry is terminal and TTL expired: removes and returns None (→ 404)
        - If entry is terminal and TTL valid: returns entry (→ normal response)
        - If entry is not terminal: returns entry (→ normal response)
        """
        async with self._lock:
            entry = self._entries.get(query_id)
            if entry is None:
                return None
            if entry.query_status in ("completed", "failed", "cancelled"):
                if entry.terminal_at is not None:
                    now = time.monotonic()
                    if now - entry.terminal_at > settings.pi_cep_result_ttl_seconds:
                        self._entries.pop(query_id, None)
                        logger.info(
                            "CEP query %s removed (TTL expired)", query_id
                        )
                        return None
            return entry

    # -- Rollback --

    async def remove_unaccepted(self, query_id: str) -> None:
        """Remove an entry that was never accepted (registry registration failed).

        Called only during rollback in the endpoint.
        """
        async with self._lock:
            self._entries.pop(query_id, None)
            logger.info("CEP query %s removed (unaccepted rollback)", query_id)

    # -- Cleanup --

    async def cleanup_expired(self) -> CleanupResult:
        """Remove expired operations and apply timeouts.

        Returns the query_ids that need technical cancellation.
        The caller is responsible for coordinating with QueryRegistry.
        All reads and mutations occur under the lock.
        """
        async with self._lock:
            now = time.monotonic()
            expired_ids: list[str] = []
            timeout_ids: list[str] = []

            for entry in list(self._entries.values()):
                if entry.query_status in ("completed", "failed", "cancelled"):
                    if entry.terminal_at is not None:
                        if now - entry.terminal_at > settings.pi_cep_result_ttl_seconds:
                            expired_ids.append(entry.query_id)
                elif entry.query_status in ("pending", "running"):
                    if now - entry.created_at > settings.pi_cep_operation_timeout_seconds:
                        entry.query_status = "failed"
                        entry.terminal_at = now
                        entry.result = self._build_timeout_result(entry)
                        timeout_ids.append(entry.query_id)

            # Remove expired entries inside the lock
            for qid in expired_ids:
                self._entries.pop(qid, None)

            if expired_ids or timeout_ids:
                logger.info(
                    "CEP cleanup: expired=%d, timed_out=%d",
                    len(expired_ids),
                    len(timeout_ids),
                )

            return CleanupResult(expired=expired_ids, timed_out=timeout_ids)

    # -- Internal helpers --

    def _build_timeout_result(self, entry: CepQueryEntry) -> CepAnalysisResult:
        """Build a result for a timed-out operation."""
        now = datetime.now(UTC)
        summary = CepAnalysisSummary(
            analysis_status="failed",
            total_variables=0,
            period_start=now,
            period_end=now,
        )
        return CepAnalysisResult(
            query_id=entry.query_id,
            query_status="failed",
            summary=summary,
            variables=[],
            diagnostics=[
                CepDiagnostic(
                    tag_id=0,
                    tag_name="",
                    variable_ids=[],
                    error_code="OPERATION_TIMEOUT",
                    message="A operação excedeu o tempo limite configurado.",
                )
            ],
            metadata=CepAnalysisMetadata(),
            progress_percent=entry.progress_percent,
            completed_variables=entry.completed_variables,
            total_variables=entry.total_variables,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_cep_query_store = CepQueryStore()


def get_cep_query_store() -> CepQueryStore:
    return _cep_query_store
