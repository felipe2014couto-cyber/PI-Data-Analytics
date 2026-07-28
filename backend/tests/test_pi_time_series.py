"""Tests for the time series endpoint."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pi.errors import PiTagNotFoundError, PiUnavailableError
from app.integrations.pi.provider import PiPoint, PiValue
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.section import Section
from app.models.variable_type import VariableType
from app.schemas.pi import TimeSeriesPoint
from tests.pi_fakes import make_value


def _configure_pi() -> None:
    settings = get_settings()
    settings.pi_web_api_base_url = "https://pi.local/piwebapi"
    settings.pi_data_server_name = "PI_DATA"
    settings.pi_web_api_auth_mode = "none"
    settings.pi_query_max_tags = 10
    settings.pi_query_max_points_per_tag = 20000


def _make_tag(
    db_session: Session,
    *,
    code: str,
    pi_web_id: str | None = None,
) -> PiTag:
    equipment = Equipment(code=f"EQ-{code}", name=f"Equipment {code}")
    db_session.add(equipment)
    db_session.flush()
    section = Section(equipment_id=equipment.id, code="S1", name="Section 1")
    db_session.add(section)
    variable_type = VariableType(code=f"VT-{code}", name="Temperatura")
    db_session.add(variable_type)
    db_session.flush()
    tag = PiTag(
        equipment_id=equipment.id,
        section_id=section.id,
        variable_type_id=variable_type.id,
        pi_server="PI_DATA",
        pi_tag_name=code,
        display_name=f"Display {code}",
        engineering_unit="C",
        data_type=PiTagDataType.NUMERIC,
        active=True,
        pi_web_id=pi_web_id,
    )
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)
    return tag


def test_time_series_point_serialization_preserves_numeric_string() -> None:
    point = TimeSeriesPoint(
        timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
        value="600",
    )

    value = point.model_dump(mode="json")["value"]
    assert value == "600"
    assert isinstance(value, str)


def test_time_series_recorded(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.TEMP", pi_web_id="W1")
    point = PiPoint(web_id="W1", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W1": [
            make_value("2026-07-01T00:00:00Z", 82.5),
            make_value("2026-07-01T00:00:30Z", 83.1, good=False, questionable=True),
        ]
    }

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "recorded"
    assert body["start_time"].startswith("2026-07-01T00:00:00")
    assert body["end_time"].startswith("2026-07-01T01:00:00")
    assert len(body["series"]) == 1
    series = body["series"][0]
    assert series["tag_id"] == tag.id
    assert series["tag_name"] == tag.pi_tag_name
    assert series["display_name"] == tag.display_name
    assert series["unit"] == "C"
    assert len(series["points"]) == 2
    assert series["points"][0]["value"] == 82.5
    assert series["points"][1]["good"] is False
    assert series["points"][1]["questionable"] is True


def test_time_series_interpolated(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.PRESS", pi_web_id="W2")
    point = PiPoint(web_id="W2", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]
    client.fake_provider._interpolated = {  # type: ignore[attr-defined]
        "W2": [
            make_value("2026-07-01T00:00:00Z", 1.0),
            make_value("2026-07-01T00:01:00Z", 1.5),
        ]
    }

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "interpolated",
            "interval": "1m",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "interpolated"
    assert len(body["series"]) == 1
    assert len(body["series"][0]["points"]) == 2


def test_time_series_interval_required_for_interpolated(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.NOINT", pi_web_id="W3")
    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "interpolated",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TIME_RANGE_INVALID"


def test_time_series_invalid_range(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.RANGE", pi_web_id="W4")
    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T02:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TIME_RANGE_INVALID"


def test_time_series_limit_exceeded(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    get_settings().pi_query_max_tags = 1
    tag = _make_tag(db_session, code="RB3.LIMIT1", pi_web_id="W5")
    tag2 = _make_tag(db_session, code="RB3.LIMIT2", pi_web_id="W6")
    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id, tag2.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PI_QUERY_LIMIT_EXCEEDED"


def test_time_series_blocked_by_inactive_tag(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.OFF", pi_web_id="W7")
    db_session.query(PiTag).filter(PiTag.id == tag.id).update({"active": False})
    db_session.commit()

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TAG_INACTIVE"


def test_time_series_unknown_local_tag(client: TestClient) -> None:
    _configure_pi()
    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [9999],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_time_series_auto_resolve_when_no_webid(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.NOWEBID", pi_web_id=None)
    point = PiPoint(web_id="W-NEW", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]
    client.fake_provider._recorded = {"W-NEW": [make_value("2026-07-01T00:00:00Z", 7.0)]}  # type: ignore[attr-defined]

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    refreshed = db_session.get(PiTag, tag.id)
    assert refreshed is not None
    assert refreshed.pi_web_id == "W-NEW"


def test_time_series_re_resolve_obsolete_webid(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.STALE", pi_web_id="W-OLD")
    new_point = PiPoint(web_id="W-NEW", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": new_point}  # type: ignore[attr-defined]
    # First call with old WebId returns PiTagNotFoundError; second call returns data.
    seen_webids: list[str] = []

    async def _raise_once_then_return(web_id, start_time, end_time, max_count=None):
        seen_webids.append(web_id)
        from app.integrations.pi.provider import PiRecordedValues

        if web_id == "W-OLD":
            raise PiTagNotFoundError()
        return PiRecordedValues(web_id=web_id, values=[make_value("2026-07-01T00:00:00Z", 5.0)])

    client.fake_provider.get_recorded_values = _raise_once_then_return  # type: ignore[assignment]

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["series"][0]["points"][0]["value"] == 5.0
    assert "W-OLD" in seen_webids
    assert "W-NEW" in seen_webids
    db_session.expire_all()
    refreshed = db_session.get(PiTag, tag.id)
    assert refreshed is not None
    assert refreshed.pi_web_id == "W-NEW"


def test_time_series_does_not_persist_values(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.NOPERSIST", pi_web_id="W-PERSIST")
    point = PiPoint(web_id="W-PERSIST", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-PERSIST": [
            make_value("2026-07-01T00:00:00Z", 10.0),
            make_value("2026-07-01T00:00:30Z", 20.0),
        ]
    }

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200

    # Confirm no historical value table exists.
    from sqlalchemy import inspect

    inspector = inspect(db_session.get_bind())
    tables = inspector.get_table_names()
    assert not any("tag_value" in t for t in tables)
    assert not any("time_series" in t for t in tables)
    assert not any("historical" in t for t in tables)
    # Only catalog tables.
    assert {"equipments", "sections", "variable_types", "pi_tags"}.issubset(set(tables))


def test_time_series_error_in_one_tag_does_not_block_others(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    good = _make_tag(db_session, code="RB3.GOOD", pi_web_id="W-GOOD")
    bad = _make_tag(db_session, code="RB3.BAD", pi_web_id="W-BAD")
    point = PiPoint(web_id="W-GOOD", name=good.pi_tag_name)
    client.fake_provider._points = {f"\\\\{good.pi_server}\\{good.pi_tag_name}": point}  # type: ignore[attr-defined]
    client.fake_provider._recorded = {"W-GOOD": [make_value("2026-07-01T00:00:00Z", 1.0)]}  # type: ignore[attr-defined]

    from app.integrations.pi.provider import PiRecordedValues

    async def _raise_bad(web_id, start_time, end_time, max_count=None):
        if web_id == "W-BAD":
            raise PiUnavailableError("PI indisponivel")
        return PiRecordedValues(web_id=web_id, values=client.fake_provider._recorded[web_id])  # type: ignore[attr-defined]

    client.fake_provider.get_recorded_values = _raise_bad  # type: ignore[assignment]

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [good.id, bad.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["series"]) == 1
    assert body["series"][0]["tag_id"] == good.id
    assert len(body["errors"]) == 1
    assert body["errors"][0]["tag_id"] == bad.id
    assert body["errors"][0]["code"] == "PI_UNAVAILABLE"


def test_time_series_quality_flags_normalized(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.QUAL", pi_web_id="W-QUAL")
    point = PiPoint(web_id="W-QUAL", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]

    raw = [
        PiValue(timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc), value=1.0, good=True, questionable=False, substituted=False),
        PiValue(timestamp=datetime(2026, 7, 1, 0, 1, tzinfo=timezone.utc), value=2.0, good=False, questionable=False, substituted=True),
        PiValue(timestamp=datetime(2026, 7, 1, 0, 2, tzinfo=timezone.utc), value=3.0, good=False, questionable=True, substituted=False),
    ]
    from app.integrations.pi.provider import PiRecordedValues

    async def _return_raw(web_id, start_time, end_time, max_count=None):
        return PiRecordedValues(web_id=web_id, values=raw)

    client.fake_provider.get_recorded_values = _return_raw  # type: ignore[assignment]

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    points = body["series"][0]["points"]
    assert points[0]["good"] is True
    assert points[1]["good"] is False
    assert points[1]["substituted"] is True
    assert points[2]["questionable"] is True
    assert points[2]["good"] is False


def test_time_series_preserves_value_types(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.MIX", pi_web_id="W-MIX")
    point = PiPoint(web_id="W-MIX", name=tag.pi_tag_name)
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]

    raw = [
        PiValue(timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc), value=1.5),
        PiValue(timestamp=datetime(2026, 7, 1, 0, 1, tzinfo=timezone.utc), value="RUN"),
        PiValue(timestamp=datetime(2026, 7, 1, 0, 2, tzinfo=timezone.utc), value="600"),
        PiValue(timestamp=datetime(2026, 7, 1, 0, 3, tzinfo=timezone.utc), value=None),
    ]
    from app.integrations.pi.provider import PiRecordedValues

    async def _return_raw(web_id, start_time, end_time, max_count=None):
        return PiRecordedValues(web_id=web_id, values=raw)

    client.fake_provider.get_recorded_values = _return_raw  # type: ignore[assignment]

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    points = response.json()["series"][0]["points"]
    assert points[0]["value"] == 1.5
    assert points[1]["value"] == "RUN"
    value = points[2]["value"]
    assert value == "600"
    assert isinstance(value, str)
    assert points[3]["value"] is None
