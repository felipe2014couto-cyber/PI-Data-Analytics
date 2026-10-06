from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.schemas.pi import TimeSeriesPoint
from app.services.database_time_series_service import (
    DatabaseTimeSeriesService,
    PlotReadResult,
)


UTC = timezone.utc


def _point(ts: datetime, value: float, **kwargs) -> TimeSeriesPoint:
    return TimeSeriesPoint(timestamp=ts, value=value, **kwargs)


def test_four_hour_recorded_interval_with_complete_coverage_has_no_sentinel():
    start = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    end = start + timedelta(hours=4)
    points = [
        _point(start, 0.05000014),
        _point(end, 0.153280631),
    ]

    result = DatabaseTimeSeriesService._insert_coverage_sentinels(points, [])

    assert result == points
    assert not any(point.is_render_sentinel for point in result)
    assert [point.value for point in result] == [0.05000014, 0.153280631]


def test_empty_confirmed_interval_does_not_create_sentinel():
    start = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    end = start + timedelta(hours=4)
    # CoverageService treats EMPTY_CONFIRMED as covered, yielding no missing ranges.
    points = [_point(start, 0.0), _point(end, -2.5)]

    result = DatabaseTimeSeriesService._insert_coverage_sentinels(points, [])

    assert [point.value for point in result] == [0.0, -2.5]
    assert not any(point.is_render_sentinel for point in result)


def test_explicit_uncovered_interval_inserts_one_render_sentinel_and_preserves_events():
    start = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    end = start + timedelta(hours=4)
    points = [
        _point(start, 0.0, good=True),
        _point(end, -2.5, good=True, questionable=True, substituted=True),
    ]

    result = DatabaseTimeSeriesService._insert_coverage_sentinels(
        points,
        [(start + timedelta(hours=1), start + timedelta(hours=2))],
    )

    sentinels = [point for point in result if point.is_render_sentinel]
    assert len(sentinels) == 1
    assert start < sentinels[0].timestamp < end
    assert [point.value for point in result if not point.is_render_sentinel] == [0.0, -2.5]
    assert result[-1].good is True
    assert result[-1].questionable is True
    assert result[-1].substituted is True


def test_plot_coverage_status_uses_coverage_not_bucket_end_or_missing_cagg_bucket():
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = MagicMock()
    service._available_plot_aggregates = MagicMock(return_value=((60, "pi_recorded_plot_1m", "1m"),))
    start = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=19)
    real_last = end - timedelta(milliseconds=90)
    service.db.execute.return_value.one.return_value = (start, end - timedelta(minutes=1))
    service._get_from_plot = MagicMock(return_value=[
        TimeSeriesPoint(
            timestamp=end - timedelta(minutes=2),
            value=0.08,
            plot_first=0.07,
            plot_last=0.08,
            plot_first_ts=end - timedelta(minutes=3),
            plot_last_ts=real_last,
            plot_sample_count=4,
        )
    ])
    service._get_from_raw_plot = MagicMock(return_value=[])
    service._get_recorded_boundary_seed = MagicMock(return_value=None)

    # COMPLETE coverage reaches the request end even though the visual bucket
    # timestamp itself is earlier, and may include an EMPTY_CONFIRMED stretch.
    with patch(
        "app.services.database_time_series_service.CoverageService.get_missing_intervals",
        return_value=[],
    ):
        result = service._get_from_plot_coverage_aware(
            20, start, end, "pi_recorded_plot_1m", display_bucket_seconds=74
        )

    assert result.uncovered == []
    assert result.points[0].plot_last_ts == real_last
    assert not any(point.is_render_sentinel for point in result.points)


def test_plot_query_marks_partial_and_inserts_sentinel_for_explicit_coverage_gap():
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = MagicMock()
    service._available_plot_aggregates = MagicMock(return_value=((60, "pi_recorded_plot_1m", "1m"),))
    start = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=19)
    left = _point(start + timedelta(minutes=2), 1.0)
    right = _point(start + timedelta(minutes=16), 2.0)
    service.db.execute.return_value.one.return_value = (start, end - timedelta(minutes=1))
    service._get_from_plot = MagicMock(return_value=[left, right])
    gap = (start + timedelta(minutes=8), start + timedelta(minutes=12))
    service._get_recorded_boundary_seed = MagicMock(return_value=None)

    with patch(
        "app.services.database_time_series_service.CoverageService.get_missing_intervals",
        return_value=[gap],
    ):
        result = service._get_from_plot_coverage_aware(20, start, end, "pi_recorded_plot_1m")

    assert result.uncovered == [{
        "tag_id": 20,
        "start": gap[0],
        "end": gap[1],
        "reason": "uncovered_coverage",
    }]
    assert sum(point.is_render_sentinel for point in result.points) == 1


def test_fully_confirmed_empty_plot_window_is_complete_not_partial():
    service = object.__new__(DatabaseTimeSeriesService)
    service.db = MagicMock()
    service._available_plot_aggregates = MagicMock(return_value=((60, "pi_recorded_plot_1m", "1m"),))
    service.db.execute.return_value.one.return_value = (None, None)
    service._get_from_raw_plot = MagicMock(return_value=[])
    start = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    end = start + timedelta(hours=4)

    with patch(
        "app.services.database_time_series_service.CoverageService.get_missing_intervals",
        return_value=[],
    ):
        result = service._get_from_plot_coverage_aware(20, start, end, "pi_recorded_plot_1m")

    assert isinstance(result, PlotReadResult)
    assert result.points == []
    assert result.uncovered == []
