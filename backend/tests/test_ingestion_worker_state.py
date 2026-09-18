from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.workers.ingestion_worker import _live_window, _state_timestamps


def test_live_window_does_not_replay_historical_gap() -> None:
    now = datetime(2026, 9, 12, 22, 30, tzinfo=timezone.utc)
    old_watermark = datetime(2026, 6, 30, 12, 49, tzinfo=timezone.utc)
    window = timedelta(minutes=1)

    start, end = _live_window(now, old_watermark, window)

    assert start == now - window
    assert end == now


def test_live_window_overlaps_a_recent_watermark() -> None:
    now = datetime(2026, 9, 12, 22, 31, 0, 50_000, tzinfo=timezone.utc)
    previous_end = datetime(2026, 9, 12, 22, 30, tzinfo=timezone.utc)

    start, end = _live_window(now, previous_end, timedelta(minutes=1))

    assert start < previous_end
    # minute-aligned semi-open boundary: start of the current minute
    assert end == datetime(2026, 9, 12, 22, 31, tzinfo=timezone.utc)


def test_state_watermark_tracks_complete_window_not_last_event() -> None:
    end = datetime(2026, 9, 12, 22, 30, tzinfo=timezone.utc)
    event_ts = end - timedelta(seconds=27)

    watermark, last_source = _state_timestamps(
        [SimpleNamespace(timestamp=event_ts)],
        end,
        None,
    )

    assert watermark == end
    assert last_source == event_ts


def test_empty_window_advances_watermark_and_preserves_last_event() -> None:
    end = datetime(2026, 9, 12, 22, 30, tzinfo=timezone.utc)
    previous = datetime(2026, 6, 30, 12, 49, tzinfo=timezone.utc)

    watermark, last_source = _state_timestamps([], end, previous)

    assert watermark == end
    assert last_source == previous
