"""Adapter that converts PI Web API values to CEP samples.

This module bridges the PI integration layer (PiValue) and the pure
CEP calculator (CepSample). It is the only place where this conversion
happens — neither the provider nor the calculator know about each other.
"""
from __future__ import annotations

import math

from app.integrations.pi.provider import PiValue
from app.services.cep_calculator import CepSample, PointQuality


def _is_numeric_finite(value: object) -> bool:
    """Return True if value is a finite number (int or float), not NaN, not inf."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return False


def pi_value_to_cep_sample(pi_value: PiValue) -> CepSample:
    """Convert a PiValue to a CepSample.

    Conversion rules:
    - float finite  → CepSample(ts, float(v), Q)
    - int finite    → CepSample(ts, float(v), Q)
    - bool          → rejected (value=None)
    - None          → CepSample(ts, None, Q)
    - NaN, Inf      → CepSample(ts, None, Q)
    - -999.0        → CepSample(ts, -999.0, Q) — preserved
    - str           → CepSample(ts, None, Q)
    - dict          → CepSample(ts, None, Q)
    """
    raw_value = pi_value.value

    # Determine effective value
    if _is_numeric_finite(raw_value):
        effective_value: float | None = float(raw_value)  # type: ignore[arg-type]
    else:
        effective_value = None

    quality = PointQuality(
        good=pi_value.good,
        questionable=pi_value.questionable,
        substituted=pi_value.substituted,
    )

    return CepSample(
        timestamp=pi_value.timestamp,
        value=effective_value,
        quality=quality,
    )
