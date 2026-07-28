"""Schemas module."""
from app.schemas.common import ErrorBody, ErrorResponse, PageMeta, PaginatedResponse
from app.schemas.equipment import (
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
)
from app.schemas.section import (
    SectionCreate,
    SectionResponse,
    SectionUpdate,
)
from app.schemas.variable_type import (
    VariableTypeCreate,
    VariableTypeResponse,
    VariableTypeUpdate,
)
from app.schemas.pi_tag import (
    PiTagCreate,
    PiTagResponse,
    PiTagUpdate,
)
from app.schemas.pi import (
    PiHealth,
    PiTagResolution,
    PiTagValidationResult,
    PiTagValidationBatchRequest,
    PiTagValidationBatchResponse,
    TimeSeries,
    TimeSeriesPoint,
    TimeSeriesRequest,
    TimeSeriesSeries,
)

__all__ = [
    "ErrorBody",
    "ErrorResponse",
    "PageMeta",
    "PaginatedResponse",
    "EquipmentCreate",
    "EquipmentUpdate",
    "EquipmentResponse",
    "SectionCreate",
    "SectionUpdate",
    "SectionResponse",
    "VariableTypeCreate",
    "VariableTypeUpdate",
    "VariableTypeResponse",
    "PiTagCreate",
    "PiTagUpdate",
    "PiTagResponse",
    "PiHealth",
    "PiTagResolution",
    "PiTagValidationResult",
    "PiTagValidationBatchRequest",
    "PiTagValidationBatchResponse",
    "TimeSeries",
    "TimeSeriesPoint",
    "TimeSeriesRequest",
    "TimeSeriesSeries",
]
