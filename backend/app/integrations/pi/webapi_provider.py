"""Concrete implementation of :class:`PiDataProvider` against a PI Web API."""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from pydantic import SecretStr

from app.integrations.pi.errors import (
    PiAuthError,
    PiIntegrationError,
    PiInvalidResponseError,
    PiNotConfiguredError,
    PiRateLimitedError,
    PiSSLError,
    PiTagNotFoundError,
    PiTimeoutError,
    PiUnavailableError,
    PiUnsupportedAuthError,
)
from app.core.exceptions import QueryCancelledError
from app.integrations.pi.provider import (
    PiDataProvider,
    PiInterpolatedValues,
    PiPoint,
    PiRecordedValues,
    PiValue,
)

try:
    from app.core.config import settings as _pool_settings
except ImportError:
    _pool_settings = None

logger = logging.getLogger("pi_analytics_data.pi")


def _first_value(entry: Dict[str, Any], *keys: str) -> Any:
    """Return the first key found in a dictionary.

    This allows the provider to handle both the original PI Web API field
    names and the normalized lowercase names used by some test doubles.
    """
    for key in keys:
        if key in entry:
            return entry[key]
    return None


def _normalize_timestamp(raw: Any) -> datetime:
    """Convert a PI timestamp to a timezone-aware datetime in UTC."""
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)

    if not isinstance(raw, str):
        raise PiInvalidResponseError(
            "Timestamp retornado pelo PI Web API em formato invalido."
        )

    text = raw.strip()

    if not text:
        raise PiInvalidResponseError(
            "Timestamp vazio retornado pelo PI Web API."
        )

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PiInvalidResponseError(
            "Timestamp retornado pelo PI Web API nao esta em formato ISO 8601."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _normalize_value(raw: Any) -> object:
    """Normalize a PI value while preserving its useful original type."""
    if raw is None:
        return None

    if isinstance(raw, bool):
        return raw

    if isinstance(raw, (int, float)):
        return raw

    if isinstance(raw, dict):
        # PI digital states commonly arrive in this format:
        #
        # {
        #   "Name": "Shutdown",
        #   "Value": 248,
        #   "IsSystem": true
        # }
        #
        # The human-readable Name is more useful than the internal digital
        # state number.
        name = _first_value(raw, "Name", "name")

        if isinstance(name, str) and name:
            return name

        if "Value" in raw:
            return _normalize_value(raw["Value"])

        if "value" in raw:
            return _normalize_value(raw["value"])

        return str(raw)

    if isinstance(raw, str):
        return raw

    return raw


def _normalize_boolean(raw: Any, default: bool) -> bool:
    """Convert common PI/JSON boolean representations to bool."""
    if raw is None:
        return default

    if isinstance(raw, bool):
        return raw

    if isinstance(raw, (int, float)):
        return bool(raw)

    if isinstance(raw, str):
        normalized = raw.strip().lower()

        if normalized in {"true", "1", "yes", "y", "sim"}:
            return True

        if normalized in {"false", "0", "no", "n", "nao", "n�o"}:
            return False

    return default


def _parse_quality(
    good_raw: Any,
    questionable_raw: Any = None,
    substituted_raw: Any = None,
) -> Tuple[bool, bool, bool]:
    """Return PI quality flags without inverting their meaning.

    PI Web API returns three independent boolean fields:

    - Good
    - Questionable
    - Substituted

    They are not a numeric status code. In particular, ``Good=true`` means
    exactly that the value is good.
    """
    good = _normalize_boolean(good_raw, default=True)
    questionable = _normalize_boolean(questionable_raw, default=False)
    substituted = _normalize_boolean(substituted_raw, default=False)

    return good, questionable, substituted


def _parse_value_entry(entry: Dict[str, Any]) -> PiValue:
    timestamp_raw = _first_value(entry, "Timestamp", "timestamp")
    value_raw = _first_value(entry, "Value", "value")

    good_raw = _first_value(entry, "Good", "good")
    questionable_raw = _first_value(
        entry,
        "Questionable",
        "questionable",
    )
    substituted_raw = _first_value(
        entry,
        "Substituted",
        "substituted",
    )

    timestamp = _normalize_timestamp(timestamp_raw)
    value = _normalize_value(value_raw)

    good, questionable, substituted = _parse_quality(
        good_raw,
        questionable_raw,
        substituted_raw,
    )

    units = _first_value(
        entry,
        "UnitsAbbreviation",
        "Units",
        "units_abbreviation",
        "units",
    )

    return PiValue(
        timestamp=timestamp,
        value=value,
        good=good,
        questionable=questionable,
        substituted=substituted,
        units=units,
    )


_global_semaphore: Optional[asyncio.Semaphore] = None
_global_semaphore_capacity: int = 0


def set_global_semaphore(capacity: int) -> asyncio.Semaphore:
    global _global_semaphore, _global_semaphore_capacity
    if capacity < 1:
        capacity = 1
    _global_semaphore = asyncio.Semaphore(capacity)
    _global_semaphore_capacity = capacity
    logger.info("Global PI semaphore created with capacity %d", capacity)
    return _global_semaphore


def get_global_semaphore() -> asyncio.Semaphore:
    global _global_semaphore
    if _global_semaphore is None:
        _global_semaphore = asyncio.Semaphore(4)
        _global_semaphore_capacity = 4
    return _global_semaphore


def reset_global_semaphore() -> None:
    global _global_semaphore, _global_semaphore_capacity
    _global_semaphore = None
    _global_semaphore_capacity = 0


class PiWebApiDataProvider(PiDataProvider):
    """PI Web API implementation using HTTPX AsyncClient."""

    def __init__(
        self,
        base_url: str,
        data_server: str,
        auth_mode: str = "none",
        username: Optional[str] = None,
        password: Optional[SecretStr] = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        max_retries: int = 2,
        concurrency: int = 4,
    ) -> None:
        if auth_mode not in {"none", "basic"}:
            raise PiUnsupportedAuthError(
                f"Modo de autenticacao '{auth_mode}' nao suportado. "
                "Use 'none' ou 'basic'."
            )

        self.base_url = base_url.rstrip("/") + "/" if base_url else ""
        self.data_server = data_server
        self.auth_mode = auth_mode
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

        self._auth: Optional[httpx.BasicAuth] = None

        if auth_mode == "basic":
            if not username or password is None:
                raise PiUnsupportedAuthError(
                    "Autenticacao basica requer usuario e senha."
                )

            self._auth = httpx.BasicAuth(
                username,
                password.get_secret_value(),
            )

        self._concurrency = max(1, concurrency)
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        ssl_context: Optional[ssl.SSLContext] = None

        if not self.verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        max_conn = self._concurrency + 2
        max_keep = self._concurrency

        if _pool_settings is not None:
            if _pool_settings.pi_http_max_connections > 0:
                max_conn = _pool_settings.pi_http_max_connections
            if _pool_settings.pi_http_max_keepalive > 0:
                max_keep = _pool_settings.pi_http_max_keepalive

        limits = httpx.Limits(
            max_connections=max_conn,
            max_keepalive_connections=max_keep,
            keepalive_expiry=_pool_settings.pi_http_keepalive_expiry_seconds if _pool_settings is not None else 30.0,
        )

        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=self._auth,
            verify=self.verify_ssl if ssl_context is None else ssl_context,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
            follow_redirects=True,
            limits=limits,
            trust_env=False,
        )

    async def start(self) -> None:
        if self._client is None:
            self._client = self._build_client()
            await self._client.__aenter__()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise PiUnavailableError(
                "Cliente HTTP do PI Web API nao inicializado."
            )

        return self._client

    @property
    def is_started(self) -> bool:
        return self._client is not None

    async def _request(
        self,
        method: str,
        path: str,
        query_id: Optional[str] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue an HTTP request with retry on transient failures."""
        if not self.base_url:
            raise PiNotConfiguredError()

        semaphore = get_global_semaphore()
        async with semaphore:
            return await self._do_request(method, path, query_id=query_id, **kwargs)

    async def _do_request(
        self,
        method: str,
        path: str,
        query_id: Optional[str] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue an HTTP request with retry on transient failures, no semaphore."""
        attempts = 1

        if method.upper() == "GET":
            attempts = self.max_retries + 1

        last_error: Optional[Exception] = None
        semaphore = get_global_semaphore()

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.request(
                    method,
                    path,
                    **kwargs,
                )

                self._raise_for_status(response, path)

                return response

            except PiIntegrationError as exc:
                last_error = exc

                if attempt >= attempts or not exc.retryable:
                    raise

                backoff = min(2 ** (attempt - 1), 5)
                backoff *= random.uniform(0.5, 1.5)

                logger.warning(
                    "PI request failed (attempt %s/%s), "
                    "retrying in %ss: %s",
                    attempt,
                    attempts,
                    round(backoff, 2),
                    exc.code,
                )

                semaphore.release()
                try:
                    await asyncio.sleep(backoff)
                finally:
                    await semaphore.acquire()

            except httpx.HTTPError as exc:
                pi_exc = self._translate_request_error(exc)
                last_error = pi_exc

                if attempt >= attempts or not pi_exc.retryable:
                    raise pi_exc from exc

                backoff = min(2 ** (attempt - 1), 5)
                backoff *= random.uniform(0.5, 1.5)

                logger.warning(
                    "PI request failed (attempt %s/%s), "
                    "retrying in %ss: %s",
                    attempt,
                    attempts,
                    backoff,
                    pi_exc.code,
                )

                semaphore.release()
                try:
                    await asyncio.sleep(backoff)
                finally:
                    await semaphore.acquire()

        if last_error:
            raise last_error

        raise PiUnavailableError(
            "Falha inesperada na comunicacao com o PI Web API."
        )

    def _raise_for_status(
        self,
        response: httpx.Response,
        path: str,
    ) -> None:
        code = response.status_code

        if code in (401, 403):
            raise PiAuthError(
                f"PI Web API retornou {code} "
                "(Unauthorized ou Forbidden)."
            )

        if code == 404:
            raise PiTagNotFoundError(
                f"PI Web API retornou 404 para {path}."
            )

        if code == 400:
            raise PiInvalidResponseError(
                "PI Web API retornou 400 (Bad Request)."
            )

        if code == 429:
            raise PiRateLimitedError(
                "PI Web API retornou 429 (Too Many Requests).",
                details={"retry_after": response.headers.get("Retry-After")},
            )

        if code in (502, 503, 504):
            raise PiUnavailableError(
                f"PI Web API retornou {code}."
            )

        if 500 <= code < 600:
            raise PiInvalidResponseError(
                f"PI Web API retornou status {code}."
            )

        if not response.is_success:
            raise PiInvalidResponseError(
                f"PI Web API retornou status {code}."
            )

    def _translate_request_error(
        self,
        exc: httpx.HTTPError,
    ) -> PiIntegrationError:
        if isinstance(exc, httpx.TimeoutException):
            return PiTimeoutError()

        if isinstance(exc, httpx.ConnectError):
            message = str(exc).lower()

            if "ssl" in message or "certificate" in message:
                return PiSSLError()

            return PiUnavailableError()

        return PiUnavailableError(str(exc))

    async def _safe_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            return await self._request(method, path, **kwargs)

        except PiIntegrationError:
            raise

        except httpx.HTTPError as exc:
            raise self._translate_request_error(exc) from exc

        except Exception as exc:
            raise PiUnavailableError(str(exc)) from exc

    async def ping(self) -> None:
        response = await self._safe_request("GET", "/")

        try:
            payload = response.json()
        except ValueError as exc:
            raise PiInvalidResponseError(
                "Resposta nao-JSON do PI Web API."
            ) from exc

        if not isinstance(payload, dict):
            raise PiInvalidResponseError(
                "Resposta inesperada do PI Web API."
            )

        links = payload.get("Links")

        if not isinstance(links, dict):
            raise PiInvalidResponseError(
                "Resposta do PI Web API nao contem o objeto 'Links'."
            )

        if not links.get("Self") and not links.get("System"):
            raise PiInvalidResponseError(
                "Objeto 'Links' nao contem 'Self' ou 'System'."
            )

    def _build_path(self, name: str) -> str:
        return f"\\\\{self.data_server}\\{name.lstrip('\\\\')}"

    async def resolve_point(
        self,
        path: str,
    ) -> Optional[PiPoint]:
        normalized = path.replace("/", "\\")

        response = await self._safe_request(
            "GET",
            "/points",
            params={"path": normalized},
        )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PiInvalidResponseError(
                "Resposta nao-JSON do PI Web API."
            ) from exc

        if not isinstance(payload, dict):
            raise PiInvalidResponseError(
                "Resposta inesperada do PI Web API."
            )

        web_id = payload.get("WebId")

        if not web_id:
            return None

        return PiPoint(
            web_id=web_id,
            name=payload.get("Name", normalized),
            description=payload.get("Descriptor"),
            engineering_unit=payload.get("EngineeringUnits"),
            point_type=payload.get("PointType"),
            data_type=payload.get("PointClass") or payload.get("Type"),
            raw=payload,
        )

    def _values_endpoint(self, web_id: str) -> str:
        return f"/streams/{web_id}/recorded"

    def _interpolated_endpoint(self, web_id: str) -> str:
        return f"/streams/{web_id}/interpolated"

    def _parse_values(self, payload: Any) -> List[PiValue]:
        """Parse flat stream and nested StreamSet responses."""
        if not isinstance(payload, dict):
            raise PiInvalidResponseError(
                "Resposta inesperada do PI Web API."
            )

        results: List[PiValue] = []

        def visit(node: Any) -> None:
            if isinstance(node, list):
                for child in node:
                    visit(child)

                return

            if not isinstance(node, dict):
                return

            if "Timestamp" in node or "timestamp" in node:
                results.append(_parse_value_entry(node))
                return

            if "Items" in node:
                visit(node.get("Items"))
                return

            if "items" in node:
                visit(node.get("items"))
                return

            if "Values" in node:
                visit(node.get("Values"))
                return

            if "values" in node:
                visit(node.get("values"))

        visit(payload)

        has_known_container = any(
            key in payload
            for key in (
                "Items",
                "items",
                "Values",
                "values",
                "Timestamp",
                "timestamp",
            )
        )

        if not has_known_container:
            raise PiInvalidResponseError(
                "Resposta sem 'Items' ou valores retornada pelo PI Web API."
            )

        return results

    async def get_recorded_values(
        self,
        web_id: str,
        start_time: datetime,
        end_time: datetime,
        max_count: Optional[int] = None,
    ) -> PiRecordedValues:
        if not web_id:
            raise PiInvalidResponseError(
                "WebId vazio ao consultar valores registrados."
            )

        params: Dict[str, Any] = {
            "startTime": self._format_timestamp(start_time),
            "endTime": self._format_timestamp(end_time),
            "boundaryType": "Inside",
        }

        if max_count is not None:
            params["maxCount"] = int(max_count)

        response = await self._safe_request(
            "GET",
            self._values_endpoint(web_id),
            params=params,
        )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PiInvalidResponseError(
                "Resposta nao-JSON do PI Web API."
            ) from exc

        values = self._parse_values(payload)

        return PiRecordedValues(
            web_id=web_id,
            values=values,
        )

    async def get_interpolated_values(
        self,
        web_id: str,
        start_time: datetime,
        end_time: datetime,
        interval: str,
        max_count: Optional[int] = None,
    ) -> PiInterpolatedValues:
        if not web_id:
            raise PiInvalidResponseError(
                "WebId vazio ao consultar valores interpolados."
            )

        if not interval:
            raise PiInvalidResponseError(
                "Intervalo obrigatorio para valores interpolados."
            )

        params: Dict[str, Any] = {
            "startTime": self._format_timestamp(start_time),
            "endTime": self._format_timestamp(end_time),
            "interval": interval,
        }

        if max_count is not None:
            params["maxCount"] = int(max_count)

        response = await self._safe_request(
            "GET",
            self._interpolated_endpoint(web_id),
            params=params,
        )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PiInvalidResponseError(
                "Resposta nao-JSON do PI Web API."
            ) from exc

        values = self._parse_values(payload)

        return PiInterpolatedValues(
            web_id=web_id,
            values=values,
        )

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)

        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
