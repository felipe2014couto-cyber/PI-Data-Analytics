"""PiTag Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.pi_tag import PiTagDataType, PiTagValidationStatus


def _normalize_tag_name(value: str) -> str:
    return (value or "").strip()


class PiTagBase(BaseModel):
    equipment_id: int = Field(gt=0)
    # None means that the tag belongs to the whole equipment, not to a
    # specific section.
    section_id: Optional[int] = Field(default=None, gt=0)
    variable_type_id: int = Field(gt=0)
    pi_server: str = Field(min_length=1, max_length=128)
    pi_tag_name: str = Field(min_length=1, max_length=255)
    lower_limit_tag: Optional[str] = Field(default=None, max_length=255)
    upper_limit_tag: Optional[str] = Field(default=None, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    engineering_unit: Optional[str] = Field(default=None, max_length=32)
    data_type: PiTagDataType = PiTagDataType.NUMERIC
    active: bool = True

    @field_validator("pi_server")
    @classmethod
    def _validate_server(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("O PI Server nao pode ficar vazio.")
        return cleaned

    @field_validator("pi_tag_name")
    @classmethod
    def _validate_tag(cls, value: str) -> str:
        cleaned = _normalize_tag_name(value)
        if not cleaned:
            raise ValueError("O nome da tag no PI nao pode ficar vazio.")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def _validate_display(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("O nome amigavel nao pode ficar vazio.")
        return cleaned

    @field_validator("engineering_unit")
    @classmethod
    def _validate_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = (value or "").strip()
        return cleaned or None


class PiTagCreate(PiTagBase):
    pass


class PiTagUpdate(BaseModel):
    equipment_id: Optional[int] = Field(default=None, gt=0)
    section_id: Optional[int] = Field(default=None, gt=0)
    variable_type_id: Optional[int] = Field(default=None, gt=0)
    pi_server: Optional[str] = Field(default=None, min_length=1, max_length=128)
    pi_tag_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    lower_limit_tag: Optional[str] = Field(default=None, max_length=255)
    upper_limit_tag: Optional[str] = Field(default=None, max_length=255)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    engineering_unit: Optional[str] = Field(default=None, max_length=32)
    data_type: Optional[PiTagDataType] = None
    active: Optional[bool] = None

    @field_validator("pi_server")
    @classmethod
    def _validate_server(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("O PI Server nao pode ficar vazio.")
        return cleaned

    @field_validator("pi_tag_name")
    @classmethod
    def _validate_tag(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = _normalize_tag_name(value)
        if not cleaned:
            raise ValueError("O nome da tag no PI nao pode ficar vazio.")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def _validate_display(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("O nome amigavel nao pode ficar vazio.")
        return cleaned

    @field_validator("engineering_unit")
    @classmethod
    def _validate_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = (value or "").strip()
        return cleaned or None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = (value or "").strip()
        return cleaned or None


class PiTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    section_id: Optional[int] = None
    variable_type_id: int
    pi_server: str
    pi_tag_name: str
    lower_limit_tag: Optional[str] = None
    upper_limit_tag: Optional[str] = None
    pi_web_id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    engineering_unit: Optional[str] = None
    data_type: PiTagDataType
    active: bool
    validation_status: PiTagValidationStatus
    validation_message: Optional[str] = None
    validated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
