"""Tests for CepQueryStore — state transitions, TTL, timeout, cleanup."""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.schemas.cep_analysis import (
    CepAnalysisMetadata,
    CepAnalysisRequest,
    CepAnalysisResult,
    CepAnalysisSummary,
)
from app.services.cep_query_store import CancelResult, CepQueryStore


def _make_request() -> CepAnalysisRequest:
    return CepAnalysisRequest(
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _make_result(query_id: str, status: str = "completed") -> CepAnalysisResult:
    now = datetime.now(UTC)
    return CepAnalysisResult(
        query_id=query_id,
        query_status=status,
        summary=CepAnalysisSummary(
            analysis_status="completed",
            total_variables=0,
            period_start=now,
            period_end=now,
        ),
        variables=[],
        metadata=CepAnalysisMetadata(),
    )


@pytest.mark.asyncio
async def test_register_creates_pending():
    store = CepQueryStore()
    entry = await store.register("q1", _make_request())
    assert entry.query_id == "q1"
    assert entry.query_status == "pending"
    assert entry.request is not None


@pytest.mark.asyncio
async def test_set_running_transitions_pending():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    ok = await store.set_running("q1")
    assert ok is True
    entry = await store.get("q1")
    assert entry.query_status == "running"
    assert entry.started_at is not None


@pytest.mark.asyncio
async def test_progress_tracks_completed_variables_and_is_bounded():
    store = CepQueryStore()
    await store.register("q-progress", _make_request(), total_variables=4)
    await store.set_running("q-progress")

    assert await store.set_progress("q-progress", 2) is True
    entry = await store.get("q-progress")
    assert entry.completed_variables == 2
    assert entry.progress_percent == 50

    await store.set_progress("q-progress", 99)
    entry = await store.get("q-progress")
    assert entry.completed_variables == 4
    assert entry.progress_percent == 100


@pytest.mark.asyncio
async def test_progress_tracks_real_work_units_without_completing_before_finalization():
    store = CepQueryStore()
    await store.register("q-work", _make_request(), total_variables=12, total_work_units=15)
    await store.set_running("q-work")

    await store.set_progress("q-work", 0, completed_work_units=1)
    entry = await store.get("q-work")
    assert entry.progress_percent == 7
    assert entry.completed_variables == 0

    await store.set_progress("q-work", 1, completed_work_units=3)
    entry = await store.get("q-work")
    assert entry.progress_percent == 20
    assert entry.completed_variables == 1

    await store.set_progress("q-work", 12, completed_work_units=14)
    entry = await store.get("q-work")
    assert entry.progress_percent == 93
    assert entry.progress_percent < 100

    await store.set_result("q-work", _make_result("q-work"), "completed")
    entry = await store.get("q-work")
    assert entry.progress_percent == 100
    assert entry.completed_variables == 12


@pytest.mark.asyncio
async def test_progress_is_preserved_when_cancelled():
    store = CepQueryStore()
    await store.register("q-cancel-progress", _make_request(), total_variables=2)
    await store.set_running("q-cancel-progress")
    await store.set_progress("q-cancel-progress", 1)
    await store.set_cancelled("q-cancel-progress")
    entry = await store.get("q-cancel-progress")
    assert entry.progress_percent == 50


@pytest.mark.asyncio
async def test_set_running_refuses_terminal():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_result("q1", _make_result("q1"), "completed")
    ok = await store.set_running("q1")
    assert ok is False


@pytest.mark.asyncio
async def test_set_result_transitions_to_completed():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_running("q1")
    result = _make_result("q1")
    ok = await store.set_result("q1", result, "completed")
    assert ok is True
    entry = await store.get("q1")
    assert entry.query_status == "completed"
    assert entry.terminal_at is not None
    assert entry.result is not None


@pytest.mark.asyncio
async def test_set_result_transitions_to_failed():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    result = _make_result("q1", "failed")
    ok = await store.set_result("q1", result, "failed")
    assert ok is True
    entry = await store.get("q1")
    assert entry.query_status == "failed"


@pytest.mark.asyncio
async def test_set_result_does_not_overwrite_terminal():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_result("q1", _make_result("q1"), "completed")
    ok = await store.set_result("q1", _make_result("q1", "failed"), "failed")
    assert ok is False
    entry = await store.get("q1")
    assert entry.query_status == "completed"


@pytest.mark.asyncio
async def test_set_cancelled_from_pending():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    result = await store.set_cancelled("q1")
    assert result == CancelResult.CANCELLED
    entry = await store.get("q1")
    assert entry.query_status == "cancelled"


@pytest.mark.asyncio
async def test_set_cancelled_from_running():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_running("q1")
    result = await store.set_cancelled("q1")
    assert result == CancelResult.CANCELLED


@pytest.mark.asyncio
async def test_set_cancelled_already_cancelled():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_cancelled("q1")
    result = await store.set_cancelled("q1")
    assert result == CancelResult.ALREADY_CANCELLED


@pytest.mark.asyncio
async def test_set_cancelled_already_terminal():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_result("q1", _make_result("q1"), "completed")
    result = await store.set_cancelled("q1")
    assert result == CancelResult.ALREADY_TERMINAL


@pytest.mark.asyncio
async def test_set_cancelled_not_found():
    store = CepQueryStore()
    result = await store.set_cancelled("nonexistent")
    assert result == CancelResult.NOT_FOUND


@pytest.mark.asyncio
async def test_apply_timeout_when_expired():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    # Manually set created_at to the past
    entry = await store.get("q1")
    entry.created_at = time.monotonic() - settings.pi_cep_operation_timeout_seconds - 1
    result = await store.apply_timeout("q1")
    assert result is not None
    assert result.query_status == "failed"
    assert result.result is not None


@pytest.mark.asyncio
async def test_apply_timeout_when_not_expired():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    result = await store.apply_timeout("q1")
    assert result is None


@pytest.mark.asyncio
async def test_apply_timeout_refuses_terminal():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    entry = await store.get("q1")
    entry.created_at = time.monotonic() - settings.pi_cep_operation_timeout_seconds - 1
    await store.set_result("q1", _make_result("q1"), "completed")
    result = await store.apply_timeout("q1")
    assert result is None


@pytest.mark.asyncio
async def test_get_or_remove_expired_removes_terminal():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_result("q1", _make_result("q1"), "completed")
    entry = await store.get("q1")
    entry.terminal_at = time.monotonic() - settings.pi_cep_result_ttl_seconds - 1
    result = await store.get_or_remove_expired("q1")
    assert result is None
    assert await store.get("q1") is None


@pytest.mark.asyncio
async def test_get_or_remove_expired_keeps_valid_terminal():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.set_result("q1", _make_result("q1"), "completed")
    result = await store.get_or_remove_expired("q1")
    assert result is not None
    assert result.query_status == "completed"


@pytest.mark.asyncio
async def test_remove_unaccepted():
    store = CepQueryStore()
    await store.register("q1", _make_request())
    await store.remove_unaccepted("q1")
    assert await store.get("q1") is None


@pytest.mark.asyncio
async def test_cleanup_expired_removes_and_times_out():
    store = CepQueryStore()
    # Create expired terminal
    await store.register("q1", _make_request())
    await store.set_result("q1", _make_result("q1"), "completed")
    entry1 = await store.get("q1")
    entry1.terminal_at = time.monotonic() - settings.pi_cep_result_ttl_seconds - 1
    # Create timed-out pending
    await store.register("q2", _make_request())
    entry2 = await store.get("q2")
    entry2.created_at = time.monotonic() - settings.pi_cep_operation_timeout_seconds - 1

    result = await store.cleanup_expired()
    assert "q1" in result.expired
    assert "q2" in result.timed_out
    assert await store.get("q1") is None
    entry2_after = await store.get("q2")
    assert entry2_after.query_status == "failed"


@pytest.mark.asyncio
async def test_concurrent_operations():
    store = CepQueryStore()
    # Register multiple operations concurrently
    tasks = [store.register(f"q{i}", _make_request()) for i in range(10)]
    await asyncio.gather(*tasks)
    # All should be present
    for i in range(10):
        entry = await store.get(f"q{i}")
        assert entry is not None
        assert entry.query_status == "pending"
