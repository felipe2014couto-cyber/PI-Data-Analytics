from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ReloadMode = Literal["recorded", "interpolated"]


class HistoricalReloadRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    mode: ReloadMode = "recorded"
    interval: str | None = Field(default=None, pattern=r"^\d+[smhd]$", max_length=8)
    tag_id: int | None = Field(default=None, gt=0)
    variable_id: int | None = Field(default=None, gt=0)
    all_active: bool = False

    @field_validator("start_time", "end_time")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        from datetime import UTC
        if value.tzinfo is None:
            raise ValueError("A data deve possuir timezone explícito.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_request(self) -> "HistoricalReloadRequest":
        if self.start_time >= self.end_time:
            raise ValueError("O início deve ser anterior ao fim.")
        if self.mode == "interpolated" and not self.interval:
            raise ValueError("A resolução é obrigatória no modo interpolated.")
        if self.mode == "recorded" and self.interval:
            raise ValueError("Recorded não aceita resolução.")
        if sum(bool(value) for value in (self.tag_id, self.variable_id, self.all_active)) != 1:
            raise ValueError("Informe tag_id, variable_id ou all_active.")
        return self


class HistoricalReloadJobResponse(BaseModel):
    id: int
    tag_id: int
    mode: ReloadMode
    interval: str | None = None
    target_start: datetime
    target_end: datetime
    next_start: datetime | None = None
    status: str
    stage: str
    progress_percent: float = 0
    attempts: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class HistoricalReloadCoverageResponse(BaseModel):
    tag_id: int
    mode: str
    interval: str | None
    complete: bool
    covered: list[dict]
    missing: list[dict]


class HistoricalReloadSummaryResponse(BaseModel):
    total_active_tags: int
    tags_with_data: int
    tags_without_data: int
    partial_tags: int
    modes: list[dict]
