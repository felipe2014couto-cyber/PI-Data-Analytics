"""Shared schemas used across the API."""
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[object] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PageMeta(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    page: int
    page_size: int
    total: int
    pages: int
