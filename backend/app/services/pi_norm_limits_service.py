"""Service for fetching norm limits (lower/upper) of a registered PiTag.

The norm limits are stored locally on ``PiTag.lower_limit_tag`` and
``PiTag.upper_limit_tag`` as PI tag names. This module is responsible for
resolving those names on the PI Web API using the same provider used for
the main time series query, returning the historical values for the
requested window.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    HistoricalDataNotLoadedError,
    NotFoundError,
    PiNotConfiguredError,
    TagInactiveError,
    ValidationError,
)
from app.integrations.pi.errors import (
    PiIntegrationError,
    PiTagNotFoundError,
)
from app.integrations.pi.manager import get_pi_data_provider
from app.integrations.pi.provider import PiDataProvider
from app.repositories.pi_tag_repository import PiTagRepository
from app.schemas.pi import (
    PiTagNormLimitPoint,
    PiTagNormLimitSeries,
    PiTagNormLimitsResponse,
)


def _path_for(pi_server: str, tag_name: str) -> str:
    return f"\\\\{pi_server}\\{tag_name}"


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


def _normalize_point(raw) -> PiTagNormLimitPoint:
    ts: datetime = raw.timestamp
    if isinstance(ts, datetime) and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    value = raw.value
    out_value: Optional[float] = float(value) if _is_finite_number(value) else None
    return PiTagNormLimitPoint(timestamp=ts, value=out_value)


class PiNormLimitsService:
    """Resolve and fetch norm limits (lower/upper) for a PiTag."""

    def __init__(
        self,
        db: Optional[Session] = None,
        provider: Optional[PiDataProvider] = None,
        session_factory=None,
    ) -> None:
        self.db = db
        self.repo = PiTagRepository(db) if db else None
        self.provider = provider
        self.session_factory = session_factory

    def _resolve_provider(self) -> PiDataProvider:
        if self.provider is None:
            self.provider = get_pi_data_provider()
        if self.provider is None:
            raise PiNotConfiguredError()
        return self.provider

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

        # Short-lived read of source tag metadata: connection is released before any external I/O
        if self.session_factory and not self.db:
            with self.session_factory() as s:
                repo = PiTagRepository(s)
                source = repo.get(source_tag_id)
                if source is None:
                    raise NotFoundError(
                        "Tag local nao encontrada.",
                        details={"pi_tag_id": source_tag_id},
                    )
                if not source.active:
                    raise TagInactiveError(
                        "A tag esta inativa e nao pode ser consultada.",
                        details={"pi_tag_id": source.id},
                    )
                pi_server = source.pi_server
                lower_name = (source.lower_limit_tag or "").strip() or None
                upper_name = (source.upper_limit_tag or "").strip() or None
                source_id = source.id
        else:
            if self.repo is None:
                raise NotFoundError("Tag local nao encontrada.", details={"pi_tag_id": source_tag_id})
            source = self.repo.get(source_tag_id)
            if source is None:
                raise NotFoundError(
                    "Tag local nao encontrada.",
                    details={"pi_tag_id": source_tag_id},
                )
            if not source.active:
                raise TagInactiveError(
                    "A tag esta inativa e nao pode ser consultada.",
                    details={"pi_tag_id": source.id},
                )
            pi_server = source.pi_server
            lower_name = (source.lower_limit_tag or "").strip() or None
            upper_name = (source.upper_limit_tag or "").strip() or None
            source_id = source.id
            if self.db:
                self.db.rollback()

        # No configured limits is a normal state, not a query error. This also
        # lets callers distinguish “nothing to draw” from a broken limit tag.

        max_count = max_count or settings.pi_query_max_points_per_tag

        if lower_name:
            lower = await self._fetch_one_safe(pi_server, lower_name, start_time, end_time, mode, interval, max_count)
        else:
            lower = self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=None, points=[]),
                errors=[],
            )

        if upper_name:
            upper = await self._fetch_one_safe(pi_server, upper_name, start_time, end_time, mode, interval, max_count)
        else:
            upper = self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=None, points=[]),
                errors=[],
            )

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

    class _FetchResult:
        def __init__(self, series: PiTagNormLimitSeries, errors: List[str]) -> None:
            self.series = series
            self.errors = errors

    async def _fetch_one_safe(self, pi_server, tag_name, start_time, end_time, mode, interval, max_count):
        try:
            return await self._fetch_one(pi_server, tag_name, start_time, end_time, mode, interval, max_count)
        except Exception as exc:
            reason = str(exc).strip() or exc.__class__.__name__
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
    ) -> Optional[tuple[List[PiTagNormLimitPoint], List[tuple[datetime, datetime]]]]:
        """Attempt to fetch limit points directly from the TimescaleDB hypertable."""
        try:
            session_ctx = self.session_factory() if self.session_factory else None
            db = session_ctx or self.db
            if not db:
                return None
            try:
                from app.models.pi_tag import PiTag
                from app.models.postgres import PiSample
                tag = db.query(PiTag).filter(PiTag.pi_tag_name == tag_name).first()
                if not tag:
                    return ([], [(start_time, end_time)])
                from app.services.coverage_service import CoverageService, normalize_mode
                requested_mode, interval_seconds = normalize_mode("RECORDED")
                rows = (
                    db.query(PiSample)
                    .filter(
                        PiSample.tag_id == tag.id,
                        PiSample.source_mode == requested_mode,
                        PiSample.ts >= start_time,
                        PiSample.ts < end_time,
                    )
                    .order_by(PiSample.ts.asc())
                    .limit(max_count)
                    .all()
                )
                seed = (
                    db.query(PiSample)
                    .filter(
                        PiSample.tag_id == tag.id,
                        PiSample.source_mode == requested_mode,
                        PiSample.ts < start_time,
                    )
                    .order_by(PiSample.ts.desc())
                    .first()
                )
                coverage_start = seed.ts if seed is not None else start_time
                if coverage_start.tzinfo is None:
                    coverage_start = coverage_start.replace(tzinfo=timezone.utc)
                gaps = CoverageService.get_missing_intervals(db, tag.id, coverage_start, end_time, requested_mode, interval_seconds)
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
        except HistoricalDataNotLoadedError:
            raise
        except Exception as exc:
            raise PiIntegrationError(f"Falha ao consultar histórico RECORDED da tag de limite {tag_name}: {exc}") from exc

    async def _fetch_one(
        self,
        pi_server: str,
        tag_name: str,
        start_time: datetime,
        end_time: datetime,
        mode: str,
        interval: Optional[str],
        max_count: int,
    ) -> "PiNormLimitsService._FetchResult":
        # Historical limits are read exclusively from TimescaleDB.
        db_pts = self._try_fetch_from_db(tag_name, start_time, end_time, mode, interval, max_count)
        if db_pts is not None:
            points, gaps = db_pts
            errors = []
            if gaps:
                errors.append(f"coverage ausente para {tag_name}: " + ", ".join(f"{a.isoformat()}–{b.isoformat()}" for a,b in gaps))
                if not points:
                    errors.append(f"tag de limite {tag_name!r} não está cadastrada localmente; histórico RECORDED indisponível")
            if not points:
                errors.append(f"sem seed ou eventos RECORDED para {tag_name}")
            if any(not point.good or point.questionable or point.substituted for point in points):
                errors.append(f"Bad/Timeout ou qualidade inválida em {tag_name}; validade interrompida até o próximo valor Good")
            if any(point.good and point.value is None for point in points):
                errors.append(f"estado inválido em {tag_name}; validade interrompida até o próximo valor Good")
            return self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=tag_name, points=points, coverage_gaps=gaps, error="; ".join(errors) or None),
                errors=errors,
            )

        raise ValidationError(f"tag de limite {tag_name!r} não está cadastrada localmente")
