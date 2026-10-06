"""Read materialized RECORDED norm-limit states exclusively from TimescaleDB.

PI acquisition belongs to reload-norm-limits and its hourly worker. Missing
local history is an optional overlay diagnostic, never an external fallback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    NotFoundError,
    TagInactiveError,
    ValidationError,
)
from app.schemas.pi import (
    PiTagNormLimitPoint,
    PiTagNormLimitSeries,
    PiTagNormLimitsResponse,
)


def _is_finite_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        fv = float(value)
        return fv == fv and fv not in (float("inf"), float("-inf"))
    if isinstance(value, str):
        try:
            fv = float(value)
        except ValueError:
            return False
        return fv == fv and fv not in (float("inf"), float("-inf"))
    return False


class PiNormLimitsService:
    """Resolve configured local tags and read their RECORDED history."""

    def __init__(
        self,
        db: Optional[Session] = None,
        provider: Optional[object] = None,
        session_factory=None,
    ) -> None:
        self.db = db
        self.session_factory = session_factory

    async def fetch_norm_limits(
        self,
        source_tag_id: int,
        start_time: datetime,
        end_time: datetime,
        mode: str,
        interval: Optional[str] = None,
        max_count: Optional[int] = None,
    ) -> PiTagNormLimitsResponse:
        if start_time >= end_time:
            raise ValidationError(
                "A data inicial deve ser menor que a data final.",
                details={
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                },
            )
        if mode != "recorded":
            raise ValidationError("Limites históricos aceitam somente dados RECORDED.")

        # Project only overlay metadata: unrelated ORM relationships/columns must
        # neither fan out SQL queries nor prevent this optional read.
        session = self.session_factory() if self.session_factory and not self.db else self.db
        if session is None:
            raise NotFoundError("Tag local nao encontrada.", details={"pi_tag_id": source_tag_id})
        try:
            source, limits = self._read_configuration(session, source_tag_id)
        except SQLAlchemyError as exc:
            raise ValidationError(self._query_error(exc, "configuração de limites")) from exc
        finally:
            if session is not self.db:
                session.close()
            elif self.db:
                self.db.rollback()
        source_id, pi_server, lower_name, upper_name = source
        max_count = max_count or settings.pi_query_max_points_per_tag
        results = []
        for name in (lower_name, upper_name):
            if name:
                results.append(await self._fetch_one_safe(
                    pi_server, name, start_time, end_time, mode, interval, max_count,
                    limits.get(name),
                ))
            else:
                results.append(self._FetchResult(PiTagNormLimitSeries(tag_name=None, points=[]), []))
        lower, upper = results

        start_utc = start_time.astimezone(timezone.utc)
        end_utc = end_time.astimezone(timezone.utc)
        return PiTagNormLimitsResponse(
            source_tag_id=source_id,
            start_time=start_utc,
            end_time=end_utc,
            mode=mode,  # type: ignore[arg-type]
            interval=interval,
            lower=lower.series,
            upper=upper.series,
            errors=lower.errors + upper.errors,
        )

    @staticmethod
    def _query_error(exc: Exception, context: str) -> str:
        if isinstance(exc, SQLAlchemyError):
            original = getattr(exc, "orig", None)
            code = getattr(original, "sqlstate", None)
            if code == "57014":
                return f"Timeout na consulta RECORDED de {context} (SQLSTATE 57014)."
            suffix = f"SQLSTATE {code}" if code else exc.__class__.__name__
            return f"Falha na consulta RECORDED de {context} ({suffix})."
        return f"Falha na consulta RECORDED de {context} ({exc.__class__.__name__})."

    @staticmethod
    def _read_configuration(db: Session, source_tag_id: int):
        from app.models.pi_tag import PiTag
        row = db.execute(select(
            PiTag.id, PiTag.pi_server, PiTag.lower_limit_tag,
            PiTag.upper_limit_tag, PiTag.active,
        ).where(PiTag.id == source_tag_id)).one_or_none()
        if row is None:
            raise NotFoundError("Tag local nao encontrada.", details={"pi_tag_id": source_tag_id})
        if not row.active:
            raise TagInactiveError(details={"pi_tag_id": source_tag_id})
        lower = (row.lower_limit_tag or "").strip() or None
        upper = (row.upper_limit_tag or "").strip() or None
        names = {name for name in (lower, upper) if name}
        limits = {}
        if names:
            # Resolve both configured limits and their availability in one query.
            rows = db.execute(select(
                PiTag.pi_tag_name, PiTag.id,
            ).where(PiTag.pi_server == row.pi_server, PiTag.pi_tag_name.in_(names))).all()
            limits = {item.pi_tag_name: (item.id, None) for item in rows}
        return (row.id, row.pi_server, lower, upper), limits

    class _FetchResult:
        def __init__(self, series: PiTagNormLimitSeries, errors: List[str]) -> None:
            self.series = series
            self.errors = errors

    async def _fetch_one_safe(self, pi_server, tag_name, start_time, end_time, mode, interval, max_count, local_limit):
        try:
            return await self._fetch_one(pi_server, tag_name, start_time, end_time, mode, interval, max_count, local_limit)
        except Exception as exc:
            reason = self._query_error(exc, tag_name)
            return self._FetchResult(
                PiTagNormLimitSeries(tag_name=tag_name, points=[], error=reason),
                [f"{tag_name}: {reason}"],
            )

    def _try_fetch_from_db(
        self,
        tag_name: str,
        start_time: datetime,
        end_time: datetime,
        mode: str,
        interval: Optional[str],
        max_count: int,
        local_limit,
    ) -> Optional[tuple[List[PiTagNormLimitPoint], List[tuple[datetime, datetime]]]]:
        """Attempt to fetch limit points directly from the TimescaleDB hypertable."""
        session_ctx = self.session_factory() if self.session_factory else None
        db = session_ctx or self.db
        if not db:
            return None
        try:
            from app.models.postgres import PiSample
            tag_id, _ = local_limit
            read_end = end_time
            from app.services.coverage_service import CoverageService, normalize_mode
            requested_mode, interval_seconds = normalize_mode("RECORDED")
            rows = (
                db.query(PiSample)
                .filter(
                    PiSample.tag_id == tag_id,
                    PiSample.source_mode == requested_mode,
                    PiSample.ts >= start_time,
                    PiSample.ts < read_end,
                )
                .order_by(PiSample.ts.asc())
                .limit(max_count)
                .all()
            )
            seed = (
                db.query(PiSample)
                .filter(
                    PiSample.tag_id == tag_id,
                    PiSample.source_mode == requested_mode,
                    PiSample.ts < min(start_time, read_end),
                )
                .order_by(PiSample.ts.desc())
                .first()
            )
            # The seed is a state input. Coverage is only required for the
            # requested window, never for history before its start.
            gaps = CoverageService.get_missing_intervals(db, tag_id, start_time, read_end, requested_mode, interval_seconds) if start_time < read_end else []
            if seed is not None:
                rows = [seed, *rows]
            pts = []
            for r in rows:
                ts = r.ts
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                raw_value = r.value_double if r.value_type in {"double", "float", "int"} else r.value_boolean if r.value_type == "boolean" else r.value_text
                val = float(raw_value) if _is_finite_number(raw_value) else None
                pts.append(PiTagNormLimitPoint(timestamp=ts, value=val, good=r.good, questionable=r.questionable, substituted=r.substituted))
            return (pts, gaps)
        finally:
            if session_ctx:
                session_ctx.close()

    async def _fetch_one(
        self,
        pi_server: str,
        tag_name: str,
        start_time: datetime,
        end_time: datetime,
        mode: str,
        interval: Optional[str],
        max_count: int,
        local_limit,
    ) -> "PiNormLimitsService._FetchResult":
        # Historical limits are read exclusively from TimescaleDB.
        if local_limit is None:
            reason = f"Limite aguardando a próxima recarga histórica: {tag_name!r} ainda não foi materializado no TimescaleDB."
            return self._FetchResult(PiTagNormLimitSeries(
                tag_name=tag_name, points=[], coverage_gaps=[(start_time, end_time)], error=reason,
            ), [reason])
        db_pts = self._try_fetch_from_db(tag_name, start_time, end_time, mode, interval, max_count, local_limit)
        if db_pts is not None:
            points, gaps = db_pts
            errors = []
            if gaps:
                errors.append(f"Cobertura RECORDED pendente para limite {tag_name}: " + ", ".join(f"{a.isoformat()}–{b.isoformat()}" for a,b in gaps))
            if not points:
                errors.append(f"Limite aguardando a próxima recarga histórica: sem seed ou eventos RECORDED para {tag_name}.")
            if any(not point.good or point.questionable for point in points):
                errors.append(f"Bad/Timeout ou qualidade inválida em {tag_name}; validade interrompida até o próximo valor Good")
            if any(point.good and point.value is None for point in points):
                errors.append(f"estado inválido em {tag_name}; validade interrompida até o próximo valor Good")
            return self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=tag_name, points=points, coverage_gaps=gaps, error="; ".join(errors) or None),
                errors=errors,
            )

        raise ValidationError(f"tag de limite {tag_name!r} não está cadastrada localmente")
