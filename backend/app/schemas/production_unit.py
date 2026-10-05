from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductionUnitQualityFilter(BaseModel):
    exclude_bad: bool = Field(default=True, alias="excludeBad")
    exclude_questionable: bool = Field(default=False, alias="excludeQuestionable")
    exclude_substituted: bool = Field(default=False, alias="excludeSubstituted")

    model_config = ConfigDict(populate_by_name=True)


class ProductionUnitFilterRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: Literal["numeric", "text", "weekday", "timeRange", "excludeValue"]
    enabled: bool = True
    tag_id: int | None = Field(default=None, alias="tagId", gt=0)
    series_instance_id: str | None = Field(default=None, alias="seriesInstanceId")
    section_tag_map: dict[int, int] | None = Field(default=None, alias="sectionTagMap")
    operator: str | None = None
    value: Any | None = None
    second_value: float | None = Field(default=None, alias="secondValue")
    value_type: Literal["number", "string", "boolean"] | None = Field(default=None, alias="valueType")
    case_sensitive: bool = Field(default=False, alias="caseSensitive")
    days: list[Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]] | None = None
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")


class ProductionUnitVariable(BaseModel):
    tag_id: int
    tag_name: str
    display_name: str
    data_type: str
    unit: str | None = None
    sample_count: int
    raw_sample_count: int = 0
    filtered_sample_count: int = 0
    excluded_quality_count: int
    eligible_sample_count: int | None = None
    attended_sample_count: int | None = None
    attended_percent: float | None = None
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    first_value: str | None = None
    last_value: str | None = None


class ProductionUnitSegment(BaseModel):
    segment_id: str
    um_value: str | None
    status: Literal["ASSIGNED", "UNASSIGNED"]
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    start_reason: Literal["QUERY_START", "UM_TRANSITION", "STATE_RECOVERED", "UNKNOWN_STATE"]
    end_reason: Literal["NEXT_UM", "QUERY_END", "INVALID_UM_STATE"]
    state_source_timestamp: datetime | None = None
    variables: list[ProductionUnitVariable]


class ProductionUnitAnalysisResponse(BaseModel):
    section_id: int | None
    equipment_id: int
    um_tag_id: int
    um_tag_name: str
    start_time: datetime
    end_time: datetime
    segments: list[ProductionUnitSegment]
    strategy: str = "production_unit_recorded_runtime"
    precomputed_segments: int = 0
    runtime_segments: int = 0
    runtime_raw_sample_count: int = 0


class ProductionUnitFilterConfiguration(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    filters_enabled: bool = Field(default=False, alias="filtersEnabled")
    quality: ProductionUnitQualityFilter = Field(default_factory=ProductionUnitQualityFilter)
    rules: list[ProductionUnitFilterRule] = Field(default_factory=list, max_length=100)
