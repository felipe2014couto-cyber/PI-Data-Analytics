"""Tests for the pure CEP calculator — no database, no PI."""
from datetime import datetime, timezone, timedelta

import pytest

from app.services.cep_calculator import (
    CepCalculatedPoint,
    CepInputError,
    CepSample,
    CepStatus,
    CepConformitySummary,
    ImputationMethod,
    OutOfLimitPeriod,
    PointQuality,
    _apply_imputation,
    _check_cross_series_tz,
    _check_timestamp_consistency,
    _is_bad_value,
    _is_numeric_finite,
    _sort_samples,
    classify_point,
    calculate_compliance,
    detect_out_of_limit_periods,
)


def _ts(h: int, m: int = 0) -> datetime:
    return datetime(2026, 1, 1, h, m, tzinfo=timezone.utc)


def _ts_naive(h: int, m: int = 0) -> datetime:
    return datetime(2026, 1, 1, h, m)


def _good(v: float = 0.0) -> PointQuality:
    return PointQuality(good=True, questionable=False, substituted=False)


def _substituted(v: float = 0.0) -> PointQuality:
    return PointQuality(good=True, questionable=False, substituted=True)


def _bad_questionable() -> PointQuality:
    return PointQuality(good=True, questionable=True, substituted=False)


def _bad_good_false() -> PointQuality:
    return PointQuality(good=False, questionable=False, substituted=False)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestTimestampConsistency:
    def test_all_aware_ok(self):
        samples = [CepSample(_ts(10, i), float(i), _good(i)) for i in range(3)]
        _check_timestamp_consistency(samples, "test")  # no error

    def test_all_naive_ok(self):
        samples = [CepSample(_ts_naive(10, i), float(i), _good(i)) for i in range(3)]
        _check_timestamp_consistency(samples, "test")  # no error

    def test_mixed_naive_and_aware_raises(self):
        samples = [
            CepSample(_ts(10, 0), 1.0, _good(1)),
            CepSample(_ts_naive(10, 1), 2.0, _good(2)),
        ]
        with pytest.raises(CepInputError, match="mistura"):
            _check_timestamp_consistency(samples, "test")

    def test_duplicate_timestamp_raises(self):
        samples = [
            CepSample(_ts(10, 0), 1.0, _good(1)),
            CepSample(_ts(10, 0), 2.0, _good(2)),
        ]
        with pytest.raises(CepInputError, match="duplicado"):
            _check_timestamp_consistency(samples, "test")

    def test_empty_series_ok(self):
        _check_timestamp_consistency([], "test")  # no error

    def test_single_point_ok(self):
        _check_timestamp_consistency([CepSample(_ts(10), 1.0, _good(1))], "test")


# ---------------------------------------------------------------------------
# Cross-series timezone consistency
# ---------------------------------------------------------------------------

