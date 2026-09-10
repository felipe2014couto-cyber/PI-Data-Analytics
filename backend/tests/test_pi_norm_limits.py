"""Tests for the norm limits endpoint."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pi.errors import PiTagNotFoundError
from app.integrations.pi.provider import PiPoint, PiValue
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.section import Section
from app.models.variable_type import VariableType
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
    lower_limit_tag: str | None = None,
    upper_limit_tag: str | None = None,
    active: bool = True,
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
        lower_limit_tag=lower_limit_tag,
        upper_limit_tag=upper_limit_tag,
        display_name=f"Display {code}",
        engineering_unit="C",
        data_type=PiTagDataType.NUMERIC,
        active=active,
        pi_web_id=pi_web_id,
    )
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)
    return tag


def test_norm_limits_resolves_both_tags_and_returns_points(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.TEMP",
        pi_web_id="W-MAIN",
        lower_limit_tag="LFI_RB1_LIM_INF",
        upper_limit_tag="LFI_RB1_LIM_SUP",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_LIM_INF": PiPoint(web_id="W-LOW", name="LFI_RB1_LIM_INF"),
        f"\\\\{tag.pi_server}\\LFI_RB1_LIM_SUP": PiPoint(web_id="W-HIGH", name="LFI_RB1_LIM_SUP"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-LOW": [
            make_value("2026-07-01T00:00:00Z", 100),
            make_value("2026-07-01T00:00:30Z", 105),
        ],
        "W-HIGH": [
            make_value("2026-07-01T00:00:00Z", 200),
            make_value("2026-07-01T00:00:30Z", 210),
        ],
    }

    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_tag_id"] == tag.id
    assert body["mode"] == "recorded"
    assert body["lower"]["tag_name"] == "LFI_RB1_LIM_INF"
    assert body["upper"]["tag_name"] == "LFI_RB1_LIM_SUP"
    assert len(body["lower"]["points"]) == 2
    assert len(body["upper"]["points"]) == 2
    assert body["lower"]["points"][0]["value"] == 100
    assert body["upper"]["points"][0]["value"] == 200
    assert body["errors"] == []


def test_norm_limits_uses_same_period_as_request(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.PRESS",
        pi_web_id="W-MAIN2",
        lower_limit_tag="LFI_RB1_P_LIM_INF",
        upper_limit_tag="LFI_RB1_P_LIM_SUP",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_P_LIM_INF": PiPoint(web_id="W-L", name="L"),
        f"\\\\{tag.pi_server}\\LFI_RB1_P_LIM_SUP": PiPoint(web_id="W-H", name="H"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-L": [make_value("2026-07-01T00:00:00Z", 1)],
        "W-H": [make_value("2026-07-01T00:00:00Z", 9)],
    }

    start = "2026-07-01T00:00:00Z"
    end = "2026-07-01T02:00:00Z"
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={"start_time": start, "end_time": end, "mode": "recorded"},
    )
    assert response.status_code == 200
    recorded_calls = client.fake_provider.recorded_calls  # type: ignore[attr-defined]
    assert len(recorded_calls) == 2
    for web_id, s, e, _ in recorded_calls:
        assert s == datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert e == datetime(2026, 7, 1, 2, tzinfo=timezone.utc)
        assert web_id in {"W-L", "W-H"}


def test_norm_limits_recorded_mode_used(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.SPEED",
        pi_web_id="W-MAIN3",
        lower_limit_tag="LFI_RB1_S_LIM_INF",
        upper_limit_tag="LFI_RB1_S_LIM_SUP",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_S_LIM_INF": PiPoint(web_id="W-L", name="L"),
        f"\\\\{tag.pi_server}\\LFI_RB1_S_LIM_SUP": PiPoint(web_id="W-H", name="H"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-L": [make_value("2026-07-01T00:00:00Z", 1)],
        "W-H": [make_value("2026-07-01T00:00:00Z", 9)],
    }
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    assert client.fake_provider.recorded_calls  # type: ignore[attr-defined]
    assert not client.fake_provider.interpolated_calls  # type: ignore[attr-defined]


def test_norm_limits_interpolated_mode_requires_interval(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.TEMP2",
        pi_web_id="W-MAIN4",
        lower_limit_tag="LFI_RB1_LIM_INF",
        upper_limit_tag="LFI_RB1_LIM_SUP",
    )
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "interpolated",
        },
    )
    assert response.status_code == 422
    body = response.json()
    detail = str(body).lower()
    assert "intervalo" in detail


def test_norm_limits_interpolated_mode_uses_interval(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.TEMP3",
        pi_web_id="W-MAIN5",
        lower_limit_tag="LFI_RB1_LIM_INF",
        upper_limit_tag="LFI_RB1_LIM_SUP",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_LIM_INF": PiPoint(web_id="W-L", name="L"),
        f"\\\\{tag.pi_server}\\LFI_RB1_LIM_SUP": PiPoint(web_id="W-H", name="H"),
    }
    client.fake_provider._interpolated = {  # type: ignore[attr-defined]
        "W-L": [make_value("2026-07-01T00:00:00Z", 5)],
        "W-H": [make_value("2026-07-01T00:00:00Z", 9)],
    }
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "interpolated",
            "interval": "5m",
        },
    )
    assert response.status_code == 200
    interpolated_calls = client.fake_provider.interpolated_calls  # type: ignore[attr-defined]
    assert len(interpolated_calls) == 2
    for call in interpolated_calls:
        assert call[3] == "5m"


def test_norm_limits_returns_validation_error_when_both_tags_missing(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.NO_LIMITS",
        pi_web_id="W-MAIN6",
        lower_limit_tag=None,
        upper_limit_tag=None,
    )
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert "nao possui tags de limite" in str(body).lower()


def test_norm_limits_with_only_lower_limit_configured(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.ONLY_LOW",
        pi_web_id="W-LOWONLY",
        lower_limit_tag="LFI_RB1_LIM_INF",
        upper_limit_tag=None,
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_LIM_INF": PiPoint(web_id="W-L1", name="LFI_RB1_LIM_INF"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-L1": [make_value("2026-07-01T00:00:00Z", 50)],
    }
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lower"]["tag_name"] == "LFI_RB1_LIM_INF"
    assert len(body["lower"]["points"]) == 1
    assert body["upper"]["tag_name"] is None
    assert len(body["upper"]["points"]) == 0


def test_norm_limits_with_only_upper_limit_configured(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.ONLY_UP",
        pi_web_id="W-UPONLY",
        lower_limit_tag=None,
        upper_limit_tag="LFI_RB1_LIM_SUP",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_LIM_SUP": PiPoint(web_id="W-U1", name="LFI_RB1_LIM_SUP"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-U1": [make_value("2026-07-01T00:00:00Z", 150)],
    }
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lower"]["tag_name"] is None
    assert len(body["lower"]["points"]) == 0
    assert body["upper"]["tag_name"] == "LFI_RB1_LIM_SUP"
    assert len(body["upper"]["points"]) == 1


def test_norm_limits_returns_diagnostic_when_tag_not_found(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.MISSING",
        pi_web_id="W-MAIN7",
        lower_limit_tag="LFI_RB1_MISSING_LOW",
        upper_limit_tag="LFI_RB1_MISSING_HIGH",
    )
    client.fake_provider._points = {}  # type: ignore[attr-defined]

    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["errors"]) >= 1
    assert any("LFI_RB1_MISSING_LOW" in err for err in body["errors"])
    assert any("LFI_RB1_MISSING_HIGH" in err for err in body["errors"])


def test_norm_limits_rejects_non_numeric_values(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.MIXED",
        pi_web_id="W-MAIN8",
        lower_limit_tag="LFI_RB1_MIX_LOW",
        upper_limit_tag="LFI_RB1_MIX_HIGH",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_MIX_LOW": PiPoint(web_id="W-L", name="L"),
        f"\\\\{tag.pi_server}\\LFI_RB1_MIX_HIGH": PiPoint(web_id="W-H", name="H"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-L": [
            PiValue(timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc), value="abc", good=False),
            PiValue(timestamp=datetime(2026, 7, 1, 0, 0, 30, tzinfo=timezone.utc), value=10, good=True),
        ],
        "W-H": [
            PiValue(timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc), value=99, good=True),
        ],
    }
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    lower_points = body["lower"]["points"]
    assert lower_points[0]["value"] is None
    assert lower_points[1]["value"] == 10
    assert body["upper"]["points"][0]["value"] == 99


def test_norm_limits_does_not_accept_arbitrary_tag_names(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.SAFE",
        pi_web_id="W-MAIN9",
        lower_limit_tag="LFI_RB1_SAFE_LOW",
        upper_limit_tag="LFI_RB1_SAFE_HIGH",
    )
    response = client.get(
        "/api/pi-tags/999999/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 404


def test_norm_limits_preserves_partial_response_when_one_tag_missing(
    client: TestClient, db_session: Session
) -> None:
    _configure_pi()
    tag = _make_tag(
        db_session,
        code="RB1.PARTIAL",
        pi_web_id="W-MAIN10",
        lower_limit_tag="LFI_RB1_PART_LOW",
        upper_limit_tag="LFI_RB1_PART_HIGH",
    )
    client.fake_provider._points = {  # type: ignore[attr-defined]
        f"\\\\{tag.pi_server}\\LFI_RB1_PART_LOW": PiPoint(web_id="W-L", name="L"),
    }
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W-L": [make_value("2026-07-01T00:00:00Z", 7)],
    }
    response = client.get(
        f"/api/pi-tags/{tag.id}/norm-limits",
        params={
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
            "mode": "recorded",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["lower"]["points"]) == 1
    assert body["upper"]["points"] == []
    assert any("LFI_RB1_PART_HIGH" in err for err in body["errors"])