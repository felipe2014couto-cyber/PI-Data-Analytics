"""PI Web API integration schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------- health


class PiHealth(BaseModel):
    status: Literal["connected", "unavailable", "not_configured", "verifying"]
    base_url: Optional[str] = None
    data_server: Optional[str] = None
    response_time_ms: Optional[int] = None
    message: Optional[str] = None
    error_code: Optional[str] = None


# ---------------------------------------------------------------------- validation


class PiTagResolution(BaseModel):
    """Metadata returned by the PI when a tag is resolved."""

    web_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    engineering_unit: Optional[str] = None
    point_type: Optional[str] = None


class PiTagValidationResult(BaseModel):
    tag_id: int
    status: Literal["PENDING", "VALID", "INVALID", "ERROR"]
    web_id: Optional[str] = None
    message: Optional[str] = None
    validated_at: Optional[datetime] = None
    error_code: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PiTagValidationBatchRequest(BaseModel):
    tag_ids: Optional[List[int]] = Field(default=None, description="IDs das tags a validar. Se vazio, valida todas as tags ativas.")


class PiTagValidationBatchResponse(BaseModel):
    total: int
    valid: int
    invalid: int
    error: int
    results: List[PiTagValidationResult]


# ---------------------------------------------------------------------- time series


TimeSeriesMode = Literal["recorded", "interpolated"]
ComparisonType = Literal["periods", "equipments", "categories"]


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: Optional[float | int | str | bool] = None
    good: bool = True
    questionable: bool = False
    substituted: bool = False
    elapsed_ms: Optional[int] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("timestamp")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        from datetime import timezone

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TimeSeriesSeries(BaseModel):
    tag_id: int
    tag_name: str
    display_name: str
    equipment: Optional[str] = None
    section: Optional[str] = None
    variable_type: Optional[str] = None
    unit: Optional[str] = None
    points: List[TimeSeriesPoint]
    source_point_count: Optional[int] = None
    returned_point_count: Optional[int] = None
    sampled: Optional[bool] = None
    truncated: Optional[bool] = None
    chunk_count: Optional[int] = None
    context_id: Optional[Literal["A", "B"]] = None
    context_label: Optional[str] = None
    comparison_type: Optional[ComparisonType] = None
    series_instance_id: Optional[str] = None
    category: Optional[str] = None
    original_start_time: Optional[datetime] = None
    original_end_time: Optional[datetime] = None


class QueryExecutionMetadata(BaseModel):
    strategy: Optional[str] = None
    resolution_mode: str = "automatic"
    requested_target_points_per_tag: Optional[int] = None
    effective_target_points_per_tag: Optional[int] = None
    effective_interval: Optional[str] = None
    chunk_count: Optional[int] = None
    subdivided_chunk_count: Optional[int] = None
    pi_request_count: Optional[int] = None
    visual_total_points: Optional[int] = None
    sampled: bool = False
    partial: bool = False
    duration_ms: Optional[int] = None
    cache_hit: Optional[bool] = None
    cache_age_ms: Optional[int] = None
    webid_cache_hits: Optional[int] = None
    webid_cache_misses: Optional[int] = None
    streamset_used: Optional[bool] = None
    streamset_mode: Optional[str] = None
    batch_count: Optional[int] = None
    batch_size: Optional[int] = None
    individual_fallback_requests: Optional[int] = None
    retry_count: Optional[int] = None
    batch_used: Optional[bool] = None
    streamset_group_count: Optional[int] = None
    batch_subrequest_count: Optional[int] = None
    initial_window_count: Optional[int] = None
    window_split_count: Optional[int] = None
    pi_http_requests: Optional[int] = None
    pi_points_received: Optional[int] = None
    points_returned: Optional[int] = None
    rate_limit_count: Optional[int] = None
    complete: Optional[bool] = None
    truncated: Optional[bool] = None
    queue_wait_ms: Optional[float] = None
    resolve_ms: Optional[float] = None
    fetch_ms: Optional[float] = None
    processing_ms: Optional[float] = None
    total_ms: Optional[float] = None
    query_id: Optional[str] = None


class TimeSeriesRequest(BaseModel):
    tag_ids: List[int] = Field(..., min_length=1, max_length=100)
    start_time: datetime
    end_time: datetime
    mode: TimeSeriesMode = "recorded"
    interval: Optional[str] = Field(default=None, max_length=16)
    max_count: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    resolution_mode: Optional[str] = Field(default=None, pattern="^(automatic|manual)$")
    target_points_per_tag: Optional[int] = Field(default=None, ge=1000, le=50000)

    @field_validator("start_time", "end_time")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        from datetime import timezone

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("tag_ids")
    @classmethod
    def _validate_unique(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("tag_ids nao pode estar vazio.")
        return list(dict.fromkeys(value))


class TimeSeries(BaseModel):
    start_time: datetime
    end_time: datetime
    mode: TimeSeriesMode
    series: List[TimeSeriesSeries]
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    query_execution: Optional[QueryExecutionMetadata] = None


class ComparisonContextRequest(BaseModel):
    context_id: Literal["A", "B"]
    context_label: str = Field(min_length=1, max_length=80)
    tag_ids: List[int] = Field(min_length=1, max_length=100)
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _context_utc(cls, value: datetime) -> datetime:
        from datetime import timezone
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("tag_ids")
    @classmethod
    def _context_unique_tags(cls, value: List[int]) -> List[int]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _context_period(self) -> "ComparisonContextRequest":
        if self.start_time >= self.end_time:
            raise ValueError("O inicio do contexto deve ser anterior ao fim.")
        return self


class TimeSeriesComparisonRequest(BaseModel):
    comparison_type: ComparisonType
    contexts: List[ComparisonContextRequest] = Field(min_length=2, max_length=2)
    mode: TimeSeriesMode = "recorded"
    interval: Optional[str] = Field(default=None, max_length=16)
    max_count: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    resolution_mode: str = Field(default="automatic", pattern="^(automatic|manual)$")
    target_points_per_tag: Optional[int] = Field(default=10000, ge=1000, le=50000)
    query_id: Optional[str] = None

    @field_validator("contexts")
    @classmethod
    def _contexts_a_then_b(cls, value: List[ComparisonContextRequest]) -> List[ComparisonContextRequest]:
        if [context.context_id for context in value] != ["A", "B"]:
            raise ValueError("Os contextos devem estar na ordem A, B.")
        return value


class ComparisonContextResult(BaseModel):
    context_id: Literal["A", "B"]
    context_label: str
    start_time: datetime
    end_time: datetime
    time_series: Optional[TimeSeries] = None
    error: Optional[Dict[str, Any]] = None
    complete: bool = True


class ComparisonMetadata(BaseModel):
    comparison_enabled: bool = True
    comparison_type: ComparisonType
    context_count: int = 2
    series_instance_count: int = 0
    points_received_by_context: Dict[str, int] = Field(default_factory=dict)
    points_returned_by_context: Dict[str, int] = Field(default_factory=dict)
    duration_ms_by_context: Dict[str, int] = Field(default_factory=dict)
    strategy_by_context: Dict[str, Optional[str]] = Field(default_factory=dict)
    cache_hit_by_context: Dict[str, Optional[bool]] = Field(default_factory=dict)
    pi_requests_by_context: Dict[str, int] = Field(default_factory=dict)
    duration_ms: int = 0
    complete: bool = True
    partial: bool = False
    query_id: Optional[str] = None


class TimeSeriesComparison(BaseModel):
    comparison_enabled: bool = True
    comparison_type: ComparisonType
    contexts: List[ComparisonContextResult]
    metadata: ComparisonMetadata