class TestCrossSeriesTimezone:
    """All non-empty series must share the same tz-awareness category."""

    def test_reading_aware_lower_naive_raises(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good())]
        lower = [CepSample(_ts_naive(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        with pytest.raises(CepInputError, match="Mistura de timestamps"):
            _check_cross_series_tz(reading, lower, upper, None)

    def test_reading_naive_upper_aware_raises(self):
        reading = [CepSample(_ts_naive(10, 0), 15.0, _good())]
        lower = [CepSample(_ts_naive(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        with pytest.raises(CepInputError, match="Mistura de timestamps"):
            _check_cross_series_tz(reading, lower, upper, None)

    def test_target_naive_other_aware_raises(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good())]
        lower = [CepSample(_ts(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        target = [CepSample(_ts_naive(10, 0), 17.0, _good())]
        with pytest.raises(CepInputError, match="Mistura de timestamps"):
            _check_cross_series_tz(reading, lower, upper, target)

    def test_all_aware_ok(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good())]
        lower = [CepSample(_ts(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        target = [CepSample(_ts(10, 0), 17.0, _good())]
        _check_cross_series_tz(reading, lower, upper, target)  # no error

    def test_all_naive_ok(self):
        reading = [CepSample(_ts_naive(10, 0), 15.0, _good())]
        lower = [CepSample(_ts_naive(10, 0), 10.0, _good())]
        upper = [CepSample(_ts_naive(10, 0), 20.0, _good())]
        target = [CepSample(_ts_naive(10, 0), 17.0, _good())]
        _check_cross_series_tz(reading, lower, upper, target)  # no error

    def test_empty_target_ignored(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good())]
        lower = [CepSample(_ts(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        _check_cross_series_tz(reading, lower, upper, None)  # no error

    def test_cross_series_error_via_calculate_compliance(self):
        """Cross-series mismatch propagates through calculate_compliance."""
        reading = [CepSample(_ts(10, 0), 15.0, _good())]
        lower = [CepSample(_ts_naive(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        with pytest.raises(CepInputError, match="Mistura de timestamps"):
            calculate_compliance(reading, lower, upper)

    def test_error_message_includes_both_labels(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good())]
        lower = [CepSample(_ts_naive(10, 0), 10.0, _good())]
        upper = [CepSample(_ts(10, 0), 20.0, _good())]
        with pytest.raises(CepInputError) as exc_info:
            _check_cross_series_tz(reading, lower, upper, None)
        msg = str(exc_info.value)
        assert "leitura" in msg
        assert "limite_inferior" in msg


class TestSortSamples:
    def test_sorts_by_timestamp(self):
        samples = [
            CepSample(_ts(10, 2), 3.0, _good(3)),
            CepSample(_ts(10, 0), 1.0, _good(1)),
            CepSample(_ts(10, 1), 2.0, _good(2)),
        ]
        result = _sort_samples(samples)
        assert [s.timestamp.minute for s in result] == [0, 1, 2]

    def test_stable_sort(self):
        s1 = CepSample(_ts(10, 0), 1.0, _good())
        s2 = CepSample(_ts(10, 0), 2.0, _good())
        # Same timestamp — sort is stable but duplicates would be caught by validation
        result = _sort_samples([s2, s1])
        assert result[0].value == 2.0  # original order preserved (stable sort)


# ---------------------------------------------------------------------------
# Quality validation
# ---------------------------------------------------------------------------

class TestIsNumericFinite:
    def test_int(self):
        assert _is_numeric_finite(42) is True

    def test_float(self):
        assert _is_numeric_finite(3.14) is True

    def test_zero(self):
        assert _is_numeric_finite(0) is True

    def test_negative(self):
        assert _is_numeric_finite(-100) is True

    def test_bool_rejected(self):
        assert _is_numeric_finite(True) is False
        assert _is_numeric_finite(False) is False

    def test_nan(self):
        assert _is_numeric_finite(float("nan")) is False

    def test_inf(self):
        assert _is_numeric_finite(float("inf")) is False
        assert _is_numeric_finite(float("-inf")) is False

    def test_string(self):
        assert _is_numeric_finite("42") is False

    def test_none(self):
        assert _is_numeric_finite(None) is False


class TestIsBadValue:
    def test_good_value(self):
        is_bad, reason = _is_bad_value(10.0, _good(10.0))
        assert is_bad is False
        assert reason is None

    def test_good_false(self):
        is_bad, reason = _is_bad_value(10.0, _bad_good_false())
        assert is_bad is True
        assert "Good=False" in reason

    def test_questionable(self):
        is_bad, reason = _is_bad_value(10.0, _bad_questionable())
        assert is_bad is True
        assert "Questionable" in reason

    def test_none_value(self):
        is_bad, reason = _is_bad_value(None, _good(0))
        assert is_bad is True
        assert "None" in reason

    def test_nan(self):
        is_bad, reason = _is_bad_value(float("nan"), _good(0))
        assert is_bad is True
        assert "finite" in reason

    def test_inf(self):
        is_bad, reason = _is_bad_value(float("inf"), _good(0))
        assert is_bad is True

    def test_minus_999(self):
        is_bad, reason = _is_bad_value(-999.0, _good(0))
        assert is_bad is True
        assert "-999" in reason

    def test_string_value(self):
        is_bad, reason = _is_bad_value("abc", _good(0))
        assert is_bad is True

    def test_substituted_still_valid(self):
        is_bad, _ = _is_bad_value(10.0, _substituted(10.0))
        assert is_bad is False


# ---------------------------------------------------------------------------
# Imputation
# ---------------------------------------------------------------------------

class TestImputation:
    def test_all_valid(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), 25.0, _good(25)),
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert len(result) == 3
        assert all(r.is_valid for r in result)
        assert all(not r.imputed for r in result)
        assert result[0].effective_value == 20.0
        assert result[1].effective_value == 25.0
        assert result[2].effective_value == 30.0

    def test_single_bad_between_valids(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), None, _bad_good_false()),
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert len(result) == 3
        assert result[1].imputed is True
        assert result[1].effective_value == 25.0
        assert result[1].imputation_method == ImputationMethod.NEIGHBOR_MEAN

    def test_multiple_bad_between_valids(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), None, _bad_good_false()),
            CepSample(_ts(10, 2), None, _bad_questionable()),
            CepSample(_ts(10, 3), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert len(result) == 4
        assert result[1].imputed is True
        assert result[1].effective_value == 25.0
        assert result[2].imputed is True
        assert result[2].effective_value == 25.0

    def test_bad_at_start_no_recovery(self):
        samples = [
            CepSample(_ts(10, 0), None, _bad_good_false()),
            CepSample(_ts(10, 1), 25.0, _good(25)),
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert result[0].is_valid is False
        assert result[0].effective_value is None

    def test_bad_at_end_no_recovery(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), 25.0, _good(25)),
            CepSample(_ts(10, 2), None, _bad_good_false()),
        ]
        result = _apply_imputation(samples)
        assert result[2].is_valid is False
        assert result[2].effective_value is None

    def test_all_bad_no_recovery(self):
        samples = [
            CepSample(_ts(10, 0), None, _bad_good_false()),
            CepSample(_ts(10, 1), None, _bad_questionable()),
        ]
        result = _apply_imputation(samples)
        assert all(not r.is_valid for r in result)

    def test_imputed_not_used_as_neighbor(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), None, _bad_good_false()),
            CepSample(_ts(10, 2), None, _bad_good_false()),
            CepSample(_ts(10, 3), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        # Both bad points use mean of original valid 20 and 30 = 25
        assert result[1].effective_value == 25.0
        assert result[2].effective_value == 25.0

    def test_substituted_flag_preserved(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _substituted(20)),
        ]
        result = _apply_imputation(samples)
        assert result[0].source_substituted is True
        assert result[0].is_valid is True

    def test_nan_treated_as_bad(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), float("nan"), _good(0)),
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert result[1].imputed is True
        assert result[1].effective_value == 25.0

    def test_minus_999_treated_as_bad(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), -999.0, _good(0)),
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert result[1].imputed is True
        assert result[1].effective_value == 25.0

    def test_text_value_treated_as_bad(self):
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), "abc", _good(0)),  # type: ignore[arg-type]
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        # "abc" is not numeric finite, so it's bad and gets imputed
        assert result[1].imputed is True
        assert result[1].effective_value == 25.0

    def test_source_substituted_and_imputed_independent(self):
        """Substituted flag and imputed flag are independent."""
        samples = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), 25.0, _substituted(25)),  # valid but substituted
            CepSample(_ts(10, 2), 30.0, _good(30)),
        ]
        result = _apply_imputation(samples)
        assert result[1].source_substituted is True
        assert result[1].imputed is False
        assert result[1].effective_value == 25.0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassifyPoint:
    def test_conforme(self):
        assert classify_point(15.0, 10.0, 20.0) == CepStatus.CONFORME

    def test_equal_lower(self):
        assert classify_point(10.0, 10.0, 20.0) == CepStatus.CONFORME

    def test_equal_upper(self):
        assert classify_point(20.0, 10.0, 20.0) == CepStatus.CONFORME

    def test_below_lower(self):
        assert classify_point(5.0, 10.0, 20.0) == CepStatus.FORA_DO_LIMITE_INFERIOR

    def test_above_upper(self):
        assert classify_point(25.0, 10.0, 20.0) == CepStatus.FORA_DO_LIMITE_SUPERIOR

    def test_lower_greater_than_upper(self):
        assert classify_point(15.0, 20.0, 10.0) == CepStatus.SEM_DADOS

    def test_none_reading(self):
        assert classify_point(None, 10.0, 20.0) == CepStatus.SEM_DADOS

    def test_none_lower(self):
        assert classify_point(15.0, None, 20.0) == CepStatus.SEM_DADOS

    def test_none_upper(self):
        assert classify_point(15.0, 10.0, None) == CepStatus.SEM_DADOS

    def test_all_none(self):
        assert classify_point(None, None, None) == CepStatus.SEM_DADOS

    def test_target_does_not_affect(self):
        # Target is informational only — classification is the same
        assert classify_point(15.0, 10.0, 20.0) == CepStatus.CONFORME

    def test_full_precision(self):
        assert classify_point(10.000000001, 10.0, 20.0) == CepStatus.CONFORME
        assert classify_point(9.999999999, 10.0, 20.0) == CepStatus.FORA_DO_LIMITE_INFERIOR


# ---------------------------------------------------------------------------
# Full compliance calculation
# ---------------------------------------------------------------------------

class TestCalculateCompliance:
    def test_all_conforme(self):
        reading = [CepSample(_ts(10, i), 15.0, _good(15)) for i in range(5)]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(5)]
        upper = [CepSample(_ts(10, i), 20.0, _good(20)) for i in range(5)]
        points, summary = calculate_compliance(reading, lower, upper)
        assert len(points) == 5
        assert all(p.status == CepStatus.CONFORME for p in points)
        assert summary.conformity_pct == 100.0
        assert summary.no_data == 0

    def test_some_non_conforme(self):
        reading = [
            CepSample(_ts(10, 0), 5.0, _good(5)),   # below
            CepSample(_ts(10, 1), 15.0, _good(15)),  # conforme
            CepSample(_ts(10, 2), 25.0, _good(25)),  # above
        ]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(3)]
        upper = [CepSample(_ts(10, i), 20.0, _good(20)) for i in range(3)]
        points, summary = calculate_compliance(reading, lower, upper)
        assert points[0].status == CepStatus.FORA_DO_LIMITE_INFERIOR
        assert points[1].status == CepStatus.CONFORME
        assert points[2].status == CepStatus.FORA_DO_LIMITE_SUPERIOR
        assert summary.conformity_pct == pytest.approx(100 / 3)

    def test_no_data_from_bad_reading(self):
        reading = [
            CepSample(_ts(10, 0), None, _bad_good_false()),
            CepSample(_ts(10, 1), 15.0, _good(15)),
        ]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(2)]
        upper = [CepSample(_ts(10, i), 20.0, _good(20)) for i in range(2)]
        points, summary = calculate_compliance(reading, lower, upper)
        assert points[0].status == CepStatus.SEM_DADOS
        assert points[1].status == CepStatus.CONFORME
        assert summary.no_data == 1
        assert summary.total_classifiable == 1
        assert summary.conformity_pct == 100.0

    def test_lower_greater_than_upper(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [CepSample(_ts(10, 0), 20.0, _good(20))]
        upper = [CepSample(_ts(10, 0), 10.0, _good(10))]
        points, summary = calculate_compliance(reading, lower, upper)
        assert points[0].status == CepStatus.SEM_DADOS
        assert "lower limit > upper limit" in points[0].sem_dados_reason

    def test_target_informational_only(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        target = [CepSample(_ts(10, 0), 17.0, _good(17))]
        points, _ = calculate_compliance(reading, lower, upper, target)
        assert points[0].status == CepStatus.CONFORME
        assert points[0].target_effective == 17.0

    def test_imputed_points_counted(self):
        reading = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), None, _bad_good_false()),
            CepSample(_ts(10, 2), 20.0, _good(20)),
        ]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(3)]
        upper = [CepSample(_ts(10, i), 30.0, _good(30)) for i in range(3)]
        points, summary = calculate_compliance(reading, lower, upper)
        assert points[1].reading_imputed is True
        assert summary.total_imputed >= 1

    def test_empty_series(self):
        points, summary = calculate_compliance([], [], [])
        assert points == []
        assert summary.conformity_pct is None
        assert summary.total_classifiable == 0

    def test_precision_preserved(self):
        reading = [CepSample(_ts(10, 0), 10.000000001, _good(10))]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        points, _ = calculate_compliance(reading, lower, upper)
        assert points[0].status == CepStatus.CONFORME
        assert points[0].reading_effective == pytest.approx(10.000000001)

    def test_exact_timestamp_matching(self):
        """Limit must have exact same timestamp as reading."""
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        points, _ = calculate_compliance(reading, lower, upper)
        assert points[0].lower_effective == 10.0
        assert points[0].upper_effective == 20.0

    def test_limit_timestamp_mismatch_gives_sem_dados(self):
        """Limit at different timestamp than reading → SEM_DADOS for that limit."""
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [CepSample(_ts(10, 1), 10.0, _good(10))]  # different timestamp
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        points, _ = calculate_compliance(reading, lower, upper)
        assert points[0].status == CepStatus.SEM_DADOS
        assert "lower limit unavailable" in points[0].sem_dados_reason

    def test_extra_limit_timestamps_ignored(self):
        """Extra timestamps in limits that don't match reading are ignored."""
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [
            CepSample(_ts(10, 0), 10.0, _good(10)),
            CepSample(_ts(10, 5), 10.0, _good(10)),  # extra, no matching reading
        ]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        points, _ = calculate_compliance(reading, lower, upper)
        assert len(points) == 1
        assert points[0].status == CepStatus.CONFORME

    def test_duplicate_timestamp_in_reading_raises(self):
        reading = [
            CepSample(_ts(10, 0), 15.0, _good(15)),
            CepSample(_ts(10, 0), 16.0, _good(16)),
        ]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        with pytest.raises(CepInputError, match="duplicado"):
            calculate_compliance(reading, lower, upper)

    def test_duplicate_timestamp_in_limit_raises(self):
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [
            CepSample(_ts(10, 0), 10.0, _good(10)),
            CepSample(_ts(10, 0), 11.0, _good(11)),
        ]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        with pytest.raises(CepInputError, match="duplicado"):
            calculate_compliance(reading, lower, upper)

    def test_mixed_naive_aware_in_reading_raises(self):
        reading = [
            CepSample(_ts(10, 0), 15.0, _good(15)),
            CepSample(_ts_naive(10, 1), 16.0, _good(16)),
        ]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(2)]
        upper = [CepSample(_ts(10, i), 20.0, _good(20)) for i in range(2)]
        with pytest.raises(CepInputError, match="mistura"):
            calculate_compliance(reading, lower, upper)

    def test_input_sorted_internally(self):
        """Out-of-order input is sorted before processing."""
        reading = [
            CepSample(_ts(10, 2), 15.0, _good(15)),
            CepSample(_ts(10, 0), 15.0, _good(15)),
            CepSample(_ts(10, 1), 15.0, _good(15)),
        ]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(3)]
        upper = [CepSample(_ts(10, i), 20.0, _good(20)) for i in range(3)]
        points, _ = calculate_compliance(reading, lower, upper)
        assert [p.timestamp.minute for p in points] == [0, 1, 2]

    def test_bad_target_does_not_affect_conformity(self):
        """Bad target produces SEM_DADOS reason but classification uses reading+limits."""
        reading = [CepSample(_ts(10, 0), 15.0, _good(15))]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        target = [CepSample(_ts(10, 0), None, _bad_good_false())]
        points, summary = calculate_compliance(reading, lower, upper, target)
        assert points[0].status == CepStatus.CONFORME
        assert points[0].target_effective is None
        assert summary.conformity_pct == 100.0

    def test_substituted_flag_on_each_series(self):
        """source_substituted is tracked independently per series."""
        reading = [CepSample(_ts(10, 0), 15.0, _substituted(15))]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        target = [CepSample(_ts(10, 0), 17.0, _substituted(17))]
        points, _ = calculate_compliance(reading, lower, upper, target)
        assert points[0].reading_source_substituted is True
        assert points[0].lower_source_substituted is False
        assert points[0].upper_source_substituted is False
        assert points[0].target_source_substituted is True

    def test_imputed_flag_on_each_series(self):
        """imputed is tracked independently per series."""
        reading = [
            CepSample(_ts(10, 0), 20.0, _good(20)),
            CepSample(_ts(10, 1), None, _bad_good_false()),
            CepSample(_ts(10, 2), 20.0, _good(20)),
        ]
        lower = [
            CepSample(_ts(10, 0), 10.0, _good(10)),
            CepSample(_ts(10, 1), None, _bad_good_false()),
            CepSample(_ts(10, 2), 10.0, _good(10)),
        ]
        upper = [CepSample(_ts(10, i), 30.0, _good(30)) for i in range(3)]
        points, _ = calculate_compliance(reading, lower, upper)
        assert points[1].reading_imputed is True
        assert points[1].lower_imputed is True
        assert points[1].upper_imputed is False

    def test_sem_dados_not_in_percentage(self):
        """SEM_DADOS excluded from denominator."""
        reading = [
            CepSample(_ts(10, 0), None, _bad_good_false()),
            CepSample(_ts(10, 1), 15.0, _good(15)),
            CepSample(_ts(10, 2), 25.0, _good(25)),
        ]
        lower = [CepSample(_ts(10, i), 10.0, _good(10)) for i in range(3)]
        upper = [CepSample(_ts(10, i), 20.0, _good(20)) for i in range(3)]
        _, summary = calculate_compliance(reading, lower, upper)
        assert summary.total_classifiable == 2
        assert summary.no_data == 1
        assert summary.conformity_pct == pytest.approx(50.0)

    def test_all_sem_dados_percentage_none(self):
        """When all points are SEM_DADOS, percentage is None."""
        reading = [CepSample(_ts(10, 0), None, _bad_good_false())]
        lower = [CepSample(_ts(10, 0), 10.0, _good(10))]
        upper = [CepSample(_ts(10, 0), 20.0, _good(20))]
        _, summary = calculate_compliance(reading, lower, upper)
        assert summary.conformity_pct is None


