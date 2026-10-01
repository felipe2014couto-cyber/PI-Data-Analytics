"""Schemas for PI tag CSV import."""
from typing import Optional

from pydantic import BaseModel


class PiTagCsvRowError(BaseModel):
    row: int
    column: Optional[str] = None
    value: Optional[str] = None
    message: str


class PiTagCsvRowPreview(BaseModel):
    row: int
    values: dict[str, Optional[str]]
    valid: bool


class PiTagCsvValidationResponse(BaseModel):
    valid: bool
    total_rows: int
    valid_count: int
    invalid_count: int
    ignored_example_rows: int = 0
    detected_encoding: Optional[str] = None
    detected_delimiter: Optional[str] = None
    had_bom: Optional[bool] = None
    errors: list[PiTagCsvRowError]
    preview: list[PiTagCsvRowPreview]


class PiTagCsvImportResponse(BaseModel):
    imported_count: int
    message: str
