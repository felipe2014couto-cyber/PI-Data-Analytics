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
        if mode not in ("recorded", "interpolated"):
            raise ValidationError(
                "Modo invalido. Utilize 'recorded' ou 'interpolated'.",
                details={"mode": mode},
            )
        if mode == "interpolated" and not interval:
            raise ValidationError(
                "O intervalo e obrigatorio no modo interpolated.",
                details={"mode": mode},
            )

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

        if not lower_name and not upper_name:
            raise ValidationError(
                "A serie selecionada nao possui tags de limite cadastradas.",
                details={
                    "pi_tag_id": source_id,
                    "lower_limit_tag": lower_name,
                    "upper_limit_tag": upper_name,
                },
            )

        provider = self._resolve_provider()
        max_count = max_count or settings.pi_query_max_points_per_tag

        if lower_name:
            lower = await self._fetch_one(
                provider=provider,
                pi_server=pi_server,
                tag_name=lower_name,
                start_time=start_time,
                end_time=end_time,
                mode=mode,
                interval=interval,
                max_count=max_count,
            )
        else:
            lower = self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=None, points=[]),
                errors=[],
            )

        if upper_name:
            upper = await self._fetch_one(
                provider=provider,
                pi_server=pi_server,
                tag_name=upper_name,
                start_time=start_time,
                end_time=end_time,
                mode=mode,
                interval=interval,
                max_count=max_count,
            )
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

    async def _fetch_one(
        self,
        provider: PiDataProvider,
        pi_server: str,
        tag_name: str,
        start_time: datetime,
        end_time: datetime,
        mode: str,
        interval: Optional[str],
        max_count: int,
    ) -> "PiNormLimitsService._FetchResult":
        path = _path_for(pi_server, tag_name)
        try:
            point = await provider.resolve_point(path)
        except PiIntegrationError as exc:
            return self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=tag_name, points=[]),
                errors=[f"Tag de limite nao encontrada no PI: {tag_name} ({exc.safe_message})."],
            )
        if point is None:
            return self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=tag_name, points=[]),
                errors=[f"Tag de limite nao encontrada no PI: {tag_name}."],
            )
        try:
            if mode == "recorded":
                response = await provider.get_recorded_values(
                    point.web_id, start_time, end_time, max_count=max_count
                )
                raw = response.values
            else:
                response = await provider.get_interpolated_values(
                    point.web_id,
                    start_time,
                    end_time,
                    interval or "1m",
                    max_count=max_count,
                )
                raw = response.values
        except PiTagNotFoundError:
            return self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=tag_name, points=[]),
                errors=[f"Tag de limite nao encontrada no PI: {tag_name}."],
            )
        except PiIntegrationError as exc:
            return self._FetchResult(
                series=PiTagNormLimitSeries(tag_name=tag_name, points=[]),
                errors=[f"Falha ao consultar a tag de limite {tag_name}: {exc.safe_message}."],
            )
        series = PiTagNormLimitSeries(
            tag_name=tag_name,
            points=[_normalize_point(raw_point) for raw_point in raw],
        )
        errors: List[str] = []
        if not series.points:
            errors.append(f"Sem dados para o periodo: {tag_name}.")
        return self._FetchResult(series=series, errors=errors)