"""Health check routers backed only by local state."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.config import settings
from app.models.postgres import PiIngestionState
from app.schemas.pi import PiHealth

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
def health_check() -> dict:
    return {
        "status": "ok",
        "application": settings.app_name,
    }


@router.get("/ingestion/health", response_model=PiHealth, summary="Consultar estado persistido da ingestao")
def ingestion_health(db: Session = Depends(get_db_session)) -> PiHealth:
    """Expose worker freshness without making a read-path request to PI."""
    state = db.scalar(select(PiIngestionState).order_by(PiIngestionState.updated_at.desc()).limit(1))
    if state is None or state.last_success_at is None:
        return PiHealth(
            status="unavailable", data_server=settings.pi_data_server_name or None,
            message="O worker ainda nao registrou uma ingestao bem-sucedida.",
            error_code="INGESTION_STATE_UNAVAILABLE",
        )
    last_success = state.last_success_at
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    lag = max(0.0, (datetime.now(timezone.utc) - last_success).total_seconds())
    stale = lag > settings.ingestion_freshness_tolerance_seconds
    return PiHealth(
        status="unavailable" if stale else "connected",
        data_server=settings.pi_data_server_name or None,
        message=f"Ultima ingestao bem-sucedida ha {int(lag)} segundos.",
        error_code="STALE_INGESTION" if stale else None,
    )
