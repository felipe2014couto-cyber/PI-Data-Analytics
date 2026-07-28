"""Tests for tag validation against the PI Web API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pi.errors import (
    PiAuthError,
    PiInvalidResponseError,
    PiSSLError,
    PiTimeoutError,
    PiUnavailableError,
)
from app.integrations.pi.provider import PiPoint
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType, PiTagValidationStatus
from app.models.section import Section
from app.models.variable_type import VariableType


def _configure_pi() -> None:
    settings = get_settings()
    settings.pi_web_api_base_url = "https://pi.local/piwebapi"
    settings.pi_data_server_name = "PI_DATA"
    settings.pi_web_api_auth_mode = "none"


def _make_tag(
    db_session: Session,
    *,
    code: str = "RB3.TEMP",
    pi_server: str = "PI_DATA",
    pi_web_id: str | None = None,
    active: bool = True,
) -> PiTag:
    equipment = Equipment(code=f"EQ-{code}", name=f"Equipment {code}")
    db_session.add(equipment)
    db_session.flush()
    section = Section(equipment_id=equipment.id, code="S1", name="Section 1")
    db_session.add(section)
    variable_type = VariableType(code=f"VT-{code}", name="Variable")
    db_session.add(variable_type)
    db_session.flush()
    tag = PiTag(
        equipment_id=equipment.id,
        section_id=section.id,
        variable_type_id=variable_type.id,
        pi_server=pi_server,
        pi_tag_name=code,
        display_name=code,
        engineering_unit="C",
        data_type=PiTagDataType.NUMERIC,
        active=active,
        pi_web_id=pi_web_id,
    )
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)
    return tag


def test_validate_tag_resolved_status_valid(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.TEMP")
    point = PiPoint(
        web_id="ABCD1234",
        name="RB3.TEMP",
        description="Temperature",
        engineering_unit="C",
        point_type="float32",
    )
    client.fake_provider._points = {f"\\\\{tag.pi_server}\\{tag.pi_tag_name}": point}  # type: ignore[attr-defined]

    response = client.post(f"/api/pi-tags/{tag.id}/validate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "VALID"
    assert body["web_id"] == "ABCD1234"
    assert body["message"] is not None

    db_session.expire_all()
    refreshed = db_session.get(PiTag, tag.id)
    assert refreshed is not None
    assert refreshed.validation_status == PiTagValidationStatus.VALID
    assert refreshed.pi_web_id == "ABCD1234"
    assert refreshed.validated_at is not None
    # Catalog metadata is preserved.
    assert refreshed.display_name == tag.display_name
    assert refreshed.equipment_id == tag.equipment_id
    assert refreshed.section_id == tag.section_id
    assert refreshed.variable_type_id == tag.variable_type_id


def test_validate_tag_not_found_status_invalid(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.MISSING")
    response = client.post(f"/api/pi-tags/{tag.id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INVALID"
    assert body["web_id"] is None

    db_session.expire_all()
    refreshed = db_session.get(PiTag, tag.id)
    assert refreshed is not None
    assert refreshed.validation_status == PiTagValidationStatus.INVALID
    assert refreshed.pi_web_id is None


@pytest.mark.parametrize(
    "exc,expected_code",
    [
        (PiAuthError(), "PI_AUTH_FAILED"),
        (PiTimeoutError(), "PI_TIMEOUT"),
        (PiSSLError(), "PI_SSL_ERROR"),
        (PiUnavailableError(), "PI_UNAVAILABLE"),
        (PiInvalidResponseError(), "PI_INVALID_RESPONSE"),
    ],
)
def test_validate_tag_error_status_preserves_cadastro(
    client: TestClient, db_session: Session, exc, expected_code
) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.DOWN")
    client.fake_provider._raise_on_resolve = exc  # type: ignore[attr-defined]

    response = client.post(f"/api/pi-tags/{tag.id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ERROR"
    assert body["error_code"] == expected_code

    db_session.expire_all()
    refreshed = db_session.get(PiTag, tag.id)
    assert refreshed is not None
    assert refreshed.validation_status == PiTagValidationStatus.ERROR
    # Preserved cadastro data
    assert refreshed.display_name == tag.display_name
    assert refreshed.equipment_id == tag.equipment_id
    assert refreshed.section_id == tag.section_id
    assert refreshed.variable_type_id == tag.variable_type_id


def test_validate_tag_not_found_inactive_returns_409(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag = _make_tag(db_session, code="RB3.INACTIVE", active=False)

    response = client.post(f"/api/pi-tags/{tag.id}/validate")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "TAG_INACTIVE"


def test_validate_tag_local_not_found(client: TestClient) -> None:
    _configure_pi()
    response = client.post("/api/pi-tags/999/validate")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_validate_tag_pi_not_configured(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    settings.pi_web_api_base_url = None
    settings.pi_data_server_name = None
    tag = _make_tag(db_session, code="RB3.NOCONF")

    response = client.post(f"/api/pi-tags/{tag.id}/validate")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PI_NOT_CONFIGURED"


def test_validate_batch_mixed_results(client: TestClient, db_session: Session) -> None:
    _configure_pi()
    tag_valid = _make_tag(db_session, code="RB3.A")
    tag_invalid = _make_tag(db_session, code="RB3.B")
    tag_error = _make_tag(db_session, code="RB3.C")

    point = PiPoint(web_id="A123", name="RB3.A")
    client.fake_provider._points = {f"\\\\{tag_valid.pi_server}\\{tag_valid.pi_tag_name}": point}  # type: ignore[attr-defined]
    error_path = f"\\\\{tag_error.pi_server}\\{tag_error.pi_tag_name}"
    client.fake_provider._raise_on_resolve = lambda path: PiUnavailableError() if path == error_path else None  # type: ignore[attr-defined]

    response = client.post(
        "/api/pi-tags/validate",
        json={"tag_ids": [tag_valid.id, tag_invalid.id, tag_error.id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["valid"] == 1
    assert body["invalid"] == 1
    assert body["error"] == 1
    statuses = sorted(r["status"] for r in body["results"])
    assert statuses == ["ERROR", "INVALID", "VALID"]
