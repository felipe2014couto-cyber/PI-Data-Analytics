from datetime import datetime, timedelta, timezone

from app.schemas.pi import TimeSeriesRequest
from sqlalchemy import create_engine, text

from app.services.database_time_series_service import (
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
