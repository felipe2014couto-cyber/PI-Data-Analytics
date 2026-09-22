"""Health check routers backed only by local state."""
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, require_admin
from app.core.config import settings
from app.models.postgres import PiBackfillJob, PiIngestionState
from app.models.user import User
from app.schemas.pi import PiHealth

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
def health_check() -> dict:
    return {
        "status": "ok",
        "application": settings.app_name,
    }


def _worker_state(status: Any, enabled: bool) -> str:
    if not enabled:
        return "disabled"
    if not status.alive:
        return "stopped"
    if status.consecutive_failures > 0:
        return "degraded"
    if status.leader:
        return "active"
    return "standby"


@router.get("/workers/health", summary="Liveness e readiness dos workers (publico/minimo)")
def workers_health() -> dict:
    """Minimal public liveness/readiness probe without internal details."""
    from app.workers.supervisor import ingestion_status, backfill_status

    ingestion_state = _worker_state(ingestion_status, settings.worker_ingestion_enabled)
    backfill_state = _worker_state(backfill_status, settings.worker_backfill_enabled)

    states = {ingestion_state, backfill_state}
    if "degraded" in states or "stopped" in states:
        # If at least one active/standby worker is healthy and the stopped one is disabled, not degraded
        active_present = any(s in ("active", "standby") for s in states)
        stopped_enabled = any(
            s == "stopped" for s in (ingestion_state, backfill_state)
        )
        if "degraded" in states or (stopped_enabled and not (states == {"stopped"})):
            overall = "degraded"
        elif states == {"stopped"}:
            overall = "stopped"
        else:
            overall = "healthy" if active_present else "stopped"
    elif states == {"disabled"}:
        overall = "disabled"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "ingestion": ingestion_state,
        "backfill": backfill_state,
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


@router.get("/workers/status", summary="Status detalhado dos workers integrados")
def workers_status(
    db: Session = Depends(get_db_session),
    user: User = Depends(require_admin),
) -> dict:
    """Expose comprehensive worker observability without credentials."""
    from app.workers.supervisor import ingestion_status, backfill_status

    now = datetime.now(timezone.utc)

    # Ingestion details from DB.
    ingestion_tags = db.scalar(
        select(func.count()).select_from(PiIngestionState).where(
            PiIngestionState.last_success_at.is_not(None),
        )
    ) or 0
    tags_in_backoff = db.scalar(
        select(func.count()).select_from(PiIngestionState).where(
            PiIngestionState.next_attempt_at.is_not(None),
            PiIngestionState.next_attempt_at > now,
        )
    ) or 0

    # Watermark per tag (most recent states).
    watermark_rows = db.execute(
        select(
            PiIngestionState.tag_id,
            PiIngestionState.watermark_ts,
            PiIngestionState.last_success_at,
            PiIngestionState.consecutive_failures,
            PiIngestionState.last_error_code,
        ).where(
            PiIngestionState.source_mode == "RECORDED",
        ).order_by(PiIngestionState.tag_id).limit(100)
    ).all()
    watermarks = []
    max_delay_minutes: float | None = None
    for row in watermark_rows:
        wm = row.watermark_ts
        delay = None
        if wm is not None:
            wm_utc = wm.replace(tzinfo=timezone.utc) if wm.tzinfo is None else wm.astimezone(timezone.utc)
            delay = round((now - wm_utc).total_seconds() / 60, 1)
            if max_delay_minutes is None or delay > max_delay_minutes:
                max_delay_minutes = delay
        watermarks.append({
            "tag_id": row.tag_id,
            "watermark_ts": wm.isoformat() if wm else None,
            "delay_minutes": delay,
            "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
            "consecutive_failures": row.consecutive_failures,
            "last_error_code": row.last_error_code,
        })

    # Backfill job summary.
    backfill_counts = {}
    rows = db.execute(
        select(PiBackfillJob.status, func.count()).group_by(PiBackfillJob.status)
    ).all()
    for status, cnt in rows:
        backfill_counts[status] = cnt

    running_jobs = db.execute(
        select(PiBackfillJob).where(PiBackfillJob.status == "RUNNING").limit(5)
    ).scalars().all()
    running_summaries = []
    for j in running_jobs:
        progress = None
        if j.checkpoint_start and j.target_start and j.target_end:
            total = (_as_utc(j.target_end) - _as_utc(j.target_start)).total_seconds()
            done = (_as_utc(j.checkpoint_start) - _as_utc(j.target_start)).total_seconds()
            progress = round(done / total * 100, 1) if total > 0 else 100.0
        running_summaries.append({
            "id": j.id,
            "tag_id": j.tag_id,
            "round_name": j.round_name,
            "checkpoint": j.checkpoint_start.isoformat() if j.checkpoint_start else None,
            "target_end": j.target_end.isoformat() if j.target_end else None,
            "progress_pct": progress,
            "lease_owner": j.lease_owner,
            "lease_expires_at": j.lease_expires_at.isoformat() if j.lease_expires_at else None,
            "heartbeat_at": j.heartbeat_at.isoformat() if j.heartbeat_at else None,
            "claims_count": j.attempts,
            "attempts": j.attempts,
            "consecutive_failures": j.consecutive_failures,
            "error_message": sanitize_error_message(j.error_message),
        })

    legacy_running = db.scalar(
        select(func.count()).select_from(PiBackfillJob).where(
            PiBackfillJob.status == "RUNNING",
            PiBackfillJob.lease_expires_at.is_(None),
        )
    ) or 0

    expired_leases = db.scalar(
        select(func.count()).select_from(PiBackfillJob).where(
            PiBackfillJob.status == "RUNNING",
            PiBackfillJob.lease_expires_at.is_not(None),
            PiBackfillJob.lease_expires_at < now,
        )
    ) or 0

    ingestion_data = ingestion_status.to_dict()
    ingestion_data["last_error"] = sanitize_error_message(ingestion_data.get("last_error"))

    backfill_data = backfill_status.to_dict()
    backfill_data["last_error"] = sanitize_error_message(backfill_data.get("last_error"))

    return {
        "ingestion": {
            **ingestion_data,
            "tags_processed": ingestion_tags,
            "tags_in_backoff": tags_in_backoff,
            "max_delay_minutes": max_delay_minutes,
            "watermarks": watermarks,
        },
        "backfill": {
            **backfill_data,
            "jobs_by_status": backfill_counts,
            "running_jobs": running_summaries,
            "legacy_running_without_lease": legacy_running,
            "expired_leases_pending_recovery": expired_leases,
        },
    }


def sanitize_error_message(msg: str | None) -> str | None:
    """Sanitize error messages to ensure no credentials, tokens, or URLs with auth are leaked."""
    if not msg:
        return None
    cleaned = str(msg)
    # URLs with embedded user/password, e.g. http://user:pass@host
    cleaned = re.sub(r"://[^/\s:@]+:[^/\s:@]+@", "://[REDACTED]@", cleaned)
    # password=xxx, secret=xxx, token=xxx, api_key=xxx
    cleaned = re.sub(r"(password|secret|token|api_key|authorization)\s*[:=]\s*[^\s,;'\"]+", r"\1=[REDACTED]", cleaned, flags=re.IGNORECASE)
    # Bearer tokens
    cleaned = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned[:200]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
