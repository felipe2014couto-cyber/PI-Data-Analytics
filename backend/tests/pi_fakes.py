"""Test doubles for the PI Web API integration."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from app.integrations.pi.errors import (
    PiAuthError,
    PiInvalidResponseError,
    PiNotConfiguredError,
    PiSSLError,
    PiTagNotFoundError,
    PiTimeoutError,
    PiUnavailableError,
    PiUnsupportedAuthError,
)
from app.integrations.pi.provider import (
    PiDataProvider,
    PiInterpolatedValues,
    PiPoint,
    PiRecordedValues,
    PiValue,
)


class FakePiDataProvider(PiDataProvider):
    """In-memory test double.

    Configurable through constructor flags and per-method responses. The
    provider records all calls so tests can assert on them. Each ``raise_*``
    field accepts either an exception instance (raised unconditionally) or a
    callable ``(path: str) -> Optional[Exception]`` to make per-path
    decisions.
    """

    def __init__(
        self,
        points: Optional[Dict[str, PiPoint]] = None,
        recorded: Optional[Dict[str, List[PiValue]]] = None,
        interpolated: Optional[Dict[str, List[PiValue]]] = None,
        raise_on_ping: Optional[object] = None,
        raise_on_resolve: Optional[object] = None,
        raise_on_recorded: Optional[object] = None,
        raise_on_interpolated: Optional[object] = None,
    ) -> None:
        self._points = points or {}
        self._recorded = recorded or {}
        self._interpolated = interpolated or {}
        self._raise_on_ping = raise_on_ping
        self._raise_on_resolve = raise_on_resolve
        self._raise_on_recorded = raise_on_recorded
        self._raise_on_interpolated = raise_on_interpolated
        self.ping_calls = 0
        self.resolve_calls: List[str] = []
        self.recorded_calls: List[tuple] = []
        self.interpolated_calls: List[tuple] = []
        # When true, ``resolve_point`` will return None for paths not in the map
        # instead of raising PiTagNotFoundError. Used to simulate "not found".
        self.treat_missing_as_not_found = True

    @staticmethod
    def _resolve_raise(spec, path: str):
        if spec is None:
            return None
        if callable(spec):
            return spec(path)
        return spec

    async def ping(self) -> None:
        self.ping_calls += 1
        exc = self._resolve_raise(self._raise_on_ping, "")
        if exc is not None:
            raise exc

    async def resolve_point(self, path: str) -> Optional[PiPoint]:
        self.resolve_calls.append(path)
        exc = self._resolve_raise(self._raise_on_resolve, path)
        if exc is not None:
            raise exc
        normalized = path.replace("/", "\\")
        if normalized in self._points:
            return self._points[normalized]
        if self.treat_missing_as_not_found:
            return None
        raise PiTagNotFoundError()

    async def get_recorded_values(
        self,
        web_id: str,
        start_time: datetime,
        end_time: datetime,
        max_count: Optional[int] = None,
    ) -> PiRecordedValues:
        self.recorded_calls.append((web_id, start_time, end_time, max_count))
        exc = self._resolve_raise(self._raise_on_recorded, web_id)
        if exc is not None:
            raise exc
        values = self._recorded.get(web_id, [])
        return PiRecordedValues(web_id=web_id, values=list(values))

    async def get_interpolated_values(
        self,
        web_id: str,
        start_time: datetime,
        end_time: datetime,
        interval: str,
        max_count: Optional[int] = None,
    ) -> PiInterpolatedValues:
        self.interpolated_calls.append((web_id, start_time, end_time, interval, max_count))
        exc = self._resolve_raise(self._raise_on_interpolated, web_id)
        if exc is not None:
            raise exc
        values = self._interpolated.get(web_id, [])
        return PiInterpolatedValues(web_id=web_id, values=list(values))


def make_value(
    timestamp: str,
    value,
    good: bool = True,
    questionable: bool = False,
    substituted: bool = False,
) -> PiValue:
    text = timestamp.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return PiValue(
        timestamp=datetime.fromisoformat(text).astimezone(timezone.utc),
        value=value,
        good=good,
        questionable=questionable,
        substituted=substituted,
    )


def configure_pi_for_tests(monkeypatch, base_url: str = "https://pi.local/piwebapi", data_server: str = "PI_DATA") -> None:
    """Force PI settings to look configured for the duration of a test."""
    from app.core import config as config_module

    settings = config_module.get_settings()
    settings.pi_web_api_base_url = base_url
    settings.pi_data_server_name = data_server
    settings.pi_web_api_auth_mode = "none"
    settings.pi_web_api_username = None
    settings.pi_web_api_password = None
    config_module.get_settings.cache_clear()


def clear_pi_settings(monkeypatch) -> None:
    from app.core import config as config_module

    settings = config_module.get_settings()
    settings.pi_web_api_base_url = None
    settings.pi_data_server_name = None
    config_module.get_settings.cache_clear()
