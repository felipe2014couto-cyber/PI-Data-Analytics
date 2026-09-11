from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.cep_variable import CepVariable
from app.models.pi_tag import PiTag
from app.models.postgres import PiBackfillJob, PiIngestionCoverage
from app.models.cep_variable_tag_dependency import CepVariableTagDependency
from app.schemas.historical_reload import HistoricalReloadRequest
from app.services.coverage_service import CoverageService, normalize_mode


def _one_year_later(value: datetime) -> datetime:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def _interval_seconds(interval: str | None) -> int | None:
    if not interval:
        return None
    return int(interval[:-1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[interval[-1]]


def _interval_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    for unit, size in (("h", 3600), ("m", 60), ("s", 1)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


class HistoricalReloadService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def validate_period(start: datetime, end: datetime) -> None:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValidationError("As datas devem possuir timezone explícito.")
        if start >= end:
            raise ValidationError("O início deve ser anterior ao fim.")
        if end > _one_year_later(start):
            raise ValidationError(
                "A recarga não pode exceder um ano civil.",
                details={"max_end": _one_year_later(start).isoformat()},
            )

    def _tags(self, payload: HistoricalReloadRequest) -> list[PiTag]:
        if payload.tag_id:
            tag = self.db.get(PiTag, payload.tag_id)
            if tag is None or not tag.active:
                raise NotFoundError("Tag ativa não encontrada.", details={"tag_id": payload.tag_id})
            return [tag]
        if payload.variable_id:
            variable = self.db.get(CepVariable, payload.variable_id)
            if variable is None or not variable.active:
                raise NotFoundError("Variável CEP ativa não encontrada.", details={"variable_id": payload.variable_id})
            ids = {variable.reading_tag_id, variable.lower_limit_tag_id, variable.upper_limit_tag_id, variable.target_tag_id}
            ids.update(self.db.scalars(select(CepVariableTagDependency.tag_id).where(
                CepVariableTagDependency.variable_id == variable.id,
                CepVariableTagDependency.status == "RESOLVED",
                CepVariableTagDependency.tag_id.is_not(None),
            )).all())
            tags = [tag for tag in self.db.scalars(select(PiTag).where(PiTag.id.in_([item for item in ids if item]))).all() if tag.active]
            # CEP variables may keep lower/upper limits grouped on the reading
            # tag instead of using dedicated foreign keys.
            if variable.reading_tag is not None:
                names = [variable.reading_tag.lower_limit_tag, variable.reading_tag.upper_limit_tag]
                grouped = self.db.scalars(select(PiTag).where(
                    PiTag.pi_server == variable.reading_tag.pi_server,
                    PiTag.pi_tag_name.in_([name for name in names if name]),
                    PiTag.active.is_(True),
                )).all()
                tags.extend(grouped)
            return list({tag.id: tag for tag in tags}.values())
        return list(self.db.scalars(select(PiTag).where(PiTag.active.is_(True)).order_by(PiTag.id)).all())

    def create(self, payload: HistoricalReloadRequest) -> list[PiBackfillJob]:
        self.validate_period(payload.start_time, payload.end_time)
        seconds = _interval_seconds(payload.interval)
        mode, seconds = normalize_mode(payload.mode, seconds)
        tags = self._tags(payload)
        jobs: list[PiBackfillJob] = []
        for tag in tags:
            if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
                # Serialize requests for one tag so two admins cannot both
                # enqueue the same missing interval concurrently.
                self.db.execute(text("SELECT pg_advisory_xact_lock(2147483001, :tag_id)"), {"tag_id": tag.id})
            missing = CoverageService.get_missing_intervals(self.db, tag.id, payload.start_time, payload.end_time, mode, seconds)
            for start, end in missing:
                duplicate = self.db.scalar(select(PiBackfillJob).where(
                    PiBackfillJob.tag_id == tag.id,
                    PiBackfillJob.mode == mode,
                    PiBackfillJob.interval_seconds == seconds,
                    PiBackfillJob.target_start == start,
                    PiBackfillJob.target_end == end,
                    PiBackfillJob.status.in_(("PENDING", "RUNNING")),
                ))
                if duplicate:
                    jobs.append(duplicate)
                    continue
                job = PiBackfillJob(tag_id=tag.id, mode=mode, interval_seconds=seconds, target_start=start, target_end=end, next_start=start, checkpoint_start=start, stage="PENDING", status="PENDING")
                self.db.add(job)
                jobs.append(job)
        self.db.commit()
        for job in jobs:
            self.db.refresh(job)
        return jobs

    def list(self, limit: int = 100) -> list[PiBackfillJob]:
        return list(self.db.scalars(select(PiBackfillJob).order_by(PiBackfillJob.created_at.desc()).limit(limit)).all())

    def get(self, job_id: int) -> PiBackfillJob:
        job = self.db.get(PiBackfillJob, job_id)
        if job is None:
            raise NotFoundError("Job de recarga não encontrado.", details={"job_id": job_id})
        return job

    def cancel(self, job_id: int) -> PiBackfillJob:
        job = self.get(job_id)
        if job.status in ("COMPLETED", "FAILED", "CANCELLED"):
            raise ConflictError("O job já terminou e não pode ser cancelado.")
        job.status = "CANCELLED"
        job.stage = "CANCELLED"
        self.db.commit()
        self.db.refresh(job)
        return job

    def coverage(self, tag_id: int, start: datetime, end: datetime, mode: str, interval: str | None) -> dict:
        self.validate_period(start, end)
        seconds = _interval_seconds(interval)
        normalized, seconds = normalize_mode(mode, seconds)
        tag = self.db.get(PiTag, tag_id)
        if tag is None:
            raise NotFoundError("Tag não encontrada.", details={"tag_id": tag_id})
        covered = CoverageService.get_coverage(self.db, tag_id, start, end, normalized, seconds)
        missing = CoverageService.get_missing_intervals(self.db, tag_id, start, end, normalized, seconds)
        encode = lambda rows: [{"start": a.isoformat(), "end": b.isoformat()} for a, b in rows]
        return {"tag_id": tag_id, "mode": normalized, "interval": _interval_label(seconds), "complete": not missing, "covered": encode(covered), "missing": encode(missing)}

    def summary(self) -> dict:
        active = list(self.db.scalars(select(PiTag).where(PiTag.active.is_(True))).all())
        tag_ids = [tag.id for tag in active]
        tags_with_data = set(self.db.scalars(select(PiIngestionCoverage.tag_id).where(PiIngestionCoverage.tag_id.in_(tag_ids), PiIngestionCoverage.status == "COMPLETE")).all()) if tag_ids else set()
        partial = set(self.db.scalars(select(PiIngestionCoverage.tag_id).where(PiIngestionCoverage.tag_id.in_(tag_ids), PiIngestionCoverage.status != "COMPLETE")).all()) if tag_ids else set()
        modes = [dict(row) for row in self.db.execute(select(PiIngestionCoverage.mode, PiIngestionCoverage.interval_seconds, func.count().label("ranges")).group_by(PiIngestionCoverage.mode, PiIngestionCoverage.interval_seconds)).mappings().all()]
        return {"total_active_tags": len(active), "tags_with_data": len(tags_with_data), "tags_without_data": len(set(tag_ids) - tags_with_data), "partial_tags": len(partial), "modes": modes}
