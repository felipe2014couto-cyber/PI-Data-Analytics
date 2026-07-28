"""Tests for the GET /api/time-series contract (parameter formats and limits)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.section import Section
from app.models.variable_type import VariableType
from tests.pi_fakes import FakePiDataProvider, make_value


def _configure_pi(max_tags: int = 10, max_points: int = 20000) -> None:
    s = get_settings()
    s.pi_web_api_base_url = "https://pi.local/piwebapi"
    s.pi_data_server_name = "PI_DATA"
    s.pi_query_max_tags = max_tags
    s.pi_query_max_points_per_tag = max_points


def _make_tag(db_session: Session, *, code: str, web_id: str) -> PiTag:
    equipment = Equipment(code=f"EQ-{code}", name=f"Equipment {code}")
    db_session.add(equipment)
    db_session.flush()
    section = Section(equipment_id=equipment.id, code="S1", name="Section 1")
    db_session.add(section)
    variable_type = VariableType(code=f"VT-{code}", name="VT")
    db_session.add(variable_type)
    db_session.flush()
    tag = PiTag(
        equipment_id=equipment.id,
        section_id=section.id,
        variable_type_id=variable_type.id,
        pi_server="PI_DATA",
        pi_tag_name=code,
        display_name=code,
        engineering_unit="C",
        data_type=PiTagDataType.NUMERIC,
        active=True,
        pi_web_id=web_id,
    )
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)
    return tag


def test_time_series_accepts_repeated_tag_ids(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.A", web_id="W1")
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": None}  # type: ignore[attr-defined]
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W1": [make_value("2026-07-01T00:00:00Z", 1.0)]
    }

    response = client.get(
        "/api/time-series",
        params=[
            ("tag_ids", tag.id),
            ("start_time", "2026-07-01T00:00:00Z"),
            ("end_time", "2026-07-01T01:00:00Z"),
            ("mode", "recorded"),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["series"][0]["tag_id"] == tag.id


def test_time_series_accepts_csv_tag_ids(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.B", web_id="W2")
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": None}  # type: ignore[attr-defined]
    client.fake_provider._recorded = {  # type: ignore[attr-defined]
        "W2": [make_value("2026-07-01T00:00:00Z", 2.0)]
    }

    response = client.get(
        f"/api/time-series?tag_ids={tag.id}&start_time=2026-07-01T00:00:00Z&end_time=2026-07-01T01:00:00Z&mode=recorded"
    )
    assert response.status_code == 200, response.text
    assert response.json()["series"][0]["tag_id"] == tag.id


def test_time_series_max_count_limit_enforced(client: TestClient) -> None:
    _configure_pi(max_points=100)
    # The 1_000_000 ceiling is set by the API itself; values above 1_000_000
    # should be rejected before they ever hit the service layer.
    response = client.get(
        "/api/time-series",
        params=[
            ("tag_ids", 1),
            ("start_time", "2026-07-01T00:00:00Z"),
            ("end_time", "2026-07-01T01:00:00Z"),
            ("mode", "recorded"),
            ("max_count", 2_000_000),
        ],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_time_series_max_tags_enforced_via_query(client: TestClient) -> None:
    _configure_pi(max_tags=1)
    response = client.get(
        "/api/time-series",
        params=[
            ("tag_ids", 1),
            ("tag_ids", 2),
            ("start_time", "2026-07-01T00:00:00Z"),
            ("end_time", "2026-07-01T01:00:00Z"),
            ("mode", "recorded"),
        ],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PI_QUERY_LIMIT_EXCEEDED"
