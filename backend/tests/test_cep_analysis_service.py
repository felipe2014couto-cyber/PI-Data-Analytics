"""Tests for CepAnalysisService — orchestration, compliance, Recorded."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.integrations.pi.provider import PiPoint
from app.schemas.cep_analysis import (
    CepAnalysisRequest,
    MaterializedAnalysisData,
    MaterializedTag,
    MaterializedVariable,
)
from app.services.cep_analysis_service import CepAnalysisService
from app.services.cep_query_store import CepQueryStore
from app.services.query_registry import QueryRegistry
from tests.pi_fakes import FakePiDataProvider, make_value


def _ts(year=2026, month=1, day=1, hour=0):
    return datetime(year, month, day, hour, 0, 0, tzinfo=UTC)


def _make_variable(
    var_id: int = 1,
    reading_tag_id: int = 10,
    lower_tag_id: int = 11,
    upper_tag_id: int = 12,
    target_tag_id: int | None = None,
) -> MaterializedVariable:
    return MaterializedVariable(
        id=var_id,
        code=f"VAR_{var_id:02d}",
        name=f"Variable {var_id}",
        equipment_id=1,
        section_id=1,
        variable_type_id=1,
        reading_tag_id=reading_tag_id,
        lower_limit_tag_id=lower_tag_id,
        upper_limit_tag_id=upper_tag_id,
        target_tag_id=target_tag_id,
    )


def _make_tag(tag_id: int, name: str, web_id: str | None = None) -> MaterializedTag:
    return MaterializedTag(
        id=tag_id,
        pi_tag_name=name,
        pi_server="PI_DATA",
        pi_web_id=web_id or f"W{tag_id}",
    )


def _make_materialized(
    variables: list[MaterializedVariable],
    tags: list[MaterializedTag],
    include_recorded: bool = False,
    start_time: datetime = None,
    end_time: datetime = None,
) -> MaterializedAnalysisData:
    tag_variable_map = {}
    for var in variables:
        for tag_id in [var.reading_tag_id, var.lower_limit_tag_id,
                       var.upper_limit_tag_id, var.target_tag_id]:
            if tag_id is not None:
                tag_variable_map.setdefault(tag_id, []).append(var.id)

    return MaterializedAnalysisData(
        request=CepAnalysisRequest(
            start_time=start_time or _ts(),
            end_time=end_time or _ts(day=2),
            include_recorded=include_recorded,
        ),
        variables=variables,
        tag_variable_map=tag_variable_map,
        unique_tags=tags,
    )


def _make_interpolated_values(tag_id: int, values: list) -> dict:
    """Create interpolated data dict mapping tag_id_str → PiValue list."""
    return {str(tag_id): values}


@pytest.mark.asyncio
async def test_success_total():
    """Scenario 8: All variables processed successfully."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        }
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result is not None
    assert entry.result.summary.analysis_status == "completed"
    assert entry.result.summary.conformant_variables == 1
    assert entry.result.summary.non_conformant_variables == 0


