"""Tests for CepPiAdapter — PiValue to CepSample conversion."""
from __future__ import annotations

from datetime import UTC, datetime

from app.integrations.pi.provider import PiValue
from app.services.cep_pi_adapter import pi_value_to_cep_sample


def _ts() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class TestPiValueToCepSample:
    """Test conversion rules from PiValue to CepSample."""

    def test_float_finite(self):
        pv = PiValue(timestamp=_ts(), value=42.5)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value == 42.5
        assert cs.timestamp == _ts()

    def test_int_finite(self):
        pv = PiValue(timestamp=_ts(), value=42)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value == 42.0
        assert isinstance(cs.value, float)

    def test_bool_rejected(self):
        pv = PiValue(timestamp=_ts(), value=True)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_none_value(self):
        pv = PiValue(timestamp=_ts(), value=None)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_nan_value(self):
        pv = PiValue(timestamp=_ts(), value=float("nan"))
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_inf_value(self):
        pv = PiValue(timestamp=_ts(), value=float("inf"))
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_negative_inf_value(self):
        pv = PiValue(timestamp=_ts(), value=float("-inf"))
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_preserved_negative_999(self):
        pv = PiValue(timestamp=_ts(), value=-999.0)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value == -999.0

    def test_string_value(self):
        pv = PiValue(timestamp=_ts(), value="ABC")
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_dict_value(self):
        pv = PiValue(timestamp=_ts(), value={"Name": "Shutdown"})
        cs = pi_value_to_cep_sample(pv)
        assert cs.value is None

    def test_quality_flags_preserved(self):
        pv = PiValue(
            timestamp=_ts(),
            value=1.0,
            good=False,
            questionable=True,
            substituted=True,
        )
        cs = pi_value_to_cep_sample(pv)
        assert cs.quality.good is False
        assert cs.quality.questionable is True
        assert cs.quality.substituted is True

    def test_quality_flags_default(self):
        pv = PiValue(timestamp=_ts(), value=1.0)
        cs = pi_value_to_cep_sample(pv)
        assert cs.quality.good is True
        assert cs.quality.questionable is False
        assert cs.quality.substituted is False

    def test_deterministic(self):
        pv = PiValue(timestamp=_ts(), value=3.14)
        cs1 = pi_value_to_cep_sample(pv)
        cs2 = pi_value_to_cep_sample(pv)
        assert cs1.value == cs2.value
        assert cs1.timestamp == cs2.timestamp
        assert cs1.quality.good == cs2.quality.good

    def test_zero_value(self):
        pv = PiValue(timestamp=_ts(), value=0.0)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value == 0.0

    def test_very_large_value(self):
        pv = PiValue(timestamp=_ts(), value=1e308)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value == 1e308

    def test_very_small_value(self):
        pv = PiValue(timestamp=_ts(), value=1e-308)
        cs = pi_value_to_cep_sample(pv)
        assert cs.value == 1e-308
