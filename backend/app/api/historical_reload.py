from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, require_admin, validate_csrf
from app.schemas.historical_reload import (
    HistoricalReloadBatchCancelRequest,
    HistoricalReloadCoverageResponse,
    HistoricalReloadJobResponse,
    HistoricalReloadRequest,
    HistoricalReloadSummaryResponse,
)
from app.services.historical_reload_service import HistoricalReloadService, _interval_label

router = APIRouter(
    prefix="/admin/historical-reloads",
    tags=["historical-reloads"],
    dependencies=[Depends(require_admin), Depends(validate_csrf)],
)


def _job_response(job) -> HistoricalReloadJobResponse:
    if job.status == "COMPLETED":
        progress = 100.0
    else:
        elapsed = 0 if not job.next_start else (job.next_start - job.target_start).total_seconds()
        duration = max(1, (job.target_end - job.target_start).total_seconds())
        progress = min(100.0, max(0.0, elapsed / duration * 100))
    return HistoricalReloadJobResponse(
        id=job.id, tag_id=job.tag_id,
        mode="interpolated" if job.mode.startswith("INTERPOLATED") else "recorded",
        interval=_interval_label(job.interval_seconds), target_start=job.target_start,
        target_end=job.target_end, next_start=job.next_start, status=job.status,
        stage=job.stage, progress_percent=progress,
        attempts=job.attempts or 0, error_message=job.error_message,
        lease_owner=job.lease_owner, lease_expires_at=job.lease_expires_at,
        heartbeat_at=job.heartbeat_at, next_attempt_at=job.next_attempt_at,
        created_at=job.created_at, updated_at=job.updated_at,
    )


@router.post("", response_model=list[HistoricalReloadJobResponse], status_code=status.HTTP_202_ACCEPTED)
def create_reload(payload: HistoricalReloadRequest, db: Session = Depends(get_db_session)):
    return [_job_response(job) for job in HistoricalReloadService(db).create(payload)]


@router.get("", response_model=list[HistoricalReloadJobResponse])
def list_reloads(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db_session)):
    return [_job_response(job) for job in HistoricalReloadService(db).list(limit)]


@router.get("/summary", response_model=HistoricalReloadSummaryResponse)
def reload_summary(db: Session = Depends(get_db_session)):
    return HistoricalReloadService(db).summary()


@router.delete("/terminal", status_code=status.HTTP_200_OK)
def clear_terminal_reloads(db: Session = Depends(get_db_session)):
    """Clear only COMPLETED/CANCELLED job rows, never samples or coverage."""
    return {"deleted": HistoricalReloadService(db).clear_terminal()}


@router.post("/cancel-batch", response_model=list[HistoricalReloadJobResponse])
def cancel_batch(payload: HistoricalReloadBatchCancelRequest, db: Session = Depends(get_db_session)):
    return [_job_response(job) for job in HistoricalReloadService(db).cancel_many(payload.job_ids)]


@router.get("/coverage/{tag_id}", response_model=HistoricalReloadCoverageResponse)
def reload_coverage(
    tag_id: int,
    start_time: datetime,
    end_time: datetime,
    mode: str = "recorded",
    interval: str | None = None,
    db: Session = Depends(get_db_session),
):
    return HistoricalReloadService(db).coverage(tag_id, start_time, end_time, mode, interval)


@router.get("/{job_id}", response_model=HistoricalReloadJobResponse)
def reload_status(job_id: int, db: Session = Depends(get_db_session)):
    return _job_response(HistoricalReloadService(db).get(job_id))


@router.post("/{job_id}/cancel", response_model=HistoricalReloadJobResponse)
def cancel_reload(job_id: int, db: Session = Depends(get_db_session)):
    return _job_response(HistoricalReloadService(db).cancel(job_id))