@pytest.mark.asyncio
async def test_resolves_missing_webids_before_interpolated_fetch():
    """CEP must not classify valid variables as no-data just because the cache is empty."""
    paths = {
        r"\\PI_DATA\reading": PiPoint(web_id="W10", name="reading"),
        r"\\PI_DATA\lower": PiPoint(web_id="W11", name="lower"),
        r"\\PI_DATA\upper": PiPoint(web_id="W12", name="upper"),
    }
    provider = FakePiDataProvider(
        points=paths,
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()
    var = _make_variable()
    tags = [
        MaterializedTag(id=10, pi_tag_name="reading", pi_server="PI_DATA", pi_web_id=None),
        MaterializedTag(id=11, pi_tag_name="lower", pi_server="PI_DATA", pi_web_id=None),
        MaterializedTag(id=12, pi_tag_name="upper", pi_server="PI_DATA", pi_web_id=None),
    ]
    materialized = _make_materialized([var], tags)

    await store.register("q-resolve", materialized.request)
    task = asyncio.create_task(service.run_analysis("q-resolve", materialized, store, registry))
    await registry.register("q-resolve", main_task=task)
    entry = await store.get("q-resolve")
    entry.ready_event.set()
    await task

    entry = await store.get("q-resolve")
    assert provider.resolve_calls == [r"\\PI_DATA\reading", r"\\PI_DATA\lower", r"\\PI_DATA\upper"]
    assert entry.result is not None
    assert entry.result.variables[0].status == "processed"
    assert entry.result.variables[0].total_points == 1
    assert entry.result.metadata.webid_resolved == 3
    assert entry.result.metadata.pi_points_received == 3


@pytest.mark.asyncio
async def test_interpolated_batch_keeps_each_tag_associated_with_its_webid():
    provider = FakePiDataProvider(
        interpolated={
            "W_SHARED": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W_UPPER": [make_value("2026-01-01T00:05:00Z", 60.0)],
        }
    )
    service = CepAnalysisService(provider)

    values, diagnostics = await service._fetch_interpolated(
        {10: "W_SHARED", -20: "W_SHARED", -21: "W_UPPER"},
        _ts(), _ts(day=2), "5m",
    )

    assert diagnostics == []
    assert values["10"][0].value == 50.0
    assert values["-20"][0].value == 50.0
    assert values["-21"][0].value == 60.0


@pytest.mark.asyncio
async def test_success_partial():
    """Scenario 9: Mix of processed and error variables."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
            # Second variable will have no data → error
        }
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var1 = _make_variable(1, 10, 11, 12)
    var2 = _make_variable(2, 20, 21, 22)
    tags = [
        _make_tag(10, "r1", "W10"), _make_tag(11, "l1", "W11"), _make_tag(12, "u1", "W12"),
        _make_tag(20, "r2", "W20"), _make_tag(21, "l2", "W21"), _make_tag(22, "u2", "W22"),
    ]
    materialized = _make_materialized([var1, var2], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    # var1 has data, var2 has no data → var2 is no_data, not error
    assert entry.result.summary.analysis_status == "completed"
    assert entry.result.summary.total_variables == 2


@pytest.mark.asyncio
async def test_failure_total():
    """Scenario 10: All variables fail."""
    provider = FakePiDataProvider(
        raise_on_interpolated=Exception("PI unavailable")
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "failed"
    assert entry.result.summary.analysis_status == "failed"


@pytest.mark.asyncio
async def test_no_data_variables():
    """Scenario 4: Variables with no points → no_data."""
    provider = FakePiDataProvider(interpolated={})
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.summary.analysis_status == "completed"
    assert entry.result.summary.no_data_variables == 1
    assert entry.result.variables[0].status == "no_data"


@pytest.mark.asyncio
async def test_overall_pct_with_denominator():
    """Scenario 43: overall_pct calculated when denominator > 0."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        }
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.result.summary.overall_pct is not None
    assert entry.result.summary.overall_pct == 100.0


@pytest.mark.asyncio
async def test_overall_pct_none_when_no_eligible():
    """Scenario 44: overall_pct is None when no eligible points."""
    provider = FakePiDataProvider(interpolated={})
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.result.summary.overall_pct is None


@pytest.mark.asyncio
async def test_tags_deduplicated():
    """Scenario 7: Shared tags are deduplicated."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        }
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    # Two variables sharing the same lower_limit_tag
    var1 = _make_variable(1, 10, 11, 12)
    var2 = _make_variable(2, 20, 11, 22)  # shares tag 11
    tags = [
        _make_tag(10, "r1", "W10"), _make_tag(11, "lower", "W11"),
        _make_tag(12, "u1", "W12"), _make_tag(20, "r2", "W20"), _make_tag(22, "u2", "W22"),
    ]
    materialized = _make_materialized([var1, var2], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.summary.total_variables == 2


@pytest.mark.asyncio
async def test_include_recorded_false():
    """Scenario 27: No Recorded calls when include_recorded=false."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        }
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags, include_recorded=False)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.recorded_series is None
    assert len(provider.recorded_calls) == 0


@pytest.mark.asyncio
async def test_include_recorded_true():
    """Scenario 28: Recorded series present when include_recorded=true."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
        recorded={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags, include_recorded=True)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.recorded_series is not None


@pytest.mark.asyncio
async def test_cancellation_during_execution():
    """Scenario 23: CancelledError doesn't convert failed to cancelled."""

    # Create a provider that delays to allow cancellation
    class SlowProvider(FakePiDataProvider):
        async def get_interpolated_values_batch(self, web_ids, start_time, end_time, interval, max_count=None):
            await asyncio.sleep(1.0)  # Slow enough to be cancelled
            return await super().get_interpolated_values_batch(web_ids, start_time, end_time, interval, max_count)

    provider = SlowProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        }
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()

    # Cancel the task before it completes
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    entry = await store.get(query_id)
    # Should be cancelled (set_cancelled was called in the except block)
    assert entry.query_status == "cancelled"


@pytest.mark.asyncio
async def test_exception_generates_failed():
    """Scenario 9: Unhandled exception → failed."""
    provider = FakePiDataProvider()
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags)

    query_id = "q1"
    await store.register(query_id, materialized.request)

    # Mock _fetch_interpolated to raise
    with patch.object(service, '_fetch_interpolated', side_effect=Exception("test error")):
        task = asyncio.create_task(
            service.run_analysis(query_id, materialized, store, registry)
        )
        await registry.register(query_id, main_task=task)
        entry = await store.get(query_id)
        entry.ready_event.set()
        await task

    entry = await store.get(query_id)
    assert entry.query_status == "failed"
    assert entry.result.summary.analysis_status == "failed"


@pytest.mark.asyncio
async def test_recorded_individual_truncation_flag_false():
    """Scenario 29: Individual truncation doesn't set aggregate flag."""
    # Create a tag with exactly individual_limit points
    individual_limit = settings.pi_cep_recorded_max_points_per_tag
    # Generate timestamps within valid range (0-23 hours)
    recorded_values = []
    for i in range(individual_limit):
        h = i % 24
        m = (i // 24) % 60
        recorded_values.append(make_value(f"2026-01-01T{h:02d}:{m:02d}:00Z", float(i)))

    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
        recorded={"W10": recorded_values + [make_value("2026-01-01T23:59:00Z", 99.0)]},
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags, include_recorded=True)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.metadata.recorded_total_limit_reached is False


