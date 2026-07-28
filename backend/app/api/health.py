"""Health check router."""
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
def health_check() -> dict:
    return {
        "status": "ok",
        "application": settings.app_name,
    }
