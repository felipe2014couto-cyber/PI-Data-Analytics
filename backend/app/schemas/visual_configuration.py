"""Contracts for versioned visual configurations."""
import json
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_DOCUMENT_BYTES = 100_000


class VisualDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    visual_rules: dict[str, Any]

    @field_validator("visual_rules")
    @classmethod
    def validate_rules(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not {"enabled", "selectedSeriesInstanceId", "bySeries"}.issubset(value):
            raise ValueError("Documento visual incompleto.")
        if not isinstance(value.get("enabled"), bool) or not isinstance(value.get("bySeries"), dict):
            raise ValueError("Estrutura visual invalida.")
        if len(json.dumps({"schema_version": 1, "visual_rules": value}, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES:
            raise ValueError("Documento visual excede o limite de 100000 bytes.")
        return value


class VisualConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    document: VisualDocument
    _trim_name = field_validator("name")(lambda value: value.strip() or (_ for _ in ()).throw(ValueError("Nome obrigatorio.")))


class VisualConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    document: VisualDocument


class VisualConfigurationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    _trim_name = field_validator("name")(lambda value: value.strip() or (_ for _ in ()).throw(ValueError("Nome obrigatorio.")))


class VisualConfigurationRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    version: int = Field(ge=1)


class VisualConfigurationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    current_version: int
    created_at: datetime
    updated_at: datetime
    document: VisualDocument | None = None


class VisualConfigurationVersionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    version: int
    document: VisualDocument
    operation: str
    created_at: datetime