@pytest.mark.asyncio
async def test_recorded_aggregate_truncation_flag_true():
    """Scenario 30: Aggregate truncation sets flag."""
    # Create enough tags to exhaust the aggregate limit
    # Need tags such that remaining_aggregate < individual_limit for at least one tag
    individual_limit = settings.pi_cep_recorded_max_points_per_tag
    aggregate_limit = settings.pi_cep_recorded_max_total_points

    # Create 12 tags, each with many points
    # After processing 10 tags (10 * 10000 = 100000), aggregate is exhausted
    # Tags 11 and 12 will not be acquired
    def make_recorded_values(count):
        values = []
        for i in range(count):
            h = i % 24
            m = (i // 24) % 60
            values.append(make_value(f"2026-01-01T{h:02d}:{m:02d}:00Z", float(i)))
        return values

    tags = []
    recorded = {}
    for i in range(12):
        tag_id = 10 + i
        web_id = f"W{tag_id}"
        name = f"tag_{tag_id:02d}"
        tags.append(_make_tag(tag_id, name, web_id))
        recorded[web_id] = make_recorded_values(individual_limit + 5)

    provider = FakePiDataProvider(
        interpolated={f"W{10+i}": [make_value("2026-01-01T00:05:00Z", 50.0)] for i in range(12)},
        recorded=recorded,
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    # Create variables using these tags
    variables = []
    for i in range(4):
        var = _make_variable(
            var_id=i+1,
            reading_tag_id=10 + i*3,
            lower_tag_id=11 + i*3,
            upper_tag_id=12 + i*3,
        )
        variables.append(var)

    tag_variable_map = {}
    for var in variables:
        for tag_id in [var.reading_tag_id, var.lower_limit_tag_id, var.upper_limit_tag_id]:
            tag_variable_map.setdefault(tag_id, []).append(var.id)

    materialized = MaterializedAnalysisData(
        request=CepAnalysisRequest(
            start_time=_ts(),
            end_time=_ts(day=2),
            include_recorded=True,
        ),
        variables=variables,
        tag_variable_map=tag_variable_map,
        unique_tags=tags,
    )

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    # Aggregate limit should be reached
    assert entry.result.metadata.recorded_total_limit_reached is True
    assert len(entry.result.metadata.recorded_tags_not_acquired) > 0


@pytest.mark.asyncio
async def test_recorded_lexicographic_order():
    """Scenario 36: Tags processed in lexicographic order."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
        recorded={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    # Tags in reverse order to test sorting
    tags = [_make_tag(12, "zzz_upper", "W12"), _make_tag(10, "aaa_reading", "W10"), _make_tag(11, "mmm_lower", "W11")]
    materialized = _make_materialized([var], tags, include_recorded=True)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    if entry.result.recorded_series:
        # Should be sorted lexicographically
        names = [s.tag_name for s in entry.result.recorded_series]
        assert names == sorted(names)


@pytest.mark.asyncio
async def test_source_point_count_null_when_truncated():
    """Scenario 32: source_point_count is None when truncated."""
    individual_limit = settings.pi_cep_recorded_max_points_per_tag
    # Create more points than the limit
    recorded_values = []
    for i in range(individual_limit + 5):
        h = i % 24
        m = (i // 24) % 60
        recorded_values.append(make_value(f"2026-01-01T{h:02d}:{m:02d}:00Z", float(i)))

    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
        recorded={"W10": recorded_values},
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags, include_recorded=True)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.recorded_series is not None
    for series in entry.result.recorded_series:
        if series.truncated:
            assert series.source_point_count is None


@pytest.mark.asyncio
async def test_source_point_count_exact_when_complete():
    """Scenario 33: source_point_count is exact when complete."""
    provider = FakePiDataProvider(
        interpolated={
            "W10": [make_value("2026-01-01T00:05:00Z", 50.0)],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
        recorded={
            "W10": [
                make_value("2026-01-01T00:05:00Z", 50.0),
                make_value("2026-01-01T00:10:00Z", 51.0),
            ],
            "W11": [make_value("2026-01-01T00:05:00Z", 40.0)],
            "W12": [make_value("2026-01-01T00:05:00Z", 60.0)],
        },
    )
    service = CepAnalysisService(provider)
    store = CepQueryStore()
    registry = QueryRegistry()

    var = _make_variable()
    tags = [_make_tag(10, "reading", "W10"), _make_tag(11, "lower", "W11"), _make_tag(12, "upper", "W12")]
    materialized = _make_materialized([var], tags, include_recorded=True)

    query_id = "q1"
    await store.register(query_id, materialized.request)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )
    await registry.register(query_id, main_task=task)
    entry = await store.get(query_id)
    entry.ready_event.set()
    await task

    entry = await store.get(query_id)
    assert entry.query_status == "completed"
    assert entry.result.recorded_series is not None
    for series in entry.result.recorded_series:
        if not series.truncated:
            assert series.source_point_count == len(series.points)
