"""Classification tag Pydantic schemas."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClassificationTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _normalize(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("O nome da tag de classificacao nao pode ser vazio.")
        return normalized


class ClassificationTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    updated_at: datetime


class SectionClassificationTagsUpdate(BaseModel):
    """Explicit association payload: replaces the section's tags with this list."""
    tag_ids: List[int] = Field(default_factory=list)