import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.schemas.pi import TimeSeriesPoint, TimeSeriesRequest
from app.services.database_time_series_service import (
    DatabaseTimeSeriesService,
    PlotReadResult,
    _PLOT_AGGREGATES,
)


def _make_tag(tag_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=tag_id,
        active=True,
        pi_tag_name=name,
        display_name=name,
        engineering_unit="EU",
        equipment=None,
        section=None,
        variable_type=None,
    )


def _make_mock_service(tags: list[SimpleNamespace]) -> DatabaseTimeSeriesService:
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    service.repo = MagicMock()
    service.repo.get.side_effect = lambda tid: next((t for t in tags if t.id == tid), None)
    service._available_plot_aggregates = MagicMock(return_value=_PLOT_AGGREGATES)
    return service


@pytest.mark.asyncio
async def test_multi_tag_resolution_isolation() -> None:
    """Adding tags must NOT degrade the individual resolution of existing tags."""
    tags = [_make_tag(i, f"TAG_{i}") for i in range(1, 11)]
    service = _make_mock_service(tags)

    # Each tag has 100,000 raw points (dense series)
    service._count_qualified_raw_points = MagicMock(return_value=100000)

    # Return exactly 1497 points per tag from CAGG
    mock_points = [
        TimeSeriesPoint(
            timestamp=datetime(2026, 9, 17, 14, 25, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
            value=10.0 + i,
            plot_min=9.0,
            plot_max=11.0,
            plot_first=10.0,
            plot_last=10.5,
        )
        for i in range(1497)
    ]
    service._get_from_plot_coverage_aware = MagicMock(
        return_value=PlotReadResult(mock_points, [], [])
    )

    start = datetime(2026, 9, 17, 14, 25, tzinfo=timezone.utc)
    end = datetime(2026, 9, 24, 14, 25, tzinfo=timezone.utc)

    # Query with 1 tag
    res1 = await service.fetch_time_series(
        TimeSeriesRequest(tag_ids=[1], start_time=start, end_time=end, mode="recorded", target_points_per_tag=1500),
        refresh=True,
    )
    assert len(res1.series[0].points) == 1497

    # Query with 2 tags
    res2 = await service.fetch_time_series(
        TimeSeriesRequest(tag_ids=[1, 2], start_time=start, end_time=end, mode="recorded", target_points_per_tag=1500),
        refresh=True,
    )
    assert len(next(s for s in res2.series if s.tag_id == 1).points) == 1497

    # Query with 5 tags
    res5 = await service.fetch_time_series(
        TimeSeriesRequest(tag_ids=[1, 2, 3, 4, 5], start_time=start, end_time=end, mode="recorded", target_points_per_tag=1500),
        refresh=True,
    )
    assert len(next(s for s in res5.series if s.tag_id == 1).points) == 1497

    # Query with 10 tags
    res10 = await service.fetch_time_series(
        TimeSeriesRequest(tag_ids=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], start_time=start, end_time=end, mode="recorded", target_points_per_tag=1500),
        refresh=True,
    )
    assert len(next(s for s in res10.series if s.tag_id == 1).points) == 1497

    # Verify _count_qualified_raw_points was called PER TAG (single-element lists)
    for call in service._count_qualified_raw_points.call_args_list:
        tag_ids_arg = call.args[0]
        assert len(tag_ids_arg) == 1


