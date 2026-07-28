"""Tests for StreamSet batch client."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
import pytest
from urllib.parse import parse_qs, urlparse

from app.integrations.pi.errors import (
    PiAuthError,
    PiInvalidResponseError,
    PiRateLimitedError,
    PiUnavailableError,
)
from app.integrations.pi.provider import PiValue
from app.integrations.pi.webapi_provider import PiWebApiDataProvider
from app.services.streamset_client import (
    StreamSetCapability,
    StreamSetState,
    _parse_streamset_response,
    build_web_ids_version,
    detect_missing_series,
    fetch_streamset_batch,
    build_recorded_resource,
    fetch_recorded_streamsets_batch,
    group_web_ids_for_recorded,
)


def _utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


def _make_provider(base_url="http://pi.local/piwebapi/"):
    return PiWebApiDataProvider(
        base_url=base_url,
        data_server="PIMS",
        auth_mode="none",
        verify_ssl=False,
        timeout=5.0,
        max_retries=0,
    )


@pytest.mark.asyncio
class TestStreamSetState:
    async def test_initial_is_unknown(self):
        s = StreamSetState()
        assert await s.is_supported("recorded") is True
        assert await s.is_supported("interpolated") is True

    async def test_unsupported_returns_false(self):
        s = StreamSetState()
        await s.mark_unsupported("interpolated")
        assert await s.is_supported("interpolated") is False

    async def test_supported_returns_true(self):
        s = StreamSetState()
        await s.mark_supported("recorded")
        assert await s.is_supported("recorded") is True

    async def test_expired_retry(self):
        s = StreamSetState()
        await s.mark_unsupported("interpolated")
        s.checked_at_interpolated = 0
        assert await s.is_supported("interpolated") is True


class TestParseStreamSet:
    def test_parse_simple(self):
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 100, "Good": True},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": 200, "Good": True},
                    ],
                },
                {
                    "WebId": "W2",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 300, "Good": True},
                    ],
                },
            ]
        }
        results = _parse_streamset_response(payload)
        assert "W1" in results
        assert "W2" in results
        assert len(results["W1"]) == 2
        assert len(results["W2"]) == 1
        assert results["W1"][0].value == 100

    def test_out_of_order_webids(self):
        payload = {
            "Items": [
                {"WebId": "W2", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 200, "Good": True}]},
                {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 100, "Good": True}]},
            ]
        }
        results = _parse_streamset_response(payload)
        assert results["W1"][0].value == 100
        assert results["W2"][0].value == 200

    def test_string_values_preserved(self):
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": "600", "Good": True},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": "500.5", "Good": True},
                    ],
                },
            ]
        }
        results = _parse_streamset_response(payload)
        assert results["W1"][0].value == "600"
        assert isinstance(results["W1"][0].value, str)
        assert results["W1"][1].value == "500.5"
        assert isinstance(results["W1"][1].value, str)

    def test_quality_preserved(self):
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 1, "Good": True, "Questionable": False, "Substituted": False},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": 2, "Good": False, "Questionable": True, "Substituted": False},
                    ],
                },
            ]
        }
        results = _parse_streamset_response(payload)
        assert results["W1"][0].good is True
        assert results["W1"][1].good is False
        assert results["W1"][1].questionable is True

    def test_units_preserved(self):
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 100, "Good": True, "UnitsAbbreviation": "C"},
                    ],
                },
            ]
        }
        results = _parse_streamset_response(payload)
        assert results["W1"][0].units == "C"

    def test_boolean_and_none_preserved(self):
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": True, "Good": True},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": None, "Good": False},
                    ],
                },
            ]
        }
        results = _parse_streamset_response(payload)
        assert results["W1"][0].value is True
        assert results["W1"][1].value is None

    def test_nested_multitag_containers_preserve_all_points_and_types(self):
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Name": "Numeric",
                    "Items": [{
                        "Timestamp": "2026-07-01T00:00:00Z",
                        "Items": [
                            {"Timestamp": "2026-07-01T00:00:00Z", "Value": 1, "Good": True},
                            {"Timestamp": "2026-07-01T00:01:00Z", "Value": 2.5, "Good": False},
                            {"Timestamp": "2026-07-01T00:02:00Z", "Value": 3, "Good": True},
                        ],
                    }],
                },
                {
                    "WebId": "W2",
                    "Name": "States",
                    "Items": [{"Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": "600", "Good": True},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": {"Name": "RUN", "Value": 1}, "Good": True},
                        {"Timestamp": "2026-07-01T00:02:00Z", "Value": True, "Good": True},
                        {"Timestamp": "2026-07-01T00:03:00Z", "Value": None, "Good": True},
                    ]}],
                },
                {
                    "WebId": "W3",
                    "Name": "Different count",
                    "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 30, "Good": True}],
                },
                {"WebId": "W4", "Name": "Empty", "Items": []},
            ]
        }

        results = _parse_streamset_response(payload)

        assert {web_id: len(points) for web_id, points in results.items()} == {
            "W1": 3, "W2": 4, "W3": 1, "W4": 0,
        }
        assert sum(len(points) for points in results.values()) == 8
        assert [point.value for point in results["W1"]] == [1, 2.5, 3]
        assert results["W1"][1].good is False
        assert results["W2"][0].value == "600"
        assert isinstance(results["W2"][0].value, str)
        assert [point.value for point in results["W2"][1:]] == ["RUN", True, None]
        assert results["W3"][0].value == 30

    def test_repeated_series_segments_are_appended_in_order(self):
        payload = {"Items": [
            {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 1}]},
            {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:01:00Z", "Value": 2}]},
        ]}

        results = _parse_streamset_response(payload)

        assert [point.value for point in results["W1"]] == [1, 2]

    def test_missing_series(self):
        payload = {
            "Items": [
                {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 1, "Good": True}]},
            ]
        }
        results = _parse_streamset_response(payload)
        missing = detect_missing_series(["W1", "W2"], results)
        assert "W2" in missing
        assert "W1" not in missing


class TestBuildWebIdsVersion:
    def test_single(self):
        assert build_web_ids_version(["W1"]) == "W1"

    def test_multiple(self):
        assert build_web_ids_version(["W1", "W2"]) == "W1|W2"

    def test_with_none(self):
        assert build_web_ids_version(["W1", None]) == "W1|"


class TestRecordedBatchResources:
    def test_repeated_webids_and_inside_boundary(self):
        resource = build_recorded_resource(
            "https://pi.local/piwebapi", ["W1", "W2"],
            _utc(2026, 7, 1), _utc(2026, 7, 2), 10000,
        )
        query = parse_qs(urlparse(resource).query)
        assert query["webId"] == ["W1", "W2"]
        assert query["boundaryType"] == ["Inside"]
        assert query["maxCount"] == ["10000"]

    def test_eleven_webids_split_by_configuration(self):
        groups = group_web_ids_for_recorded(
            "https://pi.local/piwebapi", [f"W{i}" for i in range(11)],
            _utc(2026, 7, 1), _utc(2026, 7, 2), 10000,
        )
        assert [len(group) for group in groups] == [10, 1]


@pytest.mark.asyncio
class TestRecordedBatchExecution:
    async def test_multiple_streamsets_share_one_batch_and_map_by_webid(self):
        provider = _make_provider()
        seen = []

        async def handler(request):
            body = __import__("json").loads(request.content)
            seen.append(body)
            response = {}
            for key, entry in body.items():
                ids = parse_qs(urlparse(entry["Resource"]).query).get("webId", [])
                response[key] = {
                    "Status": 200,
                    "Content": {"Items": [
                        {"WebId": wid, "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": wid}]}
                        for wid in reversed(ids)
                    ]},
                }
            return httpx.Response(207, json=response)

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        result = await fetch_recorded_streamsets_batch(
            [f"W{i}" for i in range(11)], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
        )
        assert len(seen) == 1
        assert len(seen[0]) == 2
        assert result.values["W0"][0].value == "W0"
        assert result.values["W10"][0].value == "W10"
        assert result.metrics.batch_subrequest_count == 2

    async def test_three_recorded_series_expand_nested_points_without_mixing(self):
        provider = _make_provider()

        async def handler(request):
            body = __import__("json").loads(request.content)
            return httpx.Response(207, json={key: {
                "Status": 200,
                "Content": {"Items": [
                    {"WebId": "W1", "Items": [{"Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 1},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": 2},
                    ]}]},
                    {"WebId": "W2", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": "RUN"}]},
                    {"WebId": "W3", "Items": []},
                ]},
            } for key in body})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        result = await fetch_recorded_streamsets_batch(
            ["W1", "W2", "W3"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
        )

        assert [point.value for point in result.values["W1"]] == [1, 2]
        assert [point.value for point in result.values["W2"]] == ["RUN"]
        assert result.values["W3"] == []
        assert result.metrics.pi_points_received == 3

    async def test_missing_series_falls_back_only_for_missing_webid(self):
        provider = _make_provider()
        resources = []

        async def handler(request):
            body = __import__("json").loads(request.content)
            response = {}
            for key, entry in body.items():
                resource = entry["Resource"]
                resources.append(resource)
                if "/streamsets/recorded" in resource:
                    response[key] = {"Status": 200, "Content": {"Items": [
                        {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 1}]}
                    ]}}
                else:
                    response[key] = {"Status": 200, "Content": {"Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": "600", "Good": True}
                    ]}}
            return httpx.Response(207, json=response)

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        result = await fetch_recorded_streamsets_batch(
            ["W1", "W2"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
        )
        assert sum("/streams/W2/recorded" in resource for resource in resources) == 1
        assert not any("/streams/W1/recorded" in resource for resource in resources)
        assert result.values["W2"][0].value == "600"
        assert isinstance(result.values["W2"][0].value, str)
        assert result.metrics.individual_fallback_requests == 1

    async def test_unsupported_streamset_uses_streams_recorded_batch(self):
        provider = _make_provider()
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            body = __import__("json").loads(request.content)
            response = {}
            for key, entry in body.items():
                if calls == 1:
                    response[key] = {"Status": 404, "Content": {}}
                else:
                    assert "/streams/" in entry["Resource"]
                    response[key] = {"Status": 200, "Content": {"Items": []}}
            return httpx.Response(207, json=response)

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        from app.services.streamset_client import _CAPABILITY
        _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
        result = await fetch_recorded_streamsets_batch(
            ["W1", "W2"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
        )
        assert calls == 2
        assert result.metrics.strategy == "batch-recorded-fallback"
        assert result.metrics.individual_fallback_requests == 2
        _CAPABILITY.recorded = StreamSetCapability.UNKNOWN

    async def test_401_subresponse_does_not_fallback(self):
        provider = _make_provider()

        async def handler(request):
            body = __import__("json").loads(request.content)
            return httpx.Response(207, json={key: {"Status": 401, "Content": {}} for key in body})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        from app.services.streamset_client import _CAPABILITY
        _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
        result = await fetch_recorded_streamsets_batch(
            ["W1"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
        )
        assert "W1" in result.errors
        assert result.metrics.individual_fallback_requests == 0

    async def test_dense_series_isolated_in_adaptive_wave(self):
        provider = _make_provider()
        requested_groups = []
        from app.services import streamset_client as module
        old_max = module.settings.pi_recorded_window_max_points
        module.settings.pi_recorded_window_max_points = 2

        async def handler(request):
            body = __import__("json").loads(request.content)
            response = {}
            for key, entry in body.items():
                ids = parse_qs(urlparse(entry["Resource"]).query).get("webId", [])
                requested_groups.append(ids)
                items = []
                for wid in ids:
                    count = 2 if wid == "DENSE" and len(requested_groups) == 1 else 1
                    items.append({"WebId": wid, "Items": [
                        {"Timestamp": f"2026-07-01T00:00:0{i}Z", "Value": i}
                        for i in range(count)
                    ]})
                response[key] = {"Status": 200, "Content": {"Items": items}}
            return httpx.Response(207, json=response)

        try:
            provider._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url=provider.base_url,
            )
            from app.services.streamset_client import _CAPABILITY
            _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
            result = await fetch_recorded_streamsets_batch(
                ["DENSE", "DONE"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
            )
            assert requested_groups[0] == ["DENSE", "DONE"]
            assert all(group == ["DENSE"] for group in requested_groups[1:])
            assert result.metrics.window_split_count == 1
        finally:
            module.settings.pi_recorded_window_max_points = old_max

    async def test_minimum_saturated_window_is_partial_and_truncated(self):
        provider = _make_provider()
        from app.services import streamset_client as module
        old_max = module.settings.pi_recorded_window_max_points
        old_min = module.settings.pi_recorded_window_min_seconds
        module.settings.pi_recorded_window_max_points = 2
        module.settings.pi_recorded_window_min_seconds = 60

        async def handler(request):
            body = __import__("json").loads(request.content)
            response = {}
            for key in body:
                response[key] = {"Status": 200, "Content": {"Items": [{
                    "WebId": "W1", "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 1},
                        {"Timestamp": "2026-07-01T00:00:01Z", "Value": 2},
                    ],
                }]}}
            return httpx.Response(207, json=response)

        try:
            provider._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url=provider.base_url,
            )
            from app.services.streamset_client import _CAPABILITY
            _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
            result = await fetch_recorded_streamsets_batch(
                ["W1"], _utc(2026, 7, 1), _utc(2026, 7, 1, 0, 2), provider,
            )
            assert result.metrics.partial is True
            assert result.metrics.truncated is True
            assert result.truncated_web_ids == {"W1"}
        finally:
            module.settings.pi_recorded_window_max_points = old_max
            module.settings.pi_recorded_window_min_seconds = old_min

    async def test_429_subresponse_retries_only_rate_limited_entry(self):
        provider = _make_provider()
        calls = 0
        keys_per_call = []

        async def handler(request):
            nonlocal calls
            calls += 1
            body = __import__("json").loads(request.content)
            keys_per_call.append(list(body))
            response = {}
            for key in body:
                if calls == 1:
                    response[key] = {"Status": 429, "Headers": {"Retry-After": "0"}, "Content": {}}
                else:
                    response[key] = {"Status": 200, "Content": {"Items": [
                        {"WebId": "W1", "Items": []}
                    ]}}
            return httpx.Response(207, json=response)

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        from app.services.streamset_client import _CAPABILITY
        _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
        result = await fetch_recorded_streamsets_batch(
            ["W1"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
        )
        assert calls == 2
        assert keys_per_call[1] == keys_per_call[0]
        assert result.metrics.rate_limit_count == 1
        assert result.metrics.retry_count == 1

    async def test_cancellation_interrupts_retry_after_before_new_http_call(self):
        provider = _make_provider()
        calls = 0
        cancelled = False

        async def handler(request):
            nonlocal calls, cancelled
            calls += 1
            cancelled = True
            body = __import__("json").loads(request.content)
            return httpx.Response(207, json={
                key: {"Status": 429, "Headers": {"Retry-After": "10"}, "Content": {}}
                for key in body
            })

        async def check_cancelled():
            if cancelled:
                raise asyncio.CancelledError()

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        from app.services.streamset_client import _CAPABILITY
        _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
        with pytest.raises(asyncio.CancelledError):
            await fetch_recorded_streamsets_batch(
                ["W1"], _utc(2026, 7, 1), _utc(2026, 7, 2), provider,
                cancel_check=check_cancelled,
            )
        assert calls == 1


@pytest.mark.asyncio
class TestStreamSetFallback:
    async def test_three_interpolated_series_expand_nested_points_without_mixing(self):
        provider = _make_provider()

        def handler(request):
            assert request.url.params.get_list("webId") == ["W1", "W2", "W3"]
            assert request.url.params["interval"] == "1m"
            return httpx.Response(200, json={"Items": [
                {"WebId": "W1", "Items": [{"Items": [
                    {"Timestamp": "2026-07-01T00:00:00Z", "Value": 10},
                    {"Timestamp": "2026-07-01T00:01:00Z", "Value": 11},
                ]}]},
                {"WebId": "W2", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": "600"}]},
                {"WebId": "W3", "Items": []},
            ]})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=provider.base_url,
        )
        results, req_count, used = await fetch_streamset_batch(
            ["W1", "W2", "W3"], _utc(2026, 7, 1), _utc(2026, 7, 2),
            "interpolated", "1m", 100, provider,
        )

        assert used is True
        assert req_count == 1
        assert [point.value for point in results["W1"]] == [10, 11]
        assert [point.value for point in results["W2"]] == ["600"]
        assert isinstance(results["W2"][0].value, str)
        assert results["W3"] == []

    async def test_401_does_not_fallback(self):
        provider = _make_provider()
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"Message": "Unauthorized"})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
        )

        with pytest.raises(PiAuthError):
            await fetch_streamset_batch(
                ["W1", "W2"],
                _utc(2026, 7, 1),
                _utc(2026, 7, 2),
                "interpolated",
                "1m",
                100,
                provider,
            )
        assert call_count == 1

    async def test_429_does_not_fan_out(self):
        provider = _make_provider()
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(429, json={"Message": "Too Many Requests"})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
        )

        with pytest.raises(PiRateLimitedError):
            await fetch_streamset_batch(
                ["W1", "W2"],
                _utc(2026, 7, 1),
                _utc(2026, 7, 2),
                "interpolated",
                "1m",
                100,
                provider,
            )
        assert call_count == 1

    async def test_404_falls_back(self):
        provider = _make_provider()
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(404, json={"Message": "Not Found"})

        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
        )

        results, req_count, used = await fetch_streamset_batch(
            ["W1"],
            _utc(2026, 7, 1),
            _utc(2026, 7, 2),
            "interpolated",
            "1m",
            100,
            provider,
        )
        assert call_count == 1

    async def test_unsupported_marked(self):
        from app.services.streamset_client import _CAPABILITY

        _CAPABILITY.recorded = StreamSetCapability.UNSUPPORTED
        _CAPABILITY.checked_at_recorded = time.monotonic()

        try:
            provider = _make_provider()
            call_count = 0

            def handler(request):
                nonlocal call_count
                call_count += 1
                return httpx.Response(200, json={"Items": []})

            transport = httpx.MockTransport(handler)
            provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)

            results, req_count, used = await fetch_streamset_batch(
                ["W1"],
                _utc(2026, 7, 1),
                _utc(2026, 7, 2),
                "recorded",
                None,
                100,
                provider,
            )
            assert used is False
            assert req_count == 0
            assert call_count == 0
        finally:
            _CAPABILITY.recorded = StreamSetCapability.UNKNOWN
            _CAPABILITY.checked_at_recorded = 0.0
