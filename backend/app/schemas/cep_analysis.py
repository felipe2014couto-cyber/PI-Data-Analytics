"""Pydantic schemas for the CEP analysis endpoints.

These schemas define the public contract of the CEP analysis API.
They are used for request validation, response serialization, and
OpenAPI documentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class CepAnalysisRequest(BaseModel):
    """Request body for POST /api/cep/analyze."""

    start_time: datetime
    end_time: datetime
    equipment_id: int | None = None
    section_id: int | None = None
    variable_ids: list[int] | None = None
    include_recorded: bool = False
    interpolated_interval: Literal["1m", "2m", "5m", "10m", "15m", "30m", "1h"] = "5m"

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_time": "2026-01-01T00:00:00Z",
                    "end_time": "2026-01-02T00:00:00Z",
                    "include_recorded": False,
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


class CepAnalysisAccepted(BaseModel):
    """Response returned by POST /api/cep/analyze (HTTP 202)."""

    query_id: str
    query_status: Literal["pending"]
    message: str
    progress_percent: int = 0
    completed_variables: int = 0
    total_variables: int = 0


# ---------------------------------------------------------------------------
# Status / tracking
# ---------------------------------------------------------------------------


class CepQueryPending(BaseModel):
    """Status returned while the analysis is pending."""

    query_id: str
    query_status: Literal["pending"]
    progress_percent: int = 0
    completed_variables: int = 0
    total_variables: int = 0


class CepQueryRunning(BaseModel):
    """Status returned while the analysis is running."""

    query_id: str
    query_status: Literal["running"]
    started_at: datetime
    progress_percent: int = 0
    completed_variables: int = 0
    total_variables: int = 0


class CepQueryCancelled(BaseModel):
    """Status returned when the analysis was cancelled."""

    query_id: str
    query_status: Literal["cancelled"]
    message: str
    progress_percent: int = 0
    completed_variables: int = 0
    total_variables: int = 0


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


class CepAnalysisSummary(BaseModel):
    """Aggregated summary of the CEP analysis."""

    analysis_status: Literal["completed", "partial", "failed"]
    overall_pct: float | None = None
    total_variables: int
    conformant_variables: int = 0
    non_conformant_variables: int = 0
    no_data_variables: int = 0
    failed_variables: int = 0
    period_start: datetime
    period_end: datetime


class CepVariableResult(BaseModel):
    """Result for a single CEP variable."""

    variable_id: int
    code: str
    name: str
    equipment_id: int
    section_id: int
    variable_type_id: int
    conformity_pct: float | None = None
    total_points: int = 0
    conformant: int = 0
    non_conformant: int = 0
    no_data: int = 0
    status: Literal["processed", "no_data", "error"]


class CepDiagnostic(BaseModel):
    """Diagnostic entry for a failed tag or limit issue."""

    tag_id: int
    tag_name: str
    variable_ids: list[int]
    error_code: str
    message: str


class CepRecordedPoint(BaseModel):
    """A single recorded data point."""

    timestamp: datetime
    value: float | None = None
    good: bool = True
    questionable: bool = False
    substituted: bool = False


class CepRecordedSeries(BaseModel):
    """Recorded time series for a single tag."""

    tag_id: int
    tag_name: str
    variable_ids: list[int]
    points: list[CepRecordedPoint]
    truncated: bool = False
    source_point_count: int | None = None


class CepAnalysisMetadata(BaseModel):
    """Execution metadata for the analysis."""

    pi_request_count: int | None = None
    pi_points_received: int | None = None
    points_returned: int | None = None
    webid_cache_hits: int | None = None
    webid_cache_misses: int | None = None
    duration_ms: int | None = None
    tags_processed: int | None = None
    tags_failed: int | None = None
    webid_resolved: int | None = None
    recorded_total_point_limit: int = 0
    recorded_returned_point_count: int = 0
    recorded_total_limit_reached: bool = False
    recorded_tags_not_acquired: list[str] = Field(default_factory=list)


class CepAnalysisResult(BaseModel):
    """Full result of a completed or failed CEP analysis."""

    query_id: str
    query_status: Literal["completed", "failed"]
    summary: CepAnalysisSummary
    variables: list[CepVariableResult]
    diagnostics: list[CepDiagnostic] = Field(default_factory=list)
    recorded_series: list[CepRecordedSeries] | None = None
    metadata: CepAnalysisMetadata
    progress_percent: int = 0
    completed_variables: int = 0
    total_variables: int = 0


class CepVariableSeriesPoint(BaseModel):
    """Interpolated point retained from one CEP execution."""

    timestamp: datetime
    value: float | None = None
    lower_limit: float | None = None
    upper_limit: float | None = None


class CepNonConformingPoint(BaseModel):
    """A point classified outside the limits by the CEP calculation."""

    timestamp: datetime
    value: float
    lower_limit: float | None = None
    upper_limit: float | None = None


class CepVariableSeries(BaseModel):
    """Chart data for a variable, sourced from the completed CEP execution."""

    variable_id: int
    variable_name: str
    analysis_tag: str
    lower_limit: float | None = None
    upper_limit: float | None = None
    points: list[CepVariableSeriesPoint] = Field(default_factory=list)
    non_conforming_points: list[CepNonConformingPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Union type for GET response
# ---------------------------------------------------------------------------

CepQueryResponse = Union[
    CepQueryPending,
    CepQueryRunning,
    CepQueryCancelled,
    CepAnalysisResult,
]


# ---------------------------------------------------------------------------
# Materialized dataclasses (used by the service, not exposed in API)
# ---------------------------------------------------------------------------


@dataclass
class MaterializedVariable:
    """CepVariable detached from ORM session."""

    id: int
    code: str
    name: str
    equipment_id: int
    section_id: int
    variable_type_id: int
    reading_tag_id: int
    lower_limit_tag_id: int
    upper_limit_tag_id: int
    target_tag_id: int | None = None


@dataclass
class MaterializedTag:
    """PiTag detached from ORM session."""

    id: int
    pi_tag_name: str
    pi_server: str
    pi_web_id: str | None = None


@dataclass
class MaterializedAnalysisData:
    """All data needed for analysis, independent of ORM session."""

    request: CepAnalysisRequest
    variables: list[MaterializedVariable]
    tag_variable_map: dict[int, list[int]]
    unique_tags: list[MaterializedTag]
