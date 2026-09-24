import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.schemas.pi import TimeSeriesRequest
from sqlalchemy import create_engine, text

from app.core.exceptions import HistoricalDataNotLoadedError
from app.services.database_time_series_service import (
    DatabaseTimeSeriesService,
    _PLOT_AGGREGATES,
    _WEIGHTED_PLOT_AVERAGE_SQL,
    _dynamic_plot_plan,
    _plot_aggregate_for,
)


def _request(duration: timedelta) -> TimeSeriesRequest:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return TimeSeriesRequest(
        tag_ids=[20],
        start_time=start,
        end_time=start + duration,
        mode="recorded",
    )


def test_plot_planner_uses_five_minutes_for_seven_days() -> None:
    assert _plot_aggregate_for(_request(timedelta(days=7)), postgres=True) == (
        "pi_recorded_plot_5m",
        "5m",
    )


def test_plot_planner_keeps_short_and_long_range_levels() -> None:
    assert _plot_aggregate_for(_request(timedelta(hours=6)), postgres=True) == (
        "pi_recorded_plot_10s",
        "10s",
    )
    assert _plot_aggregate_for(_request(timedelta(days=1)), postgres=True) == (
        "pi_recorded_plot_1m",
        "1m",
    )
    assert _plot_aggregate_for(_request(timedelta(days=20)), postgres=True) == (
        "pi_recorded_plot_hourly",
        "1h",
    )
    assert _plot_aggregate_for(_request(timedelta(days=60)), postgres=True) == (
        "pi_recorded_plot_daily",
        "1d",
    )


def test_dynamic_planner_uses_raw_at_configured_boundary() -> None:
    plan = _dynamic_plot_plan(timedelta(hours=1), 1500, raw_point_count=5000, raw_point_limit=5000)
    assert plan.use_raw is True
    assert plan.view_name is None


def test_dynamic_planner_uses_aggregate_above_raw_boundary() -> None:
    plan = _dynamic_plot_plan(timedelta(days=1), 1500, raw_point_count=5001, raw_point_limit=5000)
    assert plan.use_raw is False
    assert plan.view_name == "pi_recorded_plot_10s"
    assert plan.display_bucket_seconds == 58


def test_dynamic_planner_selects_closest_source_not_coarser_than_ideal() -> None:
    plan = _dynamic_plot_plan(timedelta(days=7), 1500, raw_point_count=5001, raw_point_limit=5000)
    assert plan.view_name == "pi_recorded_plot_5m"
    assert plan.source_bucket_seconds == 300
    assert plan.display_bucket_seconds == 404


@pytest.mark.parametrize("duration,target", [
    (timedelta(hours=24), 1500),
    (timedelta(days=7), 1500),
    (timedelta(days=30), 1000),
])
def test_dynamic_planner_reproduces_target_resolution_without_overquantization(duration, target) -> None:
    plan = _dynamic_plot_plan(duration, target, raw_point_count=5001, raw_point_limit=5000)
    ideal = int(math.ceil(duration.total_seconds() / target))
    assert plan.display_bucket_seconds == max(plan.source_bucket_seconds, ideal)
    assert plan.source_bucket_seconds <= plan.display_bucket_seconds


def test_dynamic_planner_uses_closest_installed_level_when_one_minute_is_absent() -> None:
    installed = tuple(entry for entry in _PLOT_AGGREGATES if entry[1] != "pi_recorded_plot_1m")
    plan = _dynamic_plot_plan(
        timedelta(days=7),
        10000,
        raw_point_count=5001,
        raw_point_limit=5000,
        available_aggregates=installed,
    )
    assert plan.view_name == "pi_recorded_plot_5m"
    assert plan.source_bucket_seconds == 300
    assert plan.display_bucket_seconds == 300


def test_weighted_rebucketing_average_uses_sample_count() -> None:
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        value = connection.execute(text(f"""
            WITH buckets(avg_value, sample_count) AS (
                VALUES (10.0, 1), (20.0, 3)
            )
            SELECT {_WEIGHTED_PLOT_AVERAGE_SQL}
            FROM buckets
        """)).scalar_one()
    assert value == 17.5


def test_fixed_fallback_is_used_when_target_is_absent() -> None:
    request = _request(timedelta(days=1))
    assert request.target_points_per_tag is None
    assert _plot_aggregate_for(request, postgres=True) == ("pi_recorded_plot_1m", "1m")


