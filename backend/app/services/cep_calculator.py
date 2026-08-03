"""Pure CEP calculator — no database, no PI Web API, no state.

Input types mirror the PiValue dataclass from the PI integration layer
but are defined here as plain dataclasses to keep the calculator independent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Input data structures
# ---------------------------------------------------------------------------

class PointQuality:
    """Quality flags for a single data point, matching PI semantics."""

    __slots__ = ("good", "questionable", "substituted")

    def __init__(
        self,
        good: bool = True,
        questionable: bool = False,
        substituted: bool = False,
    ) -> None:
        self.good = good
        self.questionable = questionable
        self.substituted = substituted

    def __repr__(self) -> str:
        return (
            f"PointQuality(good={self.good}, questionable={self.questionable}, "
            f"substituted={self.substituted})"
        )


@dataclass
class CepSample:
    """A single timestamped sample with value and quality."""
    timestamp: datetime
    value: Optional[float]
    quality: PointQuality = field(default_factory=PointQuality)


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

class CepStatus(str, Enum):
    CONFORME = "CONFORME"
    FORA_DO_LIMITE_INFERIOR = "FORA_DO_LIMITE_INFERIOR"
    FORA_DO_LIMITE_SUPERIOR = "FORA_DO_LIMITE_SUPERIOR"
    SEM_DADOS = "SEM_DADOS"


class ImputationMethod(str, Enum):
    NEIGHBOR_MEAN = "NEIGHBOR_MEAN"


@dataclass
class RecoveredValue:
    """Result of applying quality validation and imputation to a raw sample."""
    timestamp: datetime
    raw_value: Optional[float]
    effective_value: Optional[float]
    is_valid: bool
    source_substituted: bool  # original PI Substituted flag
    imputed: bool
    imputation_method: Optional[ImputationMethod] = None
    sem_dados_reason: Optional[str] = None


@dataclass
class CepCalculatedPoint:
    """A fully calculated compliance point."""
    timestamp: datetime
    status: CepStatus
    reading_effective: Optional[float]
    lower_effective: Optional[float]
    upper_effective: Optional[float]
    target_effective: Optional[float]
    reading_source_substituted: bool
    reading_imputed: bool
    lower_source_substituted: bool
    lower_imputed: bool
    upper_source_substituted: bool
    upper_imputed: bool
    target_source_substituted: bool
    target_imputed: bool
    sem_dados_reason: Optional[str] = None


@dataclass
class CepConformitySummary:
    """Aggregated conformity summary for a set of calculated points."""
    total_classifiable: int
    conformant: int
    non_conformant_below: int
    non_conformant_above: int
    no_data: int
    total_imputed: int
    conformity_pct: Optional[float]  # None if total_classifiable == 0


@dataclass
class OutOfLimitPeriod:
    """A contiguous period where the variable was outside limits."""
    start_time: datetime
    end_time: datetime
    status: CepStatus  # FORA_DO_LIMITE_INFERIOR or FORA_DO_LIMITE_SUPERIOR


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class CepInputError(ValueError):
    """Raised when input data violates CEP calculator constraints."""


def _check_timestamp_consistency(samples: List[CepSample], label: str) -> None:
    """Validate timestamps in a series: no duplicates, no mixed tz awareness."""
    if not samples:
        return

    has_tz = samples[0].timestamp.tzinfo is not None
    for s in samples:
        s_has_tz = s.timestamp.tzinfo is not None
        if s_has_tz != has_tz:
            raise CepInputError(
                f"Serie '{label}' mistura timestamps naive e timezone-aware."
            )

    seen: Set[datetime] = set()
    for s in samples:
        if s.timestamp in seen:
            raise CepInputError(
                f"Timestamp duplicado na serie '{label}': {s.timestamp.isoformat()}"
            )
        seen.add(s.timestamp)


def _check_cross_series_tz(
    reading: List[CepSample],
    lower: List[CepSample],
    upper: List[CepSample],
    target: Optional[List[CepSample]],
) -> None:
    """Ensure all non-empty series share the same tz-awareness category.

    Raises CepInputError if some series are naive and others are aware.
    """
    series_map = {
        "leitura": reading,
        "limite_inferior": lower,
        "limite_superior": upper,
    }
    if target:
        series_map["alvo"] = target

    first_tz: Optional[bool] = None
    first_label: Optional[str] = None
    for label, series in series_map.items():
        if not series:
            continue
        has_tz = series[0].timestamp.tzinfo is not None
        if first_tz is None:
            first_tz = has_tz
            first_label = label
        elif has_tz != first_tz:
            expected = "timezone-aware" if first_tz else "naive"
            got = "timezone-aware" if has_tz else "naive"
            raise CepInputError(
                f"Mistura de timestamps entre series: '{first_label}' "
                f"usa timestamps {expected}, mas '{label}' usa {got}."
            )


def _sort_samples(samples: List[CepSample]) -> List[CepSample]:
    """Return a new list sorted by timestamp (stable sort)."""
    return sorted(samples, key=lambda s: s.timestamp)


# ---------------------------------------------------------------------------
# Core validation helpers
# ---------------------------------------------------------------------------

def _is_numeric_finite(value: object) -> bool:
    """Return True if value is a finite number (int or float), not NaN, not inf."""
    if isinstance(value, bool):
        return False  # booleans are not considered numeric for CEP
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return False


def _is_bad_value(value: Optional[float], quality: PointQuality) -> Tuple[bool, Optional[str]]:
    """Determine if a point is unusable. Returns (is_bad, reason)."""
    if quality.good is False:
        return True, "Good=False"
    if quality.questionable is True:
        return True, "Questionable=True"
    if value is None:
        return True, "value is None"
    if not _is_numeric_finite(value):
        return True, "value is not numeric finite"
    if value == -999.0:
        return True, "value is -999"
    return False, None


# ---------------------------------------------------------------------------
# Imputation (neighbor mean)
# ---------------------------------------------------------------------------

def _apply_imputation(
    samples: List[CepSample],
) -> List[RecoveredValue]:
    """Validate each point and recover bad points using neighbor mean.

    Recovered points use original valid neighbors only.
    A recovered point cannot serve as neighbor for another recovery.
    """
    n = len(samples)
    results: List[Optional[RecoveredValue]] = [None] * n

    # First pass: validate each point
    raw_valid: List[bool] = [False] * n
    for i, s in enumerate(samples):
        is_bad, _reason = _is_bad_value(s.value, s.quality)
        raw_valid[i] = not is_bad

    # Second pass: impute bad points using original valid neighbors
    for i, s in enumerate(samples):
        is_bad, reason = _is_bad_value(s.value, s.quality)
        if not is_bad:
            results[i] = RecoveredValue(
                timestamp=s.timestamp,
                raw_value=s.value,
                effective_value=s.value,
                is_valid=True,
                source_substituted=s.quality.substituted,
                imputed=False,
            )
            continue

        # Find previous valid (original) point
        prev_idx: Optional[int] = None
        for j in range(i - 1, -1, -1):
            if raw_valid[j]:
                prev_idx = j
                break

        # Find next valid (original) point
        next_idx: Optional[int] = None
        for j in range(i + 1, n):
            if raw_valid[j]:
                next_idx = j
                break

        if prev_idx is not None and next_idx is not None:
            mean_val = (samples[prev_idx].value + samples[next_idx].value) / 2.0
            results[i] = RecoveredValue(
                timestamp=s.timestamp,
                raw_value=s.value,
                effective_value=mean_val,
                is_valid=True,
                source_substituted=s.quality.substituted,
                imputed=True,
                imputation_method=ImputationMethod.NEIGHBOR_MEAN,
            )
        else:
            results[i] = RecoveredValue(
                timestamp=s.timestamp,
                raw_value=s.value,
                effective_value=None,
                is_valid=False,
                source_substituted=s.quality.substituted,
                imputed=False,
                sem_dados_reason=reason or "no valid neighbors for imputation",
            )

    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Single-point classification
# ---------------------------------------------------------------------------

def classify_point(
    reading: Optional[float],
    lower: Optional[float],
    upper: Optional[float],
) -> CepStatus:
    """Classify a single point given effective values.

    Rules:
    - If lower > upper → SEM_DADOS
    - If lower <= reading <= upper → CONFORME
    - If reading < lower → FORA_DO_LIMITE_INFERIOR
    - If reading > upper → FORA_DO_LIMITE_SUPERIOR
    - If any value is None → SEM_DADOS
    """
    if reading is None or lower is None or upper is None:
        return CepStatus.SEM_DADOS
    if lower > upper:
        return CepStatus.SEM_DADOS
    if reading < lower:
        return CepStatus.FORA_DO_LIMITE_INFERIOR
    if reading > upper:
        return CepStatus.FORA_DO_LIMITE_SUPERIOR
    return CepStatus.CONFORME


# ---------------------------------------------------------------------------
# Main calculation entry point
# ---------------------------------------------------------------------------

def calculate_compliance(
    reading_samples: List[CepSample],
    lower_samples: List[CepSample],
    upper_samples: List[CepSample],
    target_samples: Optional[List[CepSample]] = None,
) -> Tuple[List[CepCalculatedPoint], CepConformitySummary]:
    """Calculate CEP compliance for aligned time series.

    Alignment strategy: the reading series is the main timeline.
    For each reading timestamp, find the EXACT same timestamp in lower,
    upper, and target series. No interpolation, no nearest-prior.

    Input rules:
    - All timestamps within a series must be unique.
    - All timestamps within a series must be consistently naive or aware.
    - Inputs are sorted internally before processing.
    - Extra timestamps in limit/target series that don't match reading
      are ignored (they don't create new CEP samples).
    """
    # --- Validate inputs ---
    _check_timestamp_consistency(reading_samples, "leitura")
    _check_timestamp_consistency(lower_samples, "limite_inferior")
    _check_timestamp_consistency(upper_samples, "limite_superior")
    if target_samples:
        _check_timestamp_consistency(target_samples, "alvo")

    # --- Cross-series timezone consistency ---
    _check_cross_series_tz(reading_samples, lower_samples, upper_samples, target_samples)

    # --- Sort inputs ---
    reading_sorted = _sort_samples(reading_samples)
    lower_sorted = _sort_samples(lower_samples)
    upper_sorted = _sort_samples(upper_samples)
    target_sorted = _sort_samples(target_samples) if target_samples else []

    # --- Validate and recover each series independently ---
    reading_recovered = _apply_imputation(reading_sorted)
    lower_recovered = _apply_imputation(lower_sorted)
    upper_recovered = _apply_imputation(upper_sorted)
    target_recovered = _apply_imputation(target_sorted) if target_sorted else []

    # --- Build timestamp → RecoveredValue maps ---
    reading_map: Dict[datetime, RecoveredValue] = {r.timestamp: r for r in reading_recovered}
    lower_map: Dict[datetime, RecoveredValue] = {r.timestamp: r for r in lower_recovered}
    upper_map: Dict[datetime, RecoveredValue] = {r.timestamp: r for r in upper_recovered}
    target_map: Dict[datetime, RecoveredValue] = {r.timestamp: r for r in target_recovered}

    # --- Calculate points using reading timestamps as reference ---
    points: List[CepCalculatedPoint] = []

    for r_sample in reading_sorted:
        ts = r_sample.timestamp
        r_rec = reading_map.get(ts)

        # Exact timestamp match for limits and target
        lo_rec = lower_map.get(ts)
        hi_rec = upper_map.get(ts)
        tgt_rec = target_map.get(ts) if target_map else None

        # Determine effective values
        r_eff = r_rec.effective_value if r_rec and r_rec.is_valid else None
        lo_eff = lo_rec.effective_value if lo_rec and lo_rec.is_valid else None
        hi_eff = hi_rec.effective_value if hi_rec and hi_rec.is_valid else None
        tgt_eff = tgt_rec.effective_value if tgt_rec and tgt_rec.is_valid else None

        # Classify
        status = classify_point(r_eff, lo_eff, hi_eff)

        # Determine SEM_DADOS reason
        sem_reason: Optional[str] = None
        if status == CepStatus.SEM_DADOS:
            if r_eff is None:
                if r_rec and not r_rec.is_valid:
                    sem_reason = r_rec.sem_dados_reason or "reading unavailable"
                else:
                    sem_reason = "reading unavailable"
            elif lo_eff is None:
                if lo_rec and not lo_rec.is_valid:
                    sem_reason = lo_rec.sem_dados_reason or "lower limit unavailable"
                else:
                    sem_reason = "lower limit unavailable"
            elif hi_eff is None:
                if hi_rec and not hi_rec.is_valid:
                    sem_reason = hi_rec.sem_dados_reason or "upper limit unavailable"
                else:
                    sem_reason = "upper limit unavailable"
            elif lo_eff > hi_eff:
                sem_reason = "lower limit > upper limit"

        point = CepCalculatedPoint(
            timestamp=ts,
            status=status,
            reading_effective=r_eff,
            lower_effective=lo_eff,
            upper_effective=hi_eff,
            target_effective=tgt_eff,
            reading_source_substituted=r_rec.source_substituted if r_rec else False,
            reading_imputed=r_rec.imputed if r_rec else False,
            lower_source_substituted=lo_rec.source_substituted if lo_rec else False,
            lower_imputed=lo_rec.imputed if lo_rec else False,
            upper_source_substituted=hi_rec.source_substituted if hi_rec else False,
            upper_imputed=hi_rec.imputed if hi_rec else False,
            target_source_substituted=tgt_rec.source_substituted if tgt_rec else False,
            target_imputed=tgt_rec.imputed if tgt_rec else False,
            sem_dados_reason=sem_reason,
        )
        points.append(point)

    # --- Summary ---
    classifiable = [p for p in points if p.status != CepStatus.SEM_DADOS]
    conformant = sum(1 for p in classifiable if p.status == CepStatus.CONFORME)
    below = sum(1 for p in classifiable if p.status == CepStatus.FORA_DO_LIMITE_INFERIOR)
    above = sum(1 for p in classifiable if p.status == CepStatus.FORA_DO_LIMITE_SUPERIOR)
    no_data = sum(1 for p in points if p.status == CepStatus.SEM_DADOS)
    imputed_count = sum(
        1 for p in points
        if p.reading_imputed or p.lower_imputed or p.upper_imputed
    )

    pct = (conformant / len(classifiable) * 100.0) if classifiable else None

    summary = CepConformitySummary(
        total_classifiable=len(classifiable),
        conformant=conformant,
        non_conformant_below=below,
        non_conformant_above=above,
        no_data=no_data,
        total_imputed=imputed_count,
        conformity_pct=pct,
    )

    return points, summary


# ---------------------------------------------------------------------------
# Out-of-limit period detection
# ---------------------------------------------------------------------------

def detect_out_of_limit_periods(
    points: List[CepCalculatedPoint],
) -> List[OutOfLimitPeriod]:
    """Group consecutive non-conforming points into periods.

    Rules:
    - A single out-of-limit sample forms a period.
    - SEM_DADOS breaks a period.
    - Change between BELOW and ABOVE starts a new period.
    - Compliant points close a period.
    - Periods are ordered chronologically.
    """
    if not points:
        return []

    periods: List[OutOfLimitPeriod] = []
    current_status: Optional[CepStatus] = None
    current_start: Optional[datetime] = None

    for i, p in enumerate(points):
        is_out = p.status in (CepStatus.FORA_DO_LIMITE_INFERIOR, CepStatus.FORA_DO_LIMITE_SUPERIOR)

        if is_out and p.status == current_status:
            # Continue current period
            continue

        if is_out and p.status != current_status:
            # Close previous period if any
            if current_status is not None and current_start is not None:
                end_ts = points[i - 1].timestamp
                periods.append(OutOfLimitPeriod(
                    start_time=current_start,
                    end_time=end_ts,
                    status=current_status,
                ))
            current_status = p.status
            current_start = p.timestamp

        if not is_out:
            # Close current period (conforme or sem_dados)
            if current_status is not None and current_start is not None:
                end_ts = points[i - 1].timestamp
                periods.append(OutOfLimitPeriod(
                    start_time=current_start,
                    end_time=end_ts,
                    status=current_status,
                ))
            current_status = None
            current_start = None

    # Close any open period at end
    if current_status is not None and current_start is not None and points:
        periods.append(OutOfLimitPeriod(
            start_time=current_start,
            end_time=points[-1].timestamp,
            status=current_status,
        ))

    return periods
