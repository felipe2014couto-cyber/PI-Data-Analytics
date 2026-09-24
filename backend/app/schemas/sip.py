"""Contracts for reusable SIP Oracle SELECT sources."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SipColumnsRequest(BaseModel):
    sql_text: str = Field(min_length=1, max_length=20000)


class SipColumnsResponse(BaseModel):
    columns: list[str]


class SipSourceCreate(BaseModel):
    equipment_id: int = Field(gt=0)
    section_id: Optional[int] = Field(default=None, gt=0)
    variable_type_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    sql_text: str = Field(min_length=1, max_length=20000)
    timestamp_column: str = Field(min_length=1, max_length=128)
    value_column: str = Field(min_length=1, max_length=128)
    active: bool = True


class SipSourceUpdate(BaseModel):
    equipment_id: Optional[int] = Field(default=None, gt=0)
    section_id: Optional[int] = Field(default=None, gt=0)
    variable_type_id: Optional[int] = Field(default=None, gt=0)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    sql_text: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    timestamp_column: Optional[str] = Field(default=None, min_length=1, max_length=128)
    value_column: Optional[str] = Field(default=None, min_length=1, max_length=128)
    active: Optional[bool] = None


class SipSourceResponse(SipSourceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class SipDatabaseTagCreate(BaseModel):
    equipment_id: int = Field(gt=0)
    section_id: Optional[int] = Field(default=None, gt=0)
    variable_type_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    sql_text: str = Field(min_length=1, max_length=20000)
    value_column: str = Field(min_length=1, max_length=128)
    active: bool = True


class SipDatabaseTagResponse(SipDatabaseTagCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
