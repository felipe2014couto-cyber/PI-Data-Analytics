"""Service that orchestrates PI Web API interactions for local tags."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    NotFoundError,
    PiNotConfiguredError,
    QueryLimitExceededError,
    TagInactiveError,
    TimeRangeInvalidError,
)
from app.integrations.pi.errors import (
    PiAuthError,
    PiIntegrationError,
    PiInvalidResponseError,
    PiNotConfiguredError as PiNotConfiguredIntegrationError,
    PiSSLError,
    PiTagNotFoundError,
    PiTimeoutError,
    PiUnavailableError,
)
from app.integrations.pi.manager import get_pi_data_provider
from app.integrations.pi.provider import PiDataProvider, PiPoint
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagValidationStatus
from app.models.section import Section
from app.models.variable_type import VariableType
from app.repositories.pi_tag_repository import PiTagRepository
from app.schemas.pi import (
    PiHealth,
    PiTagResolution,
    PiTagValidationResult,
    TimeSeries,
    TimeSeriesPoint,
    TimeSeriesRequest,
    TimeSeriesSeries,
)

logger = logging.getLogger("pi_analytics_data.service.pi")


class PiService:
    """High-level service for PI Web API operations.

    This service is the only place that combines the local catalog with the
    remote PI Web API. It is responsible for:
    * resolving tags and caching the WebId locally;
    * keeping ``validation_status`` consistent with the resolution outcome;
    * fetching time series and normalizing the payload to a stable shape.
    """

    def __init__(self, db: Session, provider: Optional[PiDataProvider] = None) -> None:
        self.db = db
        self.provider = provider
        self.repo = PiTagRepository(db)

    def _resolve_provider(self) -> PiDataProvider:
        if self.provider is None:
            self.provider = get_pi_data_provider()
        if self.provider is None:
            raise PiNotConfiguredError()
        return self.provider

    @staticmethod
    def _path_for(tag: PiTag) -> str:
        return f"\\\\{tag.pi_server}\\{tag.pi_tag_name}"

    async def check_health(self) -> PiHealth:
        provider = self._resolve_provider()
        if not settings.is_pi_configured():
            return PiHealth(
                status="not_configured",
                base_url=settings.pi_web_api_base_url or None,
                data_server=settings.pi_data_server_name or None,
                response_time_ms=None,
                message="PI Web API nao configurado.",
            )
        started = datetime.utcnow()
        try:
            await provider.ping()
        except PiIntegrationError as exc:
            elapsed = int((datetime.utcnow() - started).total_seconds() * 1000)
            return PiHealth(
                status="unavailable",
                base_url=settings.pi_web_api_base_url,
                data_server=settings.pi_data_server_name,
                response_time_ms=elapsed,
                message=exc.safe_message,
                error_code=exc.code,
            )
        elapsed = int((datetime.utcnow() - started).total_seconds() * 1000)
        return PiHealth(
            status="connected",
            base_url=settings.pi_web_api_base_url,
            data_server=settings.pi_data_server_name,
            response_time_ms=elapsed,
        )

    def _get_tag(self, tag_id: int) -> PiTag:
        tag = self.repo.get(tag_id)
        if tag is None:
            raise NotFoundError(
                "Tag local nao encontrada.",
                details={"pi_tag_id": tag_id},
            )
        return tag

    def _ensure_active(self, tag: PiTag) -> None:
        if not tag.active:
            raise TagInactiveError(
                "A tag esta inativa e nao pode ser consultada.",
                details={"pi_tag_id": tag.id},
            )

    async def _resolve_web_id(self, tag: PiTag) -> Tuple[Optional[PiPoint], Optional[PiIntegrationError]]:
        provider = self._resolve_provider()
        path = self._path_for(tag)
        try:
            point = await provider.resolve_point(path)
            return point, None
        except PiIntegrationError as exc:
            return None, exc

    async def validate_tag(self, tag_id: int) -> PiTagValidationResult:
        tag = self._get_tag(tag_id)
        if not tag.active:
            raise TagInactiveError(
                "A tag esta inativa e nao pode ser validada.",
                details={"pi_tag_id": tag.id},
            )

        if not settings.is_pi_configured():
            raise PiNotConfiguredError()

        point, error = await self._resolve_web_id(tag)
        now = datetime.utcnow()
        if point is not None:
            tag.pi_web_id = point.web_id
            tag.validation_status = PiTagValidationStatus.VALID
            tag.validation_message = "Tag localizada no PI Web API."
            tag.validated_at = now
            self.db.commit()
            self.db.refresh(tag)
            return PiTagValidationResult(
                tag_id=tag.id,
                status=tag.validation_status.value,
                web_id=point.web_id,
                message=tag.validation_message,
                validated_at=tag.validated_at,
                metadata={
                    "name": point.name,
                    "engineering_unit": point.engineering_unit,
                    "point_type": point.point_type,
                },
            )

        if error is None:
            tag.pi_web_id = None
            tag.validation_status = PiTagValidationStatus.INVALID
            tag.validation_message = "Tag nao encontrada no PI Web API."
            tag.validated_at = now
            self.db.commit()
            self.db.refresh(tag)
            return PiTagValidationResult(
                tag_id=tag.id,
                status=tag.validation_status.value,
                web_id=None,
                message=tag.validation_message,
                validated_at=tag.validated_at,
            )

        if isinstance(error, PiTagNotFoundError):
            tag.pi_web_id = None
            tag.validation_status = PiTagValidationStatus.INVALID
            tag.validation_message = "Tag nao encontrada no PI Web API."
            tag.validated_at = now
            self.db.commit()
            self.db.refresh(tag)
            return PiTagValidationResult(
                tag_id=tag.id,
                status=tag.validation_status.value,
                web_id=None,
                message=tag.validation_message,
                validated_at=tag.validated_at,
            )

        if isinstance(error, (PiAuthError, PiTimeoutError, PiSSLError, PiUnavailableError, PiInvalidResponseError)):
            # Preserve cadastro, only update status/message.
            tag.validation_status = PiTagValidationStatus.ERROR
            tag.validation_message = error.safe_message
            tag.validated_at = now
            self.db.commit()
            self.db.refresh(tag)
            return PiTagValidationResult(
                tag_id=tag.id,
                status=tag.validation_status.value,
                web_id=tag.pi_web_id,
                message=tag.validation_message,
                validated_at=tag.validated_at,
                error_code=error.code,
            )

        # Unknown error: treat as ERROR.
        tag.validation_status = PiTagValidationStatus.ERROR
        tag.validation_message = "Falha desconhecida na validacao."
        tag.validated_at = now
        self.db.commit()
        self.db.refresh(tag)
        return PiTagValidationResult(
            tag_id=tag.id,
            status=tag.validation_status.value,
            web_id=tag.pi_web_id,
            message=tag.validation_message,
            validated_at=tag.validated_at,
        )

    async def validate_tags(self, tag_ids: Optional[Iterable[int]] = None) -> Dict:
        if not settings.is_pi_configured():
            raise PiNotConfiguredError()

        if tag_ids is None:
            tags, _ = self.repo.list(active=True, page=1, page_size=settings.pi_query_max_tags)
        else:
            ids = list(tag_ids)
            tags = []
            for tag_id in ids:
                tag = self.repo.get(tag_id)
                if tag is not None and tag.active:
                    tags.append(tag)

        results: List[PiTagValidationResult] = []
        summary = {"total": len(tags), "valid": 0, "invalid": 0, "error": 0}
        for tag in tags:
            result = await self.validate_tag(tag.id)
            results.append(result)
            summary[result.status.lower()] = summary.get(result.status.lower(), 0) + 1
        return {"summary": summary, "results": results}

    # ------------------------------------------------------------------ time series

    def _validate_time_range(self, request: TimeSeriesRequest) -> None:
        if request.start_time >= request.end_time:
            raise TimeRangeInvalidError(
                "A data inicial deve ser menor que a data final.",
                details={
                    "start_time": request.start_time.isoformat(),
                    "end_time": request.end_time.isoformat(),
                },
            )
        if request.mode == "interpolated" and not request.interval:
            raise TimeRangeInvalidError(
                "O intervalo e obrigatorio no modo interpolated.",
                details={"mode": request.mode},
            )

    def _load_tags(self, tag_ids: List[int]) -> List[PiTag]:
        if not tag_ids:
            raise TimeRangeInvalidError(
                "A lista de tag_ids nao pode estar vazia.",
                details={"tag_ids": tag_ids},
            )
        max_tags = settings.pi_query_max_tags
        if len(tag_ids) > max_tags:
            raise QueryLimitExceededError(
                "Quantidade de tags excede o limite configurado.",
                details={"requested": len(tag_ids), "limit": max_tags},
            )
        tags: List[PiTag] = []
        for tag_id in tag_ids:
            tag = self.repo.get(tag_id)
            if tag is None:
                raise NotFoundError(
                    "Tag local nao encontrada.",
                    details={"pi_tag_id": tag_id},
                )
            self._ensure_active(tag)
            tags.append(tag)
        return tags

    def _resolve_max_count(self, request: TimeSeriesRequest) -> int:
        limit = settings.pi_query_max_points_per_tag
        requested = request.max_count or limit
        if requested > limit:
            raise QueryLimitExceededError(
                "max_count excede o limite configurado para esta POC.",
                details={"requested": requested, "limit": limit},
            )
        return requested

    async def _ensure_web_id(self, tag: PiTag) -> Optional[PiPoint]:
        if tag.pi_web_id:
            return None
        point, error = await self._resolve_web_id(tag)
        if point is not None:
            tag.pi_web_id = point.web_id
            tag.validation_status = PiTagValidationStatus.VALID
            tag.validation_message = "Tag resolvida automaticamente durante consulta."
            tag.validated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(tag)
            return point
        # Failed resolution: keep status updated if it was an INVALID response.
        if isinstance(error, PiTagNotFoundError):
            tag.pi_web_id = None
            tag.validation_status = PiTagValidationStatus.INVALID
            tag.validation_message = "Tag nao encontrada no PI Web API."
            tag.validated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(tag)
        elif error is not None:
            tag.validation_status = PiTagValidationStatus.ERROR
            tag.validation_message = error.safe_message
            tag.validated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(tag)
        return None

    async def _resolve_if_needed(self, tag: PiTag) -> Optional[PiPoint]:
        point = await self._ensure_web_id(tag)
        if point is not None:
            return point
        if not tag.pi_web_id:
            return None
        return None

    async def _fetch_series(
        self,
        tag: PiTag,
        request: TimeSeriesRequest,
        max_count: int,
    ) -> TimeSeriesSeries:
        provider = self._resolve_provider()
        await self._resolve_if_needed(tag)
        if not tag.pi_web_id:
            raise PiTagNotFoundError(
                "WebId nao disponivel para a tag.",
                details={"pi_tag_id": tag.id, "pi_tag_name": tag.pi_tag_name},
            )

        try:
            if request.mode == "recorded":
                response = await provider.get_recorded_values(
                    tag.pi_web_id, request.start_time, request.end_time, max_count=max_count
                )
                values = response.values
            else:
                response = await provider.get_interpolated_values(
                    tag.pi_web_id,
                    request.start_time,
                    request.end_time,
                    request.interval or "1m",
                    max_count=max_count,
                )
                values = response.values
        except PiTagNotFoundError:
            # Try re-resolving once with the current name.
            tag.pi_web_id = None
            self.db.commit()
            point = await self._ensure_web_id(tag)
            if point is None or not tag.pi_web_id:
                raise
            if request.mode == "recorded":
                response = await provider.get_recorded_values(
                    tag.pi_web_id,
                    request.start_time,
                    request.end_time,
                    max_count=max_count,
                )
            else:
                response = await provider.get_interpolated_values(
                    tag.pi_web_id,
                    request.start_time,
                    request.end_time,
                    request.interval or "1m",
                    max_count=max_count,
                )
            values = response.values

        return self._build_series(tag, request, values)

    def _build_series(
        self,
        tag: PiTag,
        request: TimeSeriesRequest,
        values: Iterable,
    ) -> TimeSeriesSeries:
        equipment: Optional[Equipment] = tag.equipment
        section: Optional[Section] = tag.section
        variable_type: Optional[VariableType] = tag.variable_type
        points = [
            TimeSeriesPoint(
                timestamp=v.timestamp.astimezone(timezone.utc),
                value=v.value,
                good=v.good,
                questionable=v.questionable,
                substituted=v.substituted,
            )
            for v in values
        ]
        return TimeSeriesSeries(
            tag_id=tag.id,
            tag_name=tag.pi_tag_name,
            display_name=tag.display_name,
            equipment=equipment.code if equipment else None,
            section=section.code if section else None,
            variable_type=variable_type.code if variable_type else None,
            unit=tag.engineering_unit,
            points=points,
        )

    async def fetch_time_series(self, request: TimeSeriesRequest) -> TimeSeries:
        self._validate_time_range(request)
        tags = self._load_tags(request.tag_ids)
        max_count = self._resolve_max_count(request)

        series: List[TimeSeriesSeries] = []
        errors: List[dict] = []

        for tag in tags:
            try:
                built = await self._fetch_series(tag, request, max_count)
                series.append(built)
            except PiIntegrationError as exc:
                errors.append(
                    {
                        "tag_id": tag.id,
                        "code": exc.code,
                        "message": exc.safe_message,
                    }
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("Erro inesperado ao consultar serie temporal.")
                errors.append(
                    {
                        "tag_id": tag.id,
                        "code": "INTERNAL_ERROR",
                        "message": "Falha ao consultar a serie temporal.",
                    }
                )

        start_time = request.start_time.astimezone(timezone.utc)
        end_time = request.end_time.astimezone(timezone.utc)
        return TimeSeries(
            start_time=start_time,
            end_time=end_time,
            mode=request.mode,
            series=series,
            errors=errors,
        )
