"""Administrative SIP historical reload API."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, status
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, require_admin
from app.core.exceptions import NotFoundError
from app.models import SipReloadJob
from app.services.sip_reload_service import enqueue

router = APIRouter(prefix="/admin/sip-reloads", tags=["sip-reloads"], dependencies=[Depends(require_admin)])


class SipReloadRequest(BaseModel):
    source_id: int
    start_time: datetime
    end_time: datetime


class SipReloadResponse(BaseModel):
    id: int
    source_id: int
    target_start: datetime
    target_end: datetime
    status: str
    progress_percent: float
    rows_written: int
    error_message: str | None
    model_config = ConfigDict(from_attributes=True)


@router.post("", response_model=SipReloadResponse, status_code=status.HTTP_201_CREATED)
def create(payload: SipReloadRequest, db: Session = Depends(get_db_session)):
    return enqueue(db, payload.source_id, payload.start_time, payload.end_time)


@router.get("", response_model=list[SipReloadResponse])
def list_jobs(db: Session = Depends(get_db_session)):
    return db.scalars(select(SipReloadJob).order_by(SipReloadJob.id.desc()).limit(500)).all()


@router.post("/{job_id}/cancel", response_model=SipReloadResponse)
def cancel(job_id: int, db: Session = Depends(get_db_session)):
    job = db.get(SipReloadJob, job_id)
    if job is None:
        raise NotFoundError("Recarga SIP não encontrada.")
    if job.status in ("PENDING", "RUNNING"):
        job.status = "CANCELLED"
        db.commit()
        db.refresh(job)
    return job


@router.delete("/terminal")
def clear_terminal(db: Session = Depends(get_db_session)):
    result = db.execute(delete(SipReloadJob).where(SipReloadJob.status.in_(("COMPLETED", "CANCELLED", "FAILED"))))
    db.commit()
    return {"deleted": result.rowcount}
