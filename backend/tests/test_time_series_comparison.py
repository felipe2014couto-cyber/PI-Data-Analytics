from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.time_series import compare_time_series
from app.core.exceptions import QueryCancelledError
from app.schemas.pi import (
    QueryExecutionMetadata,
    TimeSeries,
    TimeSeriesComparisonRequest,
    TimeSeriesPoint,
    TimeSeriesSeries,
)
from app.services.query_registry import QueryRegistry


def request(kind: str = "periods") -> TimeSeriesComparisonRequest:
    return TimeSeriesComparisonRequest.model_validate({
        "comparison_type": kind,
        "contexts": [
            {"context_id": "A", "context_label": "Referencia", "tag_ids": [7], "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-01T01:00:00Z"},
            {"context_id": "B", "context_label": "Comparacao", "tag_ids": [7], "start_time": "2026-02-01T00:00:00Z", "end_time": "2026-02-01T01:00:00Z"},
        ],
        "query_id": "cmp-1",
    })


def result(start: datetime, end: datetime, value: object = 1.25) -> TimeSeries:
    return TimeSeries(
        start_time=start,
        end_time=end,
        mode="recorded",
        series=[TimeSeriesSeries(
            tag_id=7,
            tag_name="TAG.7",
            display_name="Temperatura",
            variable_type="TEMPERATURE",
            unit="C",
            points=[TimeSeriesPoint(timestamp=start, value=value, good=True)],
            source_point_count=1,
        )],
        query_execution=QueryExecutionMetadata(strategy="recorded_streamset", pi_points_received=1, cache_hit=False),
    )


class FakeLongService:
    def __init__(self) -> None:
        self.calls = []

    async def fetch_time_series(self, item, **kwargs):
        self.calls.append((item, kwargs))
        return result(item.start_time, item.end_time)


@pytest.mark.asyncio
async def test_same_tag_in_two_periods_has_distinct_identity_and_elapsed_axis() -> None:
    service = FakeLongService()
    registry = QueryRegistry()
    response = await compare_time_series(request(), service, registry)

    a = response.contexts[0].time_series.series[0]
    b = response.contexts[1].time_series.series[0]
    assert a.tag_id == b.tag_id == 7
    assert a.context_id == "A" and b.context_id == "B"
    assert a.series_instance_id != b.series_instance_id
    assert a.points[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert b.points[0].timestamp == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert a.points[0].elapsed_ms == b.points[0].elapsed_ms == 0
    assert [call[1] for call in service.calls] == [
        {"refresh": True, "query_id": "cmp-1", "store_cache": False, "preserve_all_points": True},
        {"refresh": True, "query_id": "cmp-1", "store_cache": False, "preserve_all_points": True},
    ]
    assert response.metadata.series_instance_count == 2
    assert response.metadata.complete is True
    assert registry.active_count == 0


@pytest.mark.asyncio
async def test_partial_context_is_explicit_and_does_not_expose_exception_text() -> None:
    class PartialService(FakeLongService):
        async def fetch_time_series(self, item, **kwargs):
            if item.start_time.month == 2:
                raise RuntimeError("internal secret")
            return await super().fetch_time_series(item, **kwargs)

    response = await compare_time_series(request(), PartialService(), QueryRegistry())
    assert response.metadata.partial is True
    assert response.metadata.complete is False
    assert response.contexts[0].complete is True
    assert response.contexts[1].error == {
        "code": "COMPARISON_CONTEXT_ERROR",
        "message": "Falha ao consultar o contexto.",
    }


def test_comparison_contract_requires_exactly_a_then_b_and_valid_period() -> None:
    raw = request().model_dump()
    raw["contexts"] = list(reversed(raw["contexts"]))
    with pytest.raises(ValidationError):
        TimeSeriesComparisonRequest.model_validate(raw)
    raw = request().model_dump()
    raw["contexts"][0]["end_time"] = raw["contexts"][0]["start_time"]
    with pytest.raises(ValidationError):
        TimeSeriesComparisonRequest.model_validate(raw)


@pytest.mark.asyncio
async def test_single_query_id_cancels_active_comparison() -> None:
    started = asyncio.Event()

    class BlockingService(FakeLongService):
        async def fetch_time_series(self, item, **kwargs):
            started.set()
            await asyncio.Event().wait()

    registry = QueryRegistry()
    task = asyncio.create_task(compare_time_series(request(), BlockingService(), registry))
    await started.wait()
    assert await registry.cancel("cmp-1") is True
    with pytest.raises(QueryCancelledError):
        await task
    assert registry.active_count == 0
