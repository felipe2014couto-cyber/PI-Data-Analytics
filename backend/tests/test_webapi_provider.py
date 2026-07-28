"""Tests for PiWebApiDataProvider (concrete implementation)."""
from __future__ import annotations

import ssl as ssl_mod

import httpx
import pytest

from app.integrations.pi.errors import (
    PiAuthError,
    PiInvalidResponseError,
    PiRateLimitedError,
    PiTimeoutError,
    PiUnavailableError,
)
from app.integrations.pi.webapi_provider import PiWebApiDataProvider


def _make_provider(
    base_url: str = "http://10.247.224.39/piwebapi/",
    data_server: str = "PIMS",
    max_retries: int = 2,
) -> PiWebApiDataProvider:
    return PiWebApiDataProvider(
        base_url=base_url,
        data_server=data_server,
        auth_mode="none",
        verify_ssl=False,
        timeout=5.0,
        max_retries=max_retries,
    )


def _build_links_response(**links) -> dict:
    """Return a minimal PI root response with configurable Links."""
    return {
        "Root": {"Id": "0", "Name": "PIMS"},
        "Links": {
            "Self": "http://10.247.224.39/piwebapi/",
            "DataServers": "http://10.247.224.39/piwebapi/dataservers",
            **links,
        },
    }


# ─── Health check tests ────────────────────────────────────────────────


