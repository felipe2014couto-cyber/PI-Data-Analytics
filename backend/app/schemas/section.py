"""Section Pydantic schemas."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.section_analysis_tag import SectionAnalysisFilterType
from app.models.variable_type import VariableFilterDataType


def _normalize_code(value: str) -> str:
    return (value or "").strip().upper()


class SectionAnalysisTagItem(BaseModel):
    variable_type_id: int = Field(gt=0)
    pi_tag_id: int = Field(gt=0)
    filter_type: SectionAnalysisFilterType = SectionAnalysisFilterType.SELECTION


class SectionAnalysisTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variable_type_id: int
    variable_type_code: str
    variable_type_name: str
    filter_data_type: VariableFilterDataType
    pi_tag_id: int
    pi_tag_name: str
    filter_type: SectionAnalysisFilterType

    @classmethod
    def _from_orm(cls, data: object) -> dict:
        var_type = getattr(data, "variable_type", None)
        pi_tag = getattr(data, "pi_tag", None)
        filter_data_type = getattr(data, "filter_data_type", None) or (var_type.filter_data_type if var_type else VariableFilterDataType.REAL)
        raw_filter_type = getattr(data, "filter_type", None)
        if isinstance(raw_filter_type, SectionAnalysisFilterType):
            resolved_filter_type = raw_filter_type
        elif isinstance(raw_filter_type, str) and raw_filter_type in SectionAnalysisFilterType.__members__:
            resolved_filter_type = SectionAnalysisFilterType(raw_filter_type)
        else:
            resolved_filter_type = SectionAnalysisFilterType.SELECTION

        return {
            "id": getattr(data, "id", 0),
            "variable_type_id": getattr(data, "variable_type_id", 0),
            "variable_type_code": getattr(data, "variable_type_code", None) or (var_type.code if var_type else ""),
            "variable_type_name": getattr(data, "variable_type_name", None) or (var_type.name if var_type else ""),
            "filter_data_type": filter_data_type,
            "pi_tag_id": getattr(data, "pi_tag_id", 0),
            "pi_tag_name": getattr(data, "pi_tag_name", None) or (pi_tag.pi_tag_name if pi_tag else ""),
            "filter_type": resolved_filter_type,
        }

    from pydantic import model_validator

    @model_validator(mode="before")
    @classmethod
    def _validate_before(cls, data):
        if not isinstance(data, dict):
            return cls._from_orm(data)
        return data


class SectionBase(BaseModel):
    equipment_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    active: bool = True
    process_type: Optional[str] = Field(default=None, pattern=r"^(COM_FORNO|SEM_FORNO)$", max_length=32)
    group_code: Optional[str] = Field(default=None, pattern=r"^(BQ|BF)$", max_length=8)
    classification_tag_ids: Optional[List[int]] = None
    width_tag_id: Optional[int] = Field(default=None, gt=0)
    um_tag_id: Optional[int] = Field(default=None, gt=0)
    thickness_tag_id: Optional[int] = Field(default=None, gt=0)
    steel_type_tag_id: Optional[int] = Field(default=None, gt=0)
    analysis_tags: Optional[List[SectionAnalysisTagItem]] = None

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
    process_type: Optional[str] = Field(default=None, pattern=r"^(COM_FORNO|SEM_FORNO)$", max_length=32)
    group_code: Optional[str] = Field(default=None, pattern=r"^(BQ|BF)$", max_length=8)
    classification_tag_ids: List[int] = Field(default_factory=list)
    width_tag_id: Optional[int] = Field(default=None, gt=0)
    um_tag_id: Optional[int] = Field(default=None, gt=0)
    thickness_tag_id: Optional[int] = Field(default=None, gt=0)
    steel_type_tag_id: Optional[int] = Field(default=None, gt=0)
    analysis_tags: Optional[List[SectionAnalysisTagItem]] = None

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
    process_type: Optional[str] = None
    group_code: Optional[str] = None
    classification_tag_ids: List[int] = Field(default_factory=list)
    width_tag_id: Optional[int] = None
    um_tag_id: Optional[int] = None
    thickness_tag_id: Optional[int] = None
    steel_type_tag_id: Optional[int] = None
    analysis_tags: List[SectionAnalysisTagResponse] = Field(default_factory=list)
    created_at: datetime

    @field_validator("classification_tag_ids", mode="before")
    @classmethod
    def _extract_tag_ids(cls, value):
        if value is None:
            return []
        return [tag.id if hasattr(tag, "id") else tag for tag in value]
    updated_at: datetime
