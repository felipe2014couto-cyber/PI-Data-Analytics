from datetime import datetime, timedelta, timezone

from app.schemas.pi import TimeSeriesPoint
from app.services.database_time_series_service import DatabaseTimeSeriesService


def _pts(specs):
    base = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
    out = []
    for i, (seconds, value) in enumerate(specs):
        out.append(TimeSeriesPoint(
            timestamp=base + timedelta(seconds=seconds if seconds is not None else i * 10),
            value=value, good=True, questionable=False, substituted=False))
    return out


def _svc():
    return DatabaseTimeSeriesService.__new__(DatabaseTimeSeriesService)


def test_out_of_order_input_is_sorted_first():
    points = _pts([(0, 5.0), (50, 1.0), (10, 9.0), (30, 0.0), (20, 3.0)])
    shuffled = [points[2], points[0], points[4], points[1], points[3]]
    result = _svc()._downsample_for_visual(shuffled, 4)
    ts = [p.timestamp for p in result]
    assert ts == sorted(ts)
    assert min(p.value for p in result) == 0.0
    assert max(p.value for p in result) == 9.0


def test_min_before_max_and_max_before_min_orderings():
    a = _pts([(0, 1.0), (10, 0.0), (20, 5.0), (30, 2.0)])
    b = _pts([(0, 3.0), (10, 5.0), (20, 0.0), (30, 1.0)])
    for points in (a, b):
        result = _svc()._downsample_for_visual(points, 4)
        assert min(p.value for p in result) == 0.0
        assert max(p.value for p in result) == 5.0
        ts = [p.timestamp for p in result]
        assert ts == sorted(ts)


def test_zero_duration_window():
    ts = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
    # Same timestamp = same event identity: must deduplicate to one point
    points = [
        TimeSeriesPoint(timestamp=ts, value=v, good=True, questionable=False, substituted=False)
        for v in (5.0, 0.0, 9.0, 2.0)
    ]
    result = _svc()._downsample_for_visual(points, 3)
    assert len(result) == 1
    assert result[0].timestamp == ts


def test_null_values_do_not_break_extremes():
    points = _pts([(0, None), (10, 4.0), (20, None), (30, 1.0)])
    result = _svc()._downsample_for_visual(points, 2)
    assert min(p.value for p in result if p.value is not None) == 1.0
    assert max(p.value for p in result if p.value is not None) == 4.0


def test_budget_respected():
    points = _pts([(i * 10, float(i)) for i in range(200)])
    result = _svc()._downsample_for_visual(points, 20)
    assert len(result) <= 20


def test_small_window_returns_all_points() -> None:
    points = _pts([(0, 1.0), (10, 2.0), (20, 3.0)])
    assert _svc()._downsample_for_visual(points, 2000) == points


def test_same_timestamp_events_deduplicated() -> None:
    points = _pts([(0, 4.0)] * 9)
    result = _svc()._downsample_for_visual(points, 4)
    assert len(result) == 1