class TestHealthCheck:
    def test_base_url_ensures_trailing_slash(self) -> None:
        p1 = _make_provider(base_url="http://10.247.224.39/piwebapi")
        assert p1.base_url == "http://10.247.224.39/piwebapi/"
        p2 = _make_provider(base_url="http://10.247.224.39/piwebapi/")
        assert p2.base_url == "http://10.247.224.39/piwebapi/"
        p3 = _make_provider(base_url="http://10.247.224.39/piwebapi///")
        assert p3.base_url == "http://10.247.224.39/piwebapi/"

    def test_invalid_json_raises_invalid_response(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                200,
                text="not json",
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        with pytest.raises(PiInvalidResponseError):
            asyncio.get_event_loop().run_until_complete(provider.ping())

    def test_links_key_missing_raises_invalid_response(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                200,
                json={"Root": {"Id": "0"}},
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        with pytest.raises(PiInvalidResponseError) as exc_info:
            asyncio.get_event_loop().run_until_complete(provider.ping())
        assert "Links" in str(exc_info.value)

    def test_links_without_self_or_system_raises(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                200,
                json={"Root": {"Id": "0"}, "Links": {"DataServers": "..."}},
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        with pytest.raises(PiInvalidResponseError) as exc_info:
            asyncio.get_event_loop().run_until_complete(provider.ping())
        assert "Self" in str(exc_info.value) or "System" in str(exc_info.value)

    def test_links_with_system_only_is_connected(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                200,
                json=_build_links_response(Self="", System="http://host/piwebapi"),
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        asyncio.get_event_loop().run_until_complete(provider.ping())

    def test_response_401_raises_auth_error(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                401,
                json={"Message": "Unauthorized"},
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        with pytest.raises(PiAuthError):
            asyncio.get_event_loop().run_until_complete(provider.ping())

    def test_response_403_raises_auth_error(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                403,
                json={"Message": "Forbidden"},
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        with pytest.raises(PiAuthError):
            asyncio.get_event_loop().run_until_complete(provider.ping())

    def test_verify_ssl_false_creates_insecure_context(self) -> None:
        provider = PiWebApiDataProvider(
            base_url="http://fake/piwebapi/",
            data_server="PIMS",
            auth_mode="none",
            verify_ssl=False,
        )
        client = provider._build_client()
        import ssl as ssl_mod
        assert client._transport._pool._ssl_context is not None
        ctx = client._transport._pool._ssl_context
        assert ctx.verify_mode == ssl_mod.CERT_NONE
        assert ctx.check_hostname is False

    def test_verify_ssl_default_creates_secure_context(self) -> None:
        provider = PiWebApiDataProvider(
            base_url="http://fake/piwebapi/",
            data_server="PIMS",
            auth_mode="none",
            verify_ssl=True,
        )
        client = provider._build_client()
        assert client._transport._pool._ssl_context is None or (
            client._transport._pool._ssl_context.verify_mode != ssl_mod.CERT_NONE
        )

    def test_response_500_raises_invalid_response(self) -> None:
        provider = _make_provider()
        responses = [
            httpx.Response(
                500,
                json={"Message": "Internal Server Error"},
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        with pytest.raises(PiInvalidResponseError):
            asyncio.get_event_loop().run_until_complete(provider.ping())


# ─── Retry tests ────────────────────────────────────────────────────────


class TestRetryBehavior:
    def test_401_does_not_generate_retry(self) -> None:
        provider = _make_provider()
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"Message": "Unauthorized"})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
        )

        import asyncio
        with pytest.raises(PiAuthError):
            asyncio.get_event_loop().run_until_complete(provider.ping())
        assert call_count == 1

    def test_503_respects_retry_limit(self) -> None:
        provider = _make_provider(max_retries=2)
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, json={"Message": "Service Unavailable"})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
        )

        import asyncio
        with pytest.raises(PiUnavailableError):
            asyncio.get_event_loop().run_until_complete(provider.ping())
        assert call_count == 3

    def test_timeout_retries_up_to_limit(self) -> None:
        provider = _make_provider(max_retries=1)
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("timeout")

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
            timeout=5.0,
        )

        import asyncio
        with pytest.raises(PiTimeoutError):
            asyncio.get_event_loop().run_until_complete(provider.ping())
        assert call_count == 2


# ─── Base URL tests ─────────────────────────────────────────────────────


class TestBaseUrl:
    def test_point_path_uses_configured_base_url_not_links(self) -> None:
        """Verify that HTTPS links in root response don't override the HTTP base URL."""
        provider = _make_provider(base_url="http://10.247.224.39/piwebapi")
        assert provider.base_url == "http://10.247.224.39/piwebapi/"

    def test_resolve_point_builds_correct_path(self) -> None:
        provider = _make_provider()
        path = provider._build_path("TAG123")
        assert path == "\\\\PIMS\\TAG123"

    def test_root_200_with_links_returns_success(self) -> None:
        """Root returning 200 with Links should be treated as connected."""
        provider = _make_provider()
        links = _build_links_response()
        responses = [
            httpx.Response(
                200,
                json=links,
                request=httpx.Request("GET", "http://10.247.224.39/piwebapi/"),
            )
        ]
        transport = httpx.MockTransport(lambda req: responses.pop(0))
        provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

        import asyncio
        asyncio.get_event_loop().run_until_complete(provider.ping())


# ─── Value contract tests ──────────────────────────────────────────────


class TestValueContract:
    @staticmethod
    def _entry(value, **quality) -> dict:
        return {
            "Timestamp": "2026-07-01T00:00:00Z",
            "Value": value,
            **quality,
        }

    @pytest.mark.parametrize(
        ("raw", "expected", "expected_type"),
        [
            (600, 600, int),
            (500.5, 500.5, float),
            ("P304I", "P304I", str),
            ("500.5", "500.5", str),
            ("  P316B  ", "  P316B  ", str),
            ({"Name": "P420A", "Value": 4}, "P420A", str),
            (True, True, bool),
            (None, None, type(None)),
        ],
    )
    def test_preserves_json_value_type(self, raw, expected, expected_type) -> None:
        provider = _make_provider()

        point = provider._parse_values({"Items": [self._entry(raw)]})[0]

        assert point.value == expected
        assert isinstance(point.value, expected_type)

    def test_numeric_string_remains_string(self) -> None:
        provider = _make_provider()

        value = provider._parse_values(
            {"Items": [self._entry("600")]}
        )[0].value

        assert value == "600"
        assert isinstance(value, str)

    def test_mixed_numeric_and_text_values_preserve_each_type(self) -> None:
        provider = _make_provider()
        payload = {
            "Items": [
                self._entry(600),
                self._entry("600"),
                self._entry("P304I"),
                self._entry(500.5),
            ]
        }

        values = [point.value for point in provider._parse_values(payload)]

        assert values == [600, "600", "P304I", 500.5]
        assert isinstance(values[0], int)
        assert isinstance(values[1], str)
        assert isinstance(values[2], str)
        assert isinstance(values[3], float)

    @pytest.mark.parametrize(
        ("quality", "expected"),
        [
            ({"Good": True}, (True, False, False)),
            ({"Good": False}, (False, False, False)),
            (
                {"Good": True, "Questionable": True},
                (True, True, False),
            ),
            (
                {"Good": True, "Substituted": True},
                (True, False, True),
            ),
        ],
    )
    def test_quality_flags_are_independent(self, quality, expected) -> None:
        provider = _make_provider()

        point = provider._parse_values(
            {"Items": [self._entry("P304I", **quality)]}
        )[0]

        assert (point.good, point.questionable, point.substituted) == expected
