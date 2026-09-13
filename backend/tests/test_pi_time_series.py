"""TimescaleDB-only historical time-series endpoint tests."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import HistoricalDataNotLoadedError
from app.integrations.pi.provider import PiValue
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiSample
from app.models.section import Section
from app.models.variable_type import VariableType
from app.schemas.pi import TimeSeriesPoint
from app.services.coverage_service import CoverageService


def _configure_pi() -> None:
    from app.core.config import get_settings
    settings = get_settings()
    settings.pi_web_api_base_url = "https://pi.local/piwebapi"
    settings.pi_data_server_name = "PI"


def _make_tag(db: Session, code: str | None = None, *, unit: str | None = "C", **kwargs) -> PiTag:
    code = code or kwargs.pop("tag_name", None) or kwargs.pop("name", None)
    if not code:
        raise ValueError("code is required")
    eq = Equipment(code=f"EQ-{code}", name=code); db.add(eq); db.flush()
    sec = Section(equipment_id=eq.id, code="S1", name="Section"); vt = VariableType(code=f"VT-{code}", name="Numeric")
    db.add_all([sec, vt]); db.flush()
    tag = PiTag(equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
                pi_server="PI", pi_tag_name=code, display_name=code,
                engineering_unit=unit, data_type=PiTagDataType.NUMERIC, active=True)
    db.add(tag); db.commit(); db.refresh(tag); return tag


def _seed(db: Session, tag: PiTag, start: datetime, end: datetime, values: list[tuple[datetime, object]], mode: str = "RECORDED", interval: int | None = None) -> None:
    for ts, value in values:
        kind = "boolean" if isinstance(value, bool) else "double" if isinstance(value, (int, float)) else "string"
        db.add(PiSample(tag_id=tag.id, ts=ts, value_type=kind,
                        value_double=float(value) if kind == "double" else None,
                        value_boolean=value if kind == "boolean" else None,
                        value_text=value if kind == "string" else None,
                        source_mode=mode))
    CoverageService.record_coverage(db, tag.id, start, end, mode, interval); db.commit()


def test_time_series_point_serialization_preserves_numeric_string() -> None:
    point = TimeSeriesPoint(timestamp=datetime(2026, 7, 1, tzinfo=UTC), value="600")
    assert point.model_dump(mode="json")["value"] == "600"


def test_recorded_reads_timescaledb_and_reports_source(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    tag = _make_tag(db_session, "RECORDED")
    _seed(db_session, tag, start, end, [(start, 82.5), (start + timedelta(seconds=30), 83.1)], "RECORDED")
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded"})
    assert response.status_code == 200, response.text
    body = response.json(); assert body["query_execution"]["source"] == "timescaledb"
    # SQLite exercises the raw RECORDED fallback; PostgreSQL routes the same
    # request through the 10-second continuous aggregate.
    assert body["query_execution"]["effective_interval"] is None
    assert len(body["series"][0]["points"]) == 2
    assert client.fake_provider.recorded_calls == []  # type: ignore[attr-defined]


def test_interpolated_uses_exact_resolution(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    tag = _make_tag(db_session, "INTERP")
    _seed(db_session, tag, start, end, [(start, 1.0)], "INTERPOLATED_60S", 60)
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "interpolated", "interval": "1m"})
    assert response.status_code == 200, response.text
    assert response.json()["query_execution"]["source"] == "timescaledb"
    assert client.fake_provider.interpolated_calls == []  # type: ignore[attr-defined]


def test_missing_coverage_is_structured_409_and_pi_free(client: TestClient, db_session: Session) -> None:
    tag = _make_tag(db_session, "MISSING")
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "HISTORICAL_DATA_NOT_LOADED"
    assert error["details"]["reload_available"] is True
    assert client.fake_provider.recorded_calls == []  # type: ignore[attr-defined]


def test_invalid_range_and_interpolated_interval(client: TestClient, db_session: Session) -> None:
    tag = _make_tag(db_session, "VALIDATION")
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": "2026-07-01T02:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded"})
    assert response.status_code == 400
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "interpolated"})
    assert response.status_code == 422
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "interpolated", "interval": "1s"})
    assert response.status_code == 400


def test_limit_inactive_and_unknown_tag_contracts(client: TestClient, db_session: Session) -> None:
    tag = _make_tag(db_session, "INACTIVE")
    db_session.query(PiTag).filter(PiTag.id == tag.id).update({"active": False}); db_session.commit()
    response = client.get("/api/time-series", params={"tag_ids": [tag.id], "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded"})
    assert response.status_code == 409
    response = client.get("/api/time-series", params={"tag_ids": [999999], "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded"})
    assert response.status_code == 404
