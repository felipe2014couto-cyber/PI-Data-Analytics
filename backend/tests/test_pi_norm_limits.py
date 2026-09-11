"""TimescaleDB-only tests for the norm limits endpoint."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiSample
from app.models.section import Section
from app.models.variable_type import VariableType
from app.services.coverage_service import CoverageService


def _make_tag(db: Session, *, code: str, lower: str | None, upper: str | None) -> PiTag:
    equipment = Equipment(code=f"EQ-{code}", name=f"Equipment {code}")
    db.add(equipment); db.flush()
    section = Section(equipment_id=equipment.id, code="S1", name="Section")
    variable_type = VariableType(code=f"VT-{code}", name="Numeric")
    db.add_all([section, variable_type]); db.flush()
    tag = PiTag(
        equipment_id=equipment.id, section_id=section.id, variable_type_id=variable_type.id,
        pi_server="PI", pi_tag_name=code, display_name=code,
        lower_limit_tag=lower, upper_limit_tag=upper,
        data_type=PiTagDataType.NUMERIC, active=True,
    )
    db.add(tag); db.commit(); db.refresh(tag)
    return tag


def _seed(db: Session, name: str, start: datetime, end: datetime, value: float, mode: str = "RECORDED", interval: int | None = None) -> PiTag:
    tag = _make_tag(db, code=name, lower=None, upper=None)
    db.add(PiSample(tag_id=tag.id, ts=start, value_type="double", value_double=value, source_mode=mode))
    CoverageService.record_coverage(db, tag.id, start, end, mode, interval)
    db.commit()
    return tag


def test_missing_historical_limit_returns_409_without_pi(client: TestClient, db_session: Session) -> None:
    source = _make_tag(db_session, code="SOURCE", lower="LOW", upper="HIGH")
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded",
    })
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "HISTORICAL_DATA_NOT_LOADED"
    assert client.fake_provider.recorded_calls == []  # type: ignore[attr-defined]


def test_recorded_limit_is_read_from_timescaledb(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOW", start, end, 10)
    high = _seed(db_session, "HIGH", start, end, 20)
    source = _make_tag(db_session, code="SOURCE", lower=low.pi_tag_name, upper=high.pi_tag_name)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lower"]["points"][0]["value"] == 10
    assert body["upper"]["points"][0]["value"] == 20
    assert client.fake_provider.recorded_calls == []  # type: ignore[attr-defined]


def test_interpolated_limit_requires_and_uses_exact_resolution(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOWI", start, end, 5, "INTERPOLATED_300S", 300)
    high = _seed(db_session, "HIGHI", start, end, 9, "INTERPOLATED_300S", 300)
    source = _make_tag(db_session, code="SOURCEI", lower=low.pi_tag_name, upper=high.pi_tag_name)
    missing_interval = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "interpolated",
    })
    assert missing_interval.status_code == 422
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "interpolated", "interval": "5m",
    })
    assert response.status_code == 200, response.text
    assert response.json()["lower"]["points"][0]["value"] == 5
    assert client.fake_provider.interpolated_calls == []  # type: ignore[attr-defined]


def test_source_without_limits_still_returns_validation_error(client: TestClient, db_session: Session) -> None:
    source = _make_tag(db_session, code="NO_LIMITS", lower=None, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded",
    })
    assert response.status_code == 422
