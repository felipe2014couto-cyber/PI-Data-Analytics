"""Section Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_code(value: str) -> str:
    return (value or "").strip().upper()


class SectionBase(BaseModel):
    equipment_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    active: bool = True
    width_tag_id: Optional[int] = Field(default=None, gt=0)
    um_tag_id: Optional[int] = Field(default=None, gt=0)
    thickness_tag_id: Optional[int] = Field(default=None, gt=0)

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

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = (value or "").strip()
        return cleaned or None


class SectionCreate(SectionBase):
    pass


class SectionUpdate(BaseModel):
    equipment_id: Optional[int] = Field(default=None, gt=0)
    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    active: Optional[bool] = None
    width_tag_id: Optional[int] = Field(default=None, gt=0)
    um_tag_id: Optional[int] = Field(default=None, gt=0)
    thickness_tag_id: Optional[int] = Field(default=None, gt=0)

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
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("O nome nao pode ficar vazio.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = (value or "").strip()
        return cleaned or None


class SectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    code: str
    name: str
    description: Optional[str] = None
    active: bool
    width_tag_id: Optional[int] = None
    um_tag_id: Optional[int] = None
    thickness_tag_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
