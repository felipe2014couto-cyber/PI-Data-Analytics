"""Tests for long-range query service."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.pi.provider import PiPoint, PiValue
from app.schemas.pi import TimeSeriesRequest
from app.services.pi_long_range_service import PiLongRangeService, _remove_boundary_duplicates, _sample_series
from app.services.pi_query_planner import (
    QueryPlan,
    build_plan_for_visual,
    split_period_into_chunks,
    validate_period,
)
from tests.pi_fakes import make_value


def _utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


class TestBoundaryDeduplication:
    def test_identical_adjacent_removed(self):
        v1 = make_value("2026-07-01T00:00:00Z", 10.0)
        v2 = make_value("2026-07-01T00:00:00Z", 10.0)
        result = _remove_boundary_duplicates([v1, v2])
        assert len(result) == 1

    def test_same_timestamp_different_value_preserved(self):
        v1 = make_value("2026-07-01T00:00:00Z", 10.0)
        v2 = make_value("2026-07-01T00:00:00Z", 20.0)
        result = _remove_boundary_duplicates([v1, v2])
        assert len(result) == 2

    def test_same_timestamp_different_quality_preserved(self):
        v1 = make_value("2026-07-01T00:00:00Z", 10.0, good=True)
        v2 = make_value("2026-07-01T00:00:00Z", 10.0, good=False)
        result = _remove_boundary_duplicates([v1, v2])
        assert len(result) == 2

    def test_ordering_is_stable(self):
        values = [
            make_value("2026-07-01T00:00:01Z", 3.0),
            make_value("2026-07-01T00:00:00Z", 1.0),
            make_value("2026-07-01T00:00:02Z", 2.0),
        ]
        values.sort(key=lambda v: v.timestamp)
        result = _remove_boundary_duplicates(values)
        assert len(result) == 3
        assert result[0].value == 1.0
        assert result[1].value == 3.0
        assert result[2].value == 2.0


class TestSampling:
    def test_below_target_returns_all(self):
        values = [make_value(f"2026-07-01T00:{m:02d}:00Z", float(m)) for m in range(10)]
        result = _sample_series(values, 100)
        assert len(result) == 10

    def test_first_and_last_preserved(self):
        values = [make_value(f"2026-07-01T00:{m % 60:02d}:{m // 60:02d}Z", float(m)) for m in range(100)]
        result = _sample_series(values, 10)
        assert result[0].value == values[0].value
        assert result[-1].value == values[-1].value

    def test_string_values_preserved(self):
        values = [
            make_value("2026-07-01T00:00:00Z", "600"),
            make_value("2026-07-01T00:01:00Z", "700"),
        ]
        result = _sample_series(values, 10)
        assert result[0].value == "600"
        assert isinstance(result[0].value, str)

    def test_boolean_preserved(self):
        values = [
            make_value("2026-07-01T00:00:00Z", True),
            make_value("2026-07-01T00:01:00Z", False),
        ]
        result = _sample_series(values, 10)
        assert result[0].value is True
        assert result[1].value is False

    def test_textual_compact_repeated(self):
        values = [
            make_value("2026-07-01T00:00:00Z", "RUN"),
            make_value("2026-07-01T00:01:00Z", "RUN"),
            make_value("2026-07-01T00:02:00Z", "STOP"),
            make_value("2026-07-01T00:03:00Z", "STOP"),
            make_value("2026-07-01T00:04:00Z", "RUN"),
        ]
        result = _sample_series(values, 10)
        assert len(result) <= 5

    def test_mixed_series_no_coercion(self):
        values = [
            make_value("2026-07-01T00:00:00Z", 100),
            make_value("2026-07-01T00:01:00Z", "TEXT"),
            make_value("2026-07-01T00:02:00Z", 200),
        ]
        result = _sample_series(values, 10)
        assert result[0].value == 100
        assert isinstance(result[0].value, int)
        assert result[1].value == "TEXT"
        assert isinstance(result[1].value, str)


class TestLongRangeService:
    def test_service_initialization(self, fake_provider):
        service = PiLongRangeService(db=None, provider=fake_provider)
        assert service is not None