@pytest.mark.asyncio
async def test_independent_planning_raw_and_cagg_per_tag() -> None:
    """Tag A with few raw points uses RAW; Tag B with dense points uses CAGG in the same query."""
    tags = [_make_tag(1, "SPARSE_TAG"), _make_tag(2, "DENSE_TAG")]
    service = _make_mock_service(tags)

    # Tag 1 has 300 points (below limit 5000), Tag 2 has 50,000 points
    def mock_count(tag_ids, start, end, limit):
        return 300 if tag_ids == [1] else 50000

    service._count_qualified_raw_points = MagicMock(side_effect=mock_count)

    base_dt = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    sparse_pts = [
        TimeSeriesPoint(timestamp=base_dt + timedelta(minutes=i), value=float(i))
        for i in range(50)
    ]
    dense_pts = [
        TimeSeriesPoint(timestamp=base_dt + timedelta(minutes=i), value=100.0)
        for i in range(1500)
    ]

    service._get_qualified_raw_points = MagicMock(return_value=sparse_pts)
    service._get_from_plot_coverage_aware = MagicMock(
        return_value=PlotReadResult(dense_pts, [], [])
    )

    with patch(
        "app.services.database_time_series_service.CoverageService.get_missing_intervals",
        return_value=[],
    ):
        start = datetime(2026, 9, 17, 14, 25, tzinfo=timezone.utc)
        end = datetime(2026, 9, 24, 14, 25, tzinfo=timezone.utc)
        res = await service.fetch_time_series(
            TimeSeriesRequest(tag_ids=[1, 2], start_time=start, end_time=end, mode="recorded", target_points_per_tag=1500),
            refresh=True,
        )

        assert res.query_execution is not None
        assert res.query_execution.source_aggregate_by_tag["SPARSE_TAG"] == "pi_samples_timescale"
        assert res.query_execution.source_aggregate_by_tag["DENSE_TAG"] == "pi_recorded_plot_5m"
        assert res.query_execution.returned_points_by_tag["SPARSE_TAG"] == 50
        assert res.query_execution.returned_points_by_tag["DENSE_TAG"] == 1500


def test_downsample_for_visual_uses_target_intervals() -> None:
    """_downsample_for_visual must generate buckets based on max_points (not max_points // 4)."""
    service = object.__new__(DatabaseTimeSeriesService)
    start = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    points = [
        TimeSeriesPoint(
            timestamp=start + timedelta(seconds=i * 2),
            value=float(i % 100),
        )
        for i in range(10000)
    ]
    target = 1500
    downsampled = service._downsample_for_visual(points, target, target_intervals=target)
    # Extrema expansion yields ~1500-4000 vertices, preserving real timestamps
    assert len(downsampled) >= 1000
    # First and last must be preserved
    assert downsampled[0].timestamp == points[0].timestamp
    assert downsampled[-1].timestamp == points[-1].timestamp
    # Min and max must be preserved
    orig_min = min(p.value for p in points)
    orig_max = max(p.value for p in points)
    down_min = min(p.value for p in downsampled)
    down_max = max(p.value for p in downsampled)
    assert orig_min == down_min
    assert orig_max == down_max


def test_coverage_aware_finer_cagg_precedence_over_7_days() -> None:
    """Finer CAGG covers entire period when available; daily CAGG does not truncate it."""
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = MagicMock()
    service._available_plot_aggregates = MagicMock(return_value=_PLOT_AGGREGATES)

    start = datetime(2026, 9, 17, 14, 25, tzinfo=timezone.utc)
    end = datetime(2026, 9, 24, 14, 25, tzinfo=timezone.utc)

    # 5m CAGG covers full 7 days. Daily CAGG starts next midnight.
    bounds = {
        "pi_recorded_plot_5m": (start, end - timedelta(minutes=5)),
        "pi_recorded_plot_hourly": (start, end - timedelta(hours=1)),
        "pi_recorded_plot_daily": (datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc), end - timedelta(days=1)),
    }
    def mock_db_exec(query, params=None):
        m = MagicMock()
        q_str = str(query)
        for name, bound in bounds.items():
            if name in q_str:
                m.one.return_value = bound
                return m
        m.one.return_value = (None, None)
        return m

    service.db.execute.side_effect = mock_db_exec

    service._get_from_plot = MagicMock(return_value=[
        TimeSeriesPoint(timestamp=start, value=1.0)
    ])
    service._get_from_raw_plot = MagicMock(return_value=[])

    result = service._get_from_plot_coverage_aware(
        23, start, end, "pi_recorded_plot_5m", display_bucket_seconds=404
    )

    # Verify that only 5m was called, covering the full 7 days
    assert len(result.segments) == 1
    assert result.segments[0]["source"] == "pi_recorded_plot_5m"
    assert result.segments[0]["start"] == start
    assert result.segments[0]["end"] == end
