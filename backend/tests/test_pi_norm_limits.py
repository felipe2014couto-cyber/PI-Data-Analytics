"""TimescaleDB-only tests for the norm limits endpoint."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiIngestionCoverage, PiSample
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


def _seed(db: Session, name: str, start: datetime, end: datetime, value: float, mode: str = "RECORDED", interval: int | None = None, status: str = "COMPLETE") -> PiTag:
    tag = _make_tag(db, code=name, lower=None, upper=None)
    db.add(PiSample(tag_id=tag.id, ts=start, value_type="double", value_double=value, source_mode=mode))
    if mode == "RECORDED":
        CoverageService.record_coverage(db, tag.id, start, end, mode, interval, status=status)
    else:
        db.add(PiIngestionCoverage(
            tag_id=tag.id, range_start=start, range_end=end, mode=mode,
            interval_seconds=interval, status="COMPLETE",
        ))
    db.commit()
    return tag


def test_missing_historical_limit_reports_coverage_reason_without_pi(client: TestClient, db_session: Session) -> None:
    source = _make_tag(db_session, code="SOURCE", lower="LOW", upper="HIGH")
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded",
    })
    assert response.status_code == 200
    body = response.json()
    assert "aguardando a próxima recarga histórica" in body["errors"][0]
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


def test_norm_limits_reject_interpolated_and_ignore_legacy_rows(client: TestClient, db_session: Session) -> None:
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
    assert response.status_code == 422
    recorded = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded",
    })
    assert recorded.status_code == 200
    assert "Cobertura RECORDED pendente" in recorded.json()["errors"][0]
    assert client.fake_provider.resolve_calls == []
    assert client.fake_provider.recorded_calls == []


def test_source_without_limits_returns_empty_without_error(client: TestClient, db_session: Session) -> None:
    source = _make_tag(db_session, code="NO_LIMITS", lower=None, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T01:00:00Z", "mode": "recorded",
    })
    assert response.status_code == 200
    assert response.json()["errors"] == []
    assert response.json()["lower"]["points"] == []
    assert response.json()["upper"]["points"] == []
    assert client.fake_provider.recorded_calls == []  # type: ignore[attr-defined]


def test_single_limit_is_valid_and_seed_before_window_is_returned(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOW_SEED", start - timedelta(hours=1), end, 10)
    # Add a later change in the requested interval; earlier Good seed is included.
    db_session.add(PiSample(tag_id=low.id, ts=start + timedelta(minutes=20), value_type="double", value_double=12, source_mode="RECORDED"))
    db_session.commit()
    source = _make_tag(db_session, code="SOURCE_ONE", lower=low.pi_tag_name, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded",
    })
    assert response.status_code == 200, response.text
    points = response.json()["lower"]["points"]
    assert [p["value"] for p in points] == [10, 12], response.json()
    assert datetime.fromisoformat(points[0]["timestamp"].replace("Z", "+00:00")) == start - timedelta(hours=1)
    assert datetime.fromisoformat(points[1]["timestamp"].replace("Z", "+00:00")) == start + timedelta(minutes=20)
    assert response.json()["upper"]["points"] == []


def test_upper_only_limit_is_fetched_without_lower_limit(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    upper = _seed(db_session, "UPPER_ONLY", start, end, 20)
    source = _make_tag(db_session, code="SOURCE_UPPER", lower=None, upper=upper.pi_tag_name)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded",
    })
    assert response.status_code == 200, response.text
    assert response.json()["lower"]["points"] == []
    assert [point["value"] for point in response.json()["upper"]["points"]] == [20]


def test_empty_confirmed_window_holds_good_seed_without_gap(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOW_EMPTY_WINDOW", start - timedelta(hours=1), start, 10)
    CoverageService.record_coverage(db_session, low.id, start, end, status="EMPTY_CONFIRMED")
    db_session.commit()
    source = _make_tag(db_session, code="SOURCE_EMPTY", lower=low.pi_tag_name, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert [point["value"] for point in body["lower"]["points"]] == [10]
    assert body["lower"]["coverage_gaps"] == []
    assert body["errors"] == []


def test_bad_event_and_coverage_gap_are_reported_for_limit(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _make_tag(db_session, code="LOW_GAP", lower=None, upper=None)
    db_session.add_all([
        PiSample(tag_id=low.id, ts=start, value_type="double", value_double=4, source_mode="RECORDED"),
        PiSample(tag_id=low.id, ts=start + timedelta(minutes=10), value_type="double", value_double=None,
                 source_mode="RECORDED", good=False),
        PiSample(tag_id=low.id, ts=start + timedelta(minutes=40), value_type="double", value_double=8, source_mode="RECORDED"),
    ])
    CoverageService.record_coverage(db_session, low.id, start, start + timedelta(minutes=20))
    CoverageService.record_coverage(db_session, low.id, start + timedelta(minutes=30), end)
    db_session.commit()
    source = _make_tag(db_session, code="SOURCE_GAP", lower=low.pi_tag_name, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={
        "start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert any("Cobertura RECORDED pendente" in message for message in body["errors"])
    assert any("Bad/Timeout" in message for message in body["errors"])
    assert body["lower"]["points"][1]["good"] is False
    assert len(body["lower"]["coverage_gaps"]) == 1


def test_window_after_watermark_preserves_good_seed_and_events(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 9, 28, 14, 22, 28, tzinfo=UTC)
    end = datetime(2026, 10, 5, 14, 22, 28, tzinfo=UTC)
    watermark = datetime(2026, 10, 5, 14, 17, tzinfo=UTC)
    low = _seed(db_session, "LOW_WATERMARK", start - timedelta(minutes=2), watermark, 25)
    db_session.add_all([
        PiSample(tag_id=low.id, ts=start + timedelta(days=1), value_type="double", value_double=27, source_mode="RECORDED"),
        ])
    db_session.commit()
    source = _make_tag(db_session, code="SOURCE_WATERMARK", lower=low.pi_tag_name, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={"start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded"})
    assert response.status_code == 200
    body = response.json()
    assert [p["value"] for p in body["lower"]["points"]] == [25, 27]
    assert body["lower"]["coverage_gaps"] == [[watermark.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")]]
    assert any("Cobertura RECORDED pendente" in error and watermark.isoformat() in error for error in body["errors"])
    assert "Não foi possível consultar" not in str(body)
    assert client.fake_provider.recorded_calls == []


def test_empty_confirmed_until_watermark_retains_seed_and_real_gap(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    watermark = start + timedelta(minutes=50)
    low = _seed(db_session, "LOW_EMPTY_TAIL", start - timedelta(hours=1), start + timedelta(minutes=20), 10)
    CoverageService.record_coverage(db_session, low.id, start + timedelta(minutes=30), watermark, status="EMPTY_CONFIRMED")
    db_session.commit()
    source = _make_tag(db_session, code="SOURCE_EMPTY_TAIL", lower=low.pi_tag_name, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={"start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded"})
    assert response.status_code == 200
    body = response.json()
    assert [p["value"] for p in body["lower"]["points"]] == [10]
    assert len(body["lower"]["coverage_gaps"]) == 2
    assert body["lower"]["coverage_gaps"][0][0].endswith("00:20:00Z")
    assert body["lower"]["coverage_gaps"][1][0].endswith("00:50:00Z")
    assert any("Cobertura RECORDED pendente" in error for error in body["errors"])


def test_two_limit_metadata_is_batched_without_orm_relationship_queries(client: TestClient, db_session: Session) -> None:
    from sqlalchemy import event
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOW_BATCH", start, end, 10)
    high = _seed(db_session, "HIGH_BATCH", start, end, 20)
    source = _make_tag(db_session, code="SOURCE_BATCH", lower=low.pi_tag_name, upper=high.pi_tag_name)
    source_id = source.id
    statements = []
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"): statements.append(statement)
    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", count)
    try:
        response = client.get(f"/api/pi-tags/{source_id}/norm-limits", params={"start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded"})
    finally:
        event.remove(bind, "before_cursor_execute", count)
    assert response.status_code == 200
    metadata = [sql for sql in statements if "pi_tags" in sql]
    assert len(metadata) == 2, statements
    overlay_statements = [sql for sql in statements if "FROM users" not in sql]
    assert len(overlay_statements) == 8, overlay_statements
    assert all("JOIN equipments" not in sql and "sampling_mode" not in sql for sql in metadata)
    assert client.fake_provider.recorded_calls == []


def test_good_substituted_limit_is_still_good(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOW_SUBSTITUTED", start - timedelta(minutes=1), end, 1120)
    sample = db_session.query(PiSample).filter_by(tag_id=low.id).one()
    sample.substituted = True
    db_session.commit()
    source = _make_tag(db_session, code="SOURCE_SUBSTITUTED", lower=low.pi_tag_name, upper=None)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={"start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded"})
    assert response.status_code == 200
    assert response.json()["lower"]["points"][0]["good"] is True
    assert response.json()["errors"] == []


def test_query_failure_reports_safe_original_sqlstate(client: TestClient, db_session: Session, monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError
    from app.services.pi_norm_limits_service import PiNormLimitsService
    start = datetime(2026, 7, 1, tzinfo=UTC); end = start + timedelta(hours=1)
    low = _seed(db_session, "LOW_TIMEOUT", start, end, 10)
    source = _make_tag(db_session, code="SOURCE_TIMEOUT", lower=low.pi_tag_name, upper=None)
    class StatementTimeout(Exception):
        sqlstate = "57014"
    def fail(*args, **kwargs):
        raise OperationalError("secret SQL", {"password": "never expose"}, StatementTimeout("canceling statement due to statement timeout"))
    monkeypatch.setattr(PiNormLimitsService, "_try_fetch_from_db", fail)
    response = client.get(f"/api/pi-tags/{source.id}/norm-limits", params={"start_time": start.isoformat(), "end_time": end.isoformat(), "mode": "recorded"})
    assert response.status_code == 200
    assert "Timeout" in response.json()["lower"]["error"]
    assert "SQLSTATE 57014" in response.json()["lower"]["error"]
    assert "password" not in response.text and "secret SQL" not in response.text
