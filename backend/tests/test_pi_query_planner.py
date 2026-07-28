"""Tests for the query planner (pure functions)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.core.exceptions import TimeRangeInvalidError
from app.services.pi_query_planner import (
    SUPPORTED_INTERVALS,
    QueryPlan,
    TimeChunk,
    build_plan_for_visual,
    compute_automatic_interval,
    compute_interpolated_chunks,
    estimate_interpolated_points,
    interval_to_seconds,
    seconds_to_interval,
    split_chunk,
    split_period_into_chunks,
    validate_period,
    validate_visual_budget,
)


def _utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


class TestValidatePeriod:
    def test_valid_period(self):
        validate_period(_utc(2026, 1, 1), _utc(2026, 7, 1))

    def test_inverted_period_raises(self):
        with pytest.raises(TimeRangeInvalidError):
            validate_period(_utc(2026, 7, 1), _utc(2026, 1, 1))

    def test_equal_timestamps_raises(self):
        t = _utc(2026, 6, 1)
        with pytest.raises(TimeRangeInvalidError):
            validate_period(t, t)

    def test_exceeds_max_period(self):
        far = _utc(2026, 1, 1) + timedelta(days=400)
        with pytest.raises(TimeRangeInvalidError):
            validate_period(_utc(2026, 1, 1), far)


class TestSplitPeriod:
    def test_six_months_into_seven_day_chunks(self):
        start = _utc(2026, 1, 1)
        end = _utc(2026, 7, 1)
        chunks = split_period_into_chunks(start, end, chunk_days=7)
        assert len(chunks) > 20
        assert chunks[0].start_time == start
        assert chunks[-1].end_time == end
        for c in chunks:
            assert c.depth == 0

    def test_each_chunk_is_within_bounds(self):
        start = _utc(2026, 1, 1)
        end = _utc(2026, 7, 1)
        chunks = split_period_into_chunks(start, end, chunk_days=7)
        for c in chunks:
            assert c.start_time >= start
            assert c.end_time <= end
            assert c.start_time < c.end_time

    def test_single_chunk_for_small_period(self):
        start = _utc(2026, 6, 1)
        end = _utc(2026, 6, 3)
        chunks = split_period_into_chunks(start, end, chunk_days=7)
        assert len(chunks) == 1


class TestAutomaticInterval:
    def test_six_months_with_10000_target(self):
        start = _utc(2026, 1, 1)
        end = _utc(2026, 7, 1)
        interval = compute_automatic_interval(start, end, 10000)
        assert interval == "30m"

    def test_one_day_with_1000_target(self):
        start = _utc(2026, 6, 1)
        end = _utc(2026, 6, 2)
        interval = compute_automatic_interval(start, end, 1000)
        assert interval == "5m"

    def test_small_period_falls_back_to_minimum(self):
        start = _utc(2026, 6, 1, 0, 0, 0)
        end = _utc(2026, 6, 1, 0, 1, 0)
        interval = compute_automatic_interval(start, end, 10000)
        assert interval == "1s"

    def test_large_period_uses_max_interval(self):
        start = _utc(2026, 1, 1)
        end = _utc(2027, 1, 1)
        interval = compute_automatic_interval(start, end, 10)
        assert interval == "1d"

    def test_interval_to_seconds_and_back(self):
        for i, iv in enumerate(SUPPORTED_INTERVALS):
            assert seconds_to_interval(interval_to_seconds(iv)) == iv


class TestInterpolatedChunks:
    def test_chunks_respect_max_points(self):
        start = _utc(2026, 1, 1)
        end = _utc(2026, 7, 1)
        chunks = compute_interpolated_chunks(start, end, "30m", chunk_days=7)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.start_time >= start
            assert c.end_time <= end

    def test_estimate_points(self):
        n = estimate_interpolated_points(_utc(2026, 1, 1), _utc(2026, 7, 1), "30m")
        assert n == 8689


class TestSplitChunk:
    def test_split_in_half(self):
        chunk = TimeChunk(start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 8), index=0, depth=0)
        left, right = split_chunk(chunk)
        assert left.depth == 1
        assert right.depth == 1
        assert left.start_time == chunk.start_time
        assert right.end_time == chunk.end_time
        assert abs((left.end_time - left.start_time).total_seconds() - (right.end_time - right.start_time).total_seconds()) < 1


class TestVisualBudget:
    def test_default_target(self):
        eff, total = validate_visual_budget(1, 10000)
        assert eff <= 50000
        assert total <= 200000

    def test_high_target_reduced(self):
        eff, total = validate_visual_budget(10, 100000)
        assert eff <= 20000

    def test_many_tags_reduces_per_tag(self):
        eff, _ = validate_visual_budget(50, 10000)
        assert eff <= 4000


class TestBuildPlan:
    def test_plan_for_interpolated_automatic(self):
        plan = build_plan_for_visual(
            tag_count=2,
            start_time=_utc(2026, 1, 1),
            end_time=_utc(2026, 7, 1),
            mode="interpolated",
            resolution_mode="automatic",
            interval=None,
            target_points_per_tag=10000,
        )
        assert plan.effective_interval is not None
        assert len(plan.chunks) > 0
        assert plan.resolution_mode == "automatic"

    def test_plan_for_recorded(self):
        plan = build_plan_for_visual(
            tag_count=1,
            start_time=_utc(2026, 1, 1),
            end_time=_utc(2026, 7, 1),
            mode="recorded",
            resolution_mode="manual",
            interval=None,
            target_points_per_tag=10000,
        )
        assert len(plan.chunks) > 0
        assert plan.resolution_mode == "manual"