def test_plot_extrema_query_scans_raw_samples_once_instead_of_per_bucket() -> None:
    service = object.__new__(DatabaseTimeSeriesService)
    result = MagicMock()
    result.fetchall.return_value = []
    service.db = MagicMock()
    service.db.execute.return_value = result

    service._get_from_plot(
        tag_id=20,
        start=datetime(2026, 9, 6, tzinfo=timezone.utc),
        end=datetime(2026, 9, 13, tzinfo=timezone.utc),
        view_name="pi_recorded_plot_5m",
        display_bucket_seconds=404,
    )

    statement = str(service.db.execute.call_args.args[0])
    assert "LEFT JOIN LATERAL" not in statement
    assert "JOIN pi_samples_timescale AS sample" in statement
    assert "GROUP BY populated.bucket" in statement
    assert "time_bucket_gapfill" not in statement
    assert "interpolated_value" not in statement


@pytest.mark.asyncio
async def test_dynamic_raw_path_requires_complete_recorded_coverage() -> None:
    start = datetime(2026, 9, 10, 15, 27, tzinfo=timezone.utc)
    request = TimeSeriesRequest(
        tag_ids=[20],
        start_time=start,
        end_time=start + timedelta(seconds=10),
        mode="recorded",
        resolution_mode="automatic",
        target_points_per_tag=1500,
    )
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    tag = SimpleNamespace(
        id=20,
        active=True,
        pi_tag_name="LFI_RB1_VEL_PROC_PV",
        engineering_unit="m/min",
        variable_type=None,
    )
    service.repo = MagicMock()
    service.repo.get.return_value = tag
    service._available_plot_aggregates = MagicMock(return_value=_PLOT_AGGREGATES)
    service._count_qualified_raw_points = MagicMock(return_value=12)
    service._get_qualified_raw_points = MagicMock()

    with patch(
        "app.services.database_time_series_service.CoverageService.get_missing_intervals",
        return_value=[(request.start_time, request.end_time)],
    ):
        with pytest.raises(HistoricalDataNotLoadedError) as raised:
            await service.fetch_time_series(request)

    assert raised.value.details["resolution"] == "recorded"
    assert raised.value.details["affected_tags"][0]["tag_id"] == 20
    service._get_qualified_raw_points.assert_not_called()


@pytest.mark.asyncio
async def test_query_metadata_exposes_effective_recorded_source_mode() -> None:
    request = _request(timedelta(days=7)).model_copy(update={"target_points_per_tag": 1500})
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    tag = SimpleNamespace(
        id=20,
        active=True,
        pi_tag_name="LFI_RB1_VEL_PROC_PV",
        display_name="Velocidade",
        engineering_unit="m/min",
        equipment=None,
        section=None,
        variable_type=None,
    )
    service.repo = MagicMock()
    service.repo.get.return_value = tag
    service._available_plot_aggregates = MagicMock(return_value=_PLOT_AGGREGATES)
    service._count_qualified_raw_points = MagicMock(return_value=5001)
    from app.services.database_time_series_service import PlotReadResult
    service._get_from_plot_coverage_aware = MagicMock(return_value=PlotReadResult([], [], []))

    result = await service.fetch_time_series(request)

    assert result.query_execution is not None
    assert result.query_execution.effective_source_mode == "RECORDED"


def test_gap_markers_are_null_and_no_numeric_value_is_invented() -> None:
    from app.schemas.pi import TimeSeriesPoint
    from app.services.database_time_series_service import PlotReadResult

    service = object.__new__(DatabaseTimeSeriesService)
    service._available_plot_aggregates = MagicMock(return_value=((3600, "pi_recorded_plot_hourly", "1h"),))
    service.db = MagicMock()
    service.db.execute.return_value.one.return_value = (
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 6, tzinfo=timezone.utc),
    )
    service._get_from_plot = MagicMock(return_value=[
        TimeSeriesPoint(timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc), value=0.0),
        TimeSeriesPoint(timestamp=datetime(2026, 9, 1, 6, tzinfo=timezone.utc), value=5.0),
    ])
    service._get_from_raw_plot = MagicMock(return_value=[])

    result = service._get_from_plot_coverage_aware(
        20, datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 7, tzinfo=timezone.utc),
        "pi_recorded_plot_hourly", display_bucket_seconds=3600,
    )

    assert isinstance(result, PlotReadResult)
    assert [point.value for point in result.points] == [0.0, None, 5.0]
    assert result.points == sorted(result.points, key=lambda point: point.timestamp)
