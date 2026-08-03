"""CepVariable Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_code(value: str) -> str:
    if value is None:
        return value
    return value.strip().upper()


class CepVariableBase(BaseModel):
    equipment_id: int = Field(gt=0)
    section_id: int = Field(gt=0)
    variable_type_id: int = Field(gt=0)
    reading_tag_id: int = Field(gt=0)
    lower_limit_tag_id: int = Field(gt=0)
    upper_limit_tag_id: int = Field(gt=0)
    target_tag_id: Optional[int] = Field(default=None, gt=0)
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    active: bool = True

    @field_validator("code")
    @classmethod
    def _normalize_code_field(cls, value: str) -> str:
        normalized = _normalize_code(value)
        if not normalized:
            raise ValueError("O codigo nao pode ficar vazio.")
        return normalized

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("O nome nao pode ficar vazio.")
        return cleaned


class CepVariableCreate(CepVariableBase):
    pass


class CepVariableUpdate(BaseModel):
    equipment_id: Optional[int] = Field(default=None, gt=0)
    section_id: Optional[int] = Field(default=None, gt=0)
    variable_type_id: Optional[int] = Field(default=None, gt=0)
    reading_tag_id: Optional[int] = Field(default=None, gt=0)
    lower_limit_tag_id: Optional[int] = Field(default=None, gt=0)
    upper_limit_tag_id: Optional[int] = Field(default=None, gt=0)
    target_tag_id: Optional[int] = Field(default=None)
    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    active: Optional[bool] = None

    @field_validator("code")
    @classmethod
    def _normalize_code_field(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = _normalize_code(value)
        if not normalized:
            raise ValueError("O codigo nao pode ficar vazio.")
        return normalized

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("O nome nao pode ficar vazio.")
        return cleaned


class CepVariableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    section_id: int
    variable_type_id: int
    reading_tag_id: int
    lower_limit_tag_id: int
    upper_limit_tag_id: int
    target_tag_id: Optional[int] = None
    code: str
    name: str
    active: bool
    created_at: datetime
    updated_at: datetime
