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
    PiIntegrationError,
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
    async def test_initial_recorded_capability_is_unknown_and_usable(self):
        state = StreamSetState()
        assert await state.is_supported() is True

    async def test_recorded_unsupported_capability_can_retry_after_ttl(self):
        state = StreamSetState()
        await state.mark_unsupported()
        assert await state.is_supported() is False
        state.checked_at_recorded = 0
        assert await state.is_supported() is True

    async def test_recorded_supported_capability(self):
        state = StreamSetState()
        await state.mark_supported()
        assert await state.is_supported() is True


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

    def test_value_wrapped_multitag_events_are_expanded_by_webid(self):
        """A timestamped series wrapper must not become one visual point."""
        payload = {
            "Items": [
                {
                    "WebId": "W2",
                    "Items": [{
                        "Timestamp": "2026-07-01T00:00:00Z",
                        "Value": {"Items": [
                            {"Timestamp": "2026-07-01T00:00:00Z", "Value": "600", "Good": True},
                            {"Timestamp": "2026-07-01T00:30:00Z", "Value": {"Name": "RUN", "Value": 1}, "Good": False},
                            {"Timestamp": "2026-07-01T01:00:00Z", "Value": True, "Good": True},
                            {"Timestamp": "2026-07-01T01:30:00Z", "Value": None, "Good": True},
                        ]},
                    }],
                },
                {
                    "WebId": "W1",
                    "Items": [{
                        "Timestamp": "2026-07-01T00:00:00Z",
                        "Value": {"Items": [
                            {"Timestamp": "2026-07-01T00:00:00Z", "Value": 10, "Good": True},
                            {"Timestamp": "2026-07-01T00:30:00Z", "Value": 11.5, "Good": True},
                        ]},
                    }],
                },
                {"WebId": "W3", "Items": []},
                {"WebId": "W4", "Errors": ["Point unavailable"]},
            ]
        }

        results = _parse_streamset_response(payload)

        assert list(results) == ["W2", "W1", "W3", "W4"]
        assert sum(len(points) for points in results.values()) == 6
        assert [point.value for point in results["W1"]] == [10, 11.5]
        assert [point.value for point in results["W2"]] == ["600", "RUN", True, None]
        assert isinstance(results["W2"][0].value, str)
        assert results["W2"][1].good is False
        assert results["W3"] == []
        assert results["W4"] == []

    def test_real_pi_flat_format_multitag(self):
        """Real PI Web API streamsets/interpolated returns flat entries per series."""
        events_w1 = [
            {"Timestamp": f"2026-07-01T{i:02d}:00:00Z", "Value": i * 10.5, "Good": True,
             "UnitsAbbreviation": "C"}
            for i in range(5)
        ]
        events_w2 = [
            {"Timestamp": f"2026-07-01T{i:02d}:00:00Z", "Value": i * 3.2, "Good": True,
             "UnitsAbbreviation": "m/s"}
            for i in range(3)
        ]
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Name": "Tag1",
                    "Path": "\\\\PI\\Tag1",
                    "UnitsAbbreviation": "C",
                    "Items": events_w1,
                    "Links": {},
                },
                {
                    "WebId": "W2",
                    "Name": "Tag2",
                    "Path": "\\\\PI\\Tag2",
                    "UnitsAbbreviation": "m/s",
                    "Items": events_w2,
                    "Links": {},
                },
            ],
            "Links": {},
        }

        results = _parse_streamset_response(payload)

        assert list(results) == ["W1", "W2"]
        assert sum(len(pts) for pts in results.values()) == 8
        assert len(results["W1"]) == 5
        assert len(results["W2"]) == 3
        assert [pt.value for pt in results["W1"]] == [i * 10.5 for i in range(5)]
        assert [pt.value for pt in results["W2"]] == [i * 3.2 for i in range(3)]
        assert all(pt.good for pt in results["W1"])
        assert all(pt.good for pt in results["W2"])

    def test_real_pi_large_series_preserves_count(self):
        """7201 events per tag must stay 7201 after parsing (real 150d scenario)."""
        from datetime import datetime, timedelta
        base = datetime(2026, 1, 1)
        events = [
            {"Timestamp": (base + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "Value": float(i), "Good": True}
            for i in range(7201)
        ]
        payload = {
            "Items": [
                {"WebId": "W1", "Items": events},
                {"WebId": "W2", "Items": events[:100]},
            ]
        }
        results = _parse_streamset_response(payload)
        assert len(results["W1"]) == 7201
        assert len(results["W2"]) == 100
        assert results["W1"][0].value == 0.0
        assert results["W1"][-1].value == 7200.0

    def test_pi_error_entry_excluded_from_points(self):
        """Entries with PI Errors are NOT process points and produce 0 points."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [{
                        "Timestamp": "2026-07-01T00:00:00Z",
                        "Value": None,
                        "Good": False,
                        "Questionable": False,
                        "Substituted": False,
                        "Errors": [{"FieldName": "Value", "Message": ["An error occurred"]}],
                        "Annotated": False,
                    }],
                },
                {
                    "WebId": "W2",
                    "Items": [{
                        "Timestamp": "2026-07-01T00:00:00Z",
                        "Value": None,
                        "Good": False,
                        "Errors": [{"FieldName": "Value", "Message": ["An error occurred"]}],
                    }],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 0
        assert len(results["W2"]) == 0
        assert "W1" in error_info
        assert "W2" in error_info
        assert len(error_info["W1"]) == 1
        assert len(error_info["W2"]) == 1

    def test_error_entry_collector_captures_timestamp(self):
        """Error collector records the timestamp of the error entry."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [{
                        "Timestamp": "2026-07-01T12:30:00Z",
                        "Value": None,
                        "Good": False,
                        "Errors": [{"FieldName": "Value", "Message": ["Error"]}],
                    }],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 0
        assert error_info["W1"][0]["timestamp"] == "2026-07-01T12:30:00Z"

    def test_mixed_good_and_error_entries(self):
        """Error entries excluded; valid entries kept."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 10.0, "Good": True},
                        {"Timestamp": "2026-07-01T00:30:00Z", "Value": None, "Good": False,
                         "Errors": [{"FieldName": "Value", "Message": ["Error"]}]},
                        {"Timestamp": "2026-07-01T01:00:00Z", "Value": 20.0, "Good": True},
                    ],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 2
        assert results["W1"][0].value == 10.0
        assert results["W1"][0].good is True
        assert results["W1"][1].value == 20.0
        assert results["W1"][1].good is True
        assert "W1" in error_info
        assert len(error_info["W1"]) == 1

    def test_mixed_valid_and_error_series(self):
        """One series has data, another has only errors: error series has 0 points."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": f"2026-07-01T0{i}:00:00Z", "Value": i * 10, "Good": True}
                        for i in range(5)
                    ],
                },
                {
                    "WebId": "W2",
                    "Items": [{
                        "Timestamp": "2026-07-01T00:00:00Z",
                        "Value": None,
                        "Good": False,
                        "Errors": [{"FieldName": "Value", "Message": ["Error"]}],
                    }],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 5
        assert len(results["W2"]) == 0
        assert all(pt.good for pt in results["W1"])
        assert "W2" in error_info

    def test_good_false_without_errors_is_valid(self):
        """Good=False without Errors is a legitimate bad point, NOT an error entry."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 10.0, "Good": True},
                        {"Timestamp": "2026-07-01T00:30:00Z", "Value": 5.0, "Good": False},
                    ],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 2
        assert results["W1"][1].value == 5.0
        assert results["W1"][1].good is False
        assert "W1" not in error_info

    def test_value_null_without_errors_follows_contract(self):
        """Value=null without Errors is a legitimate null point."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": None, "Good": True},
                    ],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 1
        assert results["W1"][0].value is None
        assert "W1" not in error_info

    def test_empty_errors_list_is_valid_point(self):
        """An empty Errors list is not an error entry."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 42, "Good": True, "Errors": []},
                    ],
                },
            ]
        }
        error_info = {}
        results = _parse_streamset_response(payload, error_collector=error_info)
        assert len(results["W1"]) == 1
        assert results["W1"][0].value == 42
        assert "W1" not in error_info

    def test_series_order_independent_of_payload_order(self):
        """WebId association uses WebId, not positional order."""
        payload = {
            "Items": [
                {"WebId": "W2", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 200, "Good": True}]},
                {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 100, "Good": True}]},
                {"WebId": "W3", "Items": []},
            ]
        }
        results = _parse_streamset_response(payload)
        assert list(results) == ["W2", "W1", "W3"]
        assert results["W1"][0].value == 100
        assert results["W2"][0].value == 200
        assert results["W3"] == []

    def test_empty_series_preserved_among_valid(self):
        """Empty series (Items=[]) is preserved as empty list."""
        payload = {
            "Items": [
                {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 1, "Good": True}]},
                {"WebId": "W2", "Items": []},
                {"WebId": "W3", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 3, "Good": True}]},
            ]
        }
        results = _parse_streamset_response(payload)
        assert len(results["W1"]) == 1
        assert results["W2"] == []
        assert len(results["W3"]) == 1

    def test_all_value_types_preserved(self):
        """Numbers, strings, booleans, None, digital states, numeric strings."""
        payload = {
            "Items": [
                {
                    "WebId": "W1",
                    "Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 42, "Good": True},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": 3.14, "Good": True},
                        {"Timestamp": "2026-07-01T00:02:00Z", "Value": "600", "Good": True},
                        {"Timestamp": "2026-07-01T00:03:00Z", "Value": "500.5", "Good": True},
                        {"Timestamp": "2026-07-01T00:04:00Z", "Value": True, "Good": True},
                        {"Timestamp": "2026-07-01T00:05:00Z", "Value": False, "Good": True},
                        {"Timestamp": "2026-07-01T00:06:00Z", "Value": None, "Good": False},
                        {"Timestamp": "2026-07-01T00:07:00Z", "Value": {"Name": "RUN", "Value": 1}, "Good": True},
                        {"Timestamp": "2026-07-01T00:08:00Z", "Value": {"Name": "STOP", "Value": 0}, "Good": False},
                    ],
                },
            ]
        }
        results = _parse_streamset_response(payload)
        vals = results["W1"]
        assert len(vals) == 9
        assert vals[0].value == 42
        assert isinstance(vals[0].value, int)
        assert vals[1].value == 3.14
        assert isinstance(vals[1].value, float)
        assert vals[2].value == "600"
        assert isinstance(vals[2].value, str)
        assert vals[3].value == "500.5"
        assert isinstance(vals[3].value, str)
        assert vals[4].value is True
        assert vals[5].value is False
        assert vals[6].value is None
        assert vals[7].value == "RUN"
        assert vals[8].value == "STOP"

    def test_no_points_between_webids(self):
        """Points from different WebIds must never mix."""
        payload = {
            "Items": [
                {"WebId": "W1", "Items": [
                    {"Timestamp": "2026-07-01T00:00:00Z", "Value": 1, "Good": True},
                    {"Timestamp": "2026-07-01T00:01:00Z", "Value": 2, "Good": True},
                ]},
                {"WebId": "W2", "Items": [
                    {"Timestamp": "2026-07-01T00:00:00Z", "Value": 100, "Good": True},
                    {"Timestamp": "2026-07-01T00:01:00Z", "Value": 200, "Good": True},
                    {"Timestamp": "2026-07-01T00:02:00Z", "Value": 300, "Good": True},
                ]},
            ]
        }
        results = _parse_streamset_response(payload)
        assert [pt.value for pt in results["W1"]] == [1, 2]
        assert [pt.value for pt in results["W2"]] == [100, 200, 300]

    def test_no_duplicate_points(self):
        """Same WebId appearing twice appends without duplication."""
        payload = {
            "Items": [
                {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": 1}]},
                {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:01:00Z", "Value": 2}]},
            ]
        }
        results = _parse_streamset_response(payload)
        assert len(results["W1"]) == 2
        assert [pt.value for pt in results["W1"]] == [1, 2]

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
                    {"WebId": "W1", "Items": [{"Timestamp": "2026-07-01T00:00:00Z", "Value": {"Items": [
                        {"Timestamp": "2026-07-01T00:00:00Z", "Value": 1},
                        {"Timestamp": "2026-07-01T00:01:00Z", "Value": 2},
                    ]}}]},
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