# ---------------------------------------------------------------------------
# Out-of-limit period detection
# ---------------------------------------------------------------------------

class TestDetectOutOfLimitPeriods:
    def test_no_out_of_limit(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert periods == []

    def test_single_below_period(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 2), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 3), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 1
        assert periods[0].status == CepStatus.FORA_DO_LIMITE_INFERIOR
        assert periods[0].start_time == _ts(10, 1)
        assert periods[0].end_time == _ts(10, 2)

    def test_sem_dados_breaks_period(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.SEM_DADOS, None, None, None, None,
                               False, False, False, False, False, False, False, False,
                               sem_dados_reason="test"),
            CepCalculatedPoint(_ts(10, 2), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 2

    def test_change_from_below_to_above(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.FORA_DO_LIMITE_SUPERIOR, 25, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 2
        assert periods[0].status == CepStatus.FORA_DO_LIMITE_INFERIOR
        assert periods[0].end_time == _ts(10, 0)
        assert periods[1].status == CepStatus.FORA_DO_LIMITE_SUPERIOR
        assert periods[1].start_time == _ts(10, 1)

    def test_single_point_period(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.FORA_DO_LIMITE_SUPERIOR, 25, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 2), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 1
        assert periods[0].start_time == _ts(10, 1)
        assert periods[0].end_time == _ts(10, 1)

    def test_empty_points(self):
        periods = detect_out_of_limit_periods([])
        assert periods == []

    def test_all_out_of_limit_same_status(self):
        points = [
            CepCalculatedPoint(_ts(10, i), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False)
            for i in range(5)
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 1
        assert periods[0].start_time == _ts(10, 0)
        assert periods[0].end_time == _ts(10, 4)

    def test_conforme_breaks_period(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 2), CepStatus.FORA_DO_LIMITE_SUPERIOR, 25, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 2
        assert periods[0].status == CepStatus.FORA_DO_LIMITE_INFERIOR
        assert periods[0].end_time == _ts(10, 0)
        assert periods[1].status == CepStatus.FORA_DO_LIMITE_SUPERIOR
        assert periods[1].start_time == _ts(10, 2)

    def test_periods_chronologically_ordered(self):
        points = [
            CepCalculatedPoint(_ts(10, 0), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 1), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 2), CepStatus.FORA_DO_LIMITE_SUPERIOR, 25, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 3), CepStatus.CONFORME, 15, 10, 20, None,
                               False, False, False, False, False, False, False, False),
            CepCalculatedPoint(_ts(10, 4), CepStatus.FORA_DO_LIMITE_INFERIOR, 5, 10, 20, None,
                               False, False, False, False, False, False, False, False),
        ]
        periods = detect_out_of_limit_periods(points)
        assert len(periods) == 3
        assert periods[0].start_time < periods[1].start_time < periods[2].start_time
