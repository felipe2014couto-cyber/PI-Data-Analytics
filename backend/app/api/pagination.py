"""Pagination utilities."""
import math
from typing import Sequence

from app.schemas.common import PaginatedResponse


def build_paginated_response(
    items: Sequence,
    page: int,
    page_size: int,
    total: int,
) -> dict:
    pages = math.ceil(total / page_size) if page_size > 0 else 0
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
    }
