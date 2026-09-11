from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from app.models.postgres import PiIngestionCoverage

Interval = Tuple[datetime, datetime]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_mode(mode: str, interval_seconds: Optional[int] = None) -> tuple[str, Optional[int]]:
    normalized = mode.upper()
    if normalized == "RECORDED":
        return "RECORDED", None
    if normalized == "INTERPOLATED":
        if not interval_seconds:
            raise ValueError("INTERPOLATED exige interval_seconds")
        return f"INTERPOLATED_{interval_seconds}S", interval_seconds
    if normalized.startswith("INTERPOLATED_") and normalized.endswith("S"):
        return normalized, int(normalized.removeprefix("INTERPOLATED_").removesuffix("S"))
    raise ValueError(f"Modo de cobertura invalido: {mode}")

class CoverageService:
    @staticmethod
    def get_coverage(
        db: Session,
        tag_id: int,
        start: datetime,
        end: datetime,
        mode: str = "RECORDED",
        interval_seconds: Optional[int] = None,
    ) -> List[Interval]:
        """
        Retorna uma lista de intervalos contínuos (start, end) que já estão cobertos
        pela ingestão no banco de dados para a tag especificada.
        """
        if start >= end:
            return []
        mode, interval_seconds = normalize_mode(mode, interval_seconds)
        stmt = select(PiIngestionCoverage).where(
            and_(
                PiIngestionCoverage.tag_id == tag_id,
                PiIngestionCoverage.mode == mode,
                PiIngestionCoverage.interval_seconds == interval_seconds,
                PiIngestionCoverage.status == "COMPLETE",
                PiIngestionCoverage.range_end > start,
                PiIngestionCoverage.range_start < end,
            )
        ).order_by(PiIngestionCoverage.range_start.asc())

        coverages = db.execute(stmt).scalars().all()

        if not coverages:
            return []

        merged: List[Interval] = []
        for cov in coverages:
            current = (max(_utc(cov.range_start), _utc(start)), min(_utc(cov.range_end), _utc(end)))
            if current[0] >= current[1]:
                continue
            if merged and current[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], current[1]))
            else:
                merged.append(current)
        return merged

    @staticmethod
    def get_missing_intervals(
        db: Session,
        tag_id: int,
        start: datetime,
        end: datetime,
        mode: str = "RECORDED",
        interval_seconds: Optional[int] = None,
    ) -> List[Interval]:
        """
        Calcula as lacunas (missing intervals) subtraindo a cobertura existente
        do intervalo solicitado [start, end].
        """
        covered = CoverageService.get_coverage(db, tag_id, start, end, mode, interval_seconds)

        if not covered:
            return [(start, end)]

        missing = []
        current_req = start

        for cov_start, cov_end in covered:
            if current_req < cov_start:
                missing.append((current_req, cov_start))
            current_req = max(current_req, cov_end)

        if current_req < end:
            missing.append((current_req, end))

        return missing

    @staticmethod
    def record_coverage(
        db: Session,
        tag_id: int,
        start: datetime,
        end: datetime,
        mode: str = "RECORDED",
        interval_seconds: Optional[int] = None,
        *,
        status: str = "COMPLETE",
        pi_web_id: Optional[str] = None,
    ) -> None:
        """
        Registra um novo intervalo de cobertura no banco de dados.
        (Opcionalmente poderia mesclar registros no DB para evitar muitas linhas,
        mas por simplicidade inserimos e deixamos o get_coverage mesclar em tempo de leitura).
        """
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start >= end or status != "COMPLETE":
            return
        mode, interval_seconds = normalize_mode(mode, interval_seconds)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(2147483000, :tag_id)"), {"tag_id": tag_id})
        adjacent = db.execute(
            select(PiIngestionCoverage).where(
                and_(
                    PiIngestionCoverage.tag_id == tag_id,
                    PiIngestionCoverage.mode == mode,
                    PiIngestionCoverage.interval_seconds == interval_seconds,
                    PiIngestionCoverage.status == "COMPLETE",
                    PiIngestionCoverage.range_end >= start,
                    PiIngestionCoverage.range_start <= end,
                )
            ).with_for_update()
        ).scalars().all()
        merged_start, merged_end = start, end
        for row in adjacent:
            merged_start = min(merged_start, _utc(row.range_start))
            merged_end = max(merged_end, _utc(row.range_end))
            pi_web_id = pi_web_id or row.pi_web_id
            db.delete(row)
        db.add(PiIngestionCoverage(
            tag_id=tag_id,
            range_start=merged_start,
            range_end=merged_end,
            mode=mode,
            interval_seconds=interval_seconds,
            status="COMPLETE",
            pi_web_id=pi_web_id,
        ))
