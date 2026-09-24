"""Integration tests for dynamic analysis filters by VariableType."""
from datetime import UTC, datetime, timedelta
import json
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiSample
from app.models.section import Section
from app.models.section_analysis_tag import SectionAnalysisTag
from app.models.variable_type import VariableFilterDataType, VariableType
from app.services.coverage_service import CoverageService


def _setup_section_with_tags(db: Session):
    eq = Equipment(code="EQ-DYN", name="Equipment Dynamic")
    db.add(eq)
    db.flush()

    sec = Section(equipment_id=eq.id, code="SEC-DYN", name="Section Dynamic")
    db.add(sec)
    db.flush()

    # Create variable types of each filter data type
    vt_real = VariableType(code="TEMP", name="Temperature", default_unit="C", filter_data_type=VariableFilterDataType.REAL)
    vt_digital = VariableType(code="PUMP_ON", name="Pump Status", default_unit=None, filter_data_type=VariableFilterDataType.DIGITAL)
    vt_string = VariableType(code="COIL_ID", name="Coil Identifier", default_unit=None, filter_data_type=VariableFilterDataType.STRING)
    vt_other = VariableType(code="SPEED", name="Speed", default_unit="rpm", filter_data_type=VariableFilterDataType.REAL)
    db.add_all([vt_real, vt_digital, vt_string, vt_other])
    db.flush()

    # Create pi tags
    tag_temp = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt_real.id,
        pi_server="PI", pi_tag_name="TEMP.01", display_name="Temperature 1",
        data_type=PiTagDataType.NUMERIC, active=True,
    )
    tag_pump = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt_digital.id,
        pi_server="PI", pi_tag_name="PUMP.01", display_name="Pump 1",
        data_type=PiTagDataType.NON_NUMERIC, active=True,
    )
    tag_coil = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt_string.id,
        pi_server="PI", pi_tag_name="COIL.01", display_name="Coil 1",
        data_type=PiTagDataType.NON_NUMERIC, active=True,
    )
    tag_speed = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt_other.id,
        pi_server="PI", pi_tag_name="SPEED.01", display_name="Speed 1",
        data_type=PiTagDataType.NUMERIC, active=True,
    )
    db.add_all([tag_temp, tag_pump, tag_coil, tag_speed])
    db.flush()

    # Link TEMP, PUMP, COIL as analysis tags of SEC
    sat_temp = SectionAnalysisTag(section_id=sec.id, variable_type_id=vt_real.id, pi_tag_id=tag_temp.id)
    sat_pump = SectionAnalysisTag(section_id=sec.id, variable_type_id=vt_digital.id, pi_tag_id=tag_pump.id)
    sat_coil = SectionAnalysisTag(section_id=sec.id, variable_type_id=vt_string.id, pi_tag_id=tag_coil.id)
    db.add_all([sat_temp, sat_pump, sat_coil])
    db.commit()

    return {
        "equipment": eq,
        "section": sec,
        "types": {
            "real": vt_real,
            "digital": vt_digital,
            "string": vt_string,
            "unlinked": vt_other,
        },
        "tags": {
            "temp": tag_temp,
            "pump": tag_pump,
            "coil": tag_coil,
            "speed": tag_speed,
        },
    }


def _seed_data(db: Session, fixture_data: dict, start: datetime, end: datetime):
    t0 = start
    t1 = start + timedelta(minutes=10)
    t2 = start + timedelta(minutes=20)
    t3 = start + timedelta(minutes=30)
    timestamps = [t0, t1, t2, t3]

    # Tag SPEED (the main series being analyzed): values 100, 200, 300, 400
    # Tag TEMP (REAL filter tag): values 50.0, 75.0, 90.0, 110.0
    # Tag PUMP (DIGITAL filter tag): values True, False, True, False
    # Tag COIL (STRING filter tag): values "P001", "P005", "X010", "P100"

    speed_vals = [100.0, 200.0, 300.0, 400.0]
    temp_vals = [50.0, 75.0, 90.0, 110.0]
    pump_vals = [True, False, True, False]
    coil_vals = ["P001", "P005", "X010", "P100"]

    for i, ts in enumerate(timestamps):
        db.add(PiSample(
            tag_id=fixture_data["tags"]["speed"].id, ts=ts, value_type="double",
            value_double=speed_vals[i], source_mode="RECORDED",
        ))
        db.add(PiSample(
            tag_id=fixture_data["tags"]["temp"].id, ts=ts, value_type="double",
            value_double=temp_vals[i], source_mode="RECORDED",
        ))
        db.add(PiSample(
            tag_id=fixture_data["tags"]["pump"].id, ts=ts, value_type="boolean",
            value_boolean=pump_vals[i], source_mode="RECORDED",
        ))
        db.add(PiSample(
            tag_id=fixture_data["tags"]["coil"].id, ts=ts, value_type="string",
            value_text=coil_vals[i], source_mode="RECORDED",
        ))

    for tag in fixture_data["tags"].values():
        CoverageService.record_coverage(db, tag.id, start, end, "RECORDED", None)
    db.commit()

    return timestamps


def test_validation_error_when_section_missing_for_active_filter(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    _seed_data(db_session, data, start, end)

    filters = [{"variable_type_id": data["types"]["real"].id, "min": 60.0}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "analysis_filters": json.dumps(filters),
        },
    )
    assert resp.status_code == 422
    assert "section_id" in resp.text


def test_validation_error_when_variable_type_not_linked_to_section(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    _seed_data(db_session, data, start, end)

    # SPEED is unlinked as SectionAnalysisTag
    filters = [{"variable_type_id": data["types"]["unlinked"].id, "min": 100.0}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["temp"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters),
        },
    )
    assert resp.status_code == 422
    assert "não está vinculado" in resp.text


def test_validation_error_when_min_greater_than_max(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    _seed_data(db_session, data, start, end)

    filters = [{"variable_type_id": data["types"]["real"].id, "min": 100.0, "max": 50.0}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters),
        },
    )
    assert resp.status_code == 422
    assert "mínimo não pode ser maior" in resp.text


def test_filter_real_universe_reduction(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    timestamps = _seed_data(db_session, data, start, end)

    # Filter TEMP between 70.0 and 100.0 -> matches t1 (75.0) and t2 (90.0)
    # Series SPEED should return only points at t1 (200.0) and t2 (300.0)
    filters = [{"variable_type_id": data["types"]["real"].id, "min": 70.0, "max": 100.0}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters),
        },
    )
    assert resp.status_code == 200, resp.text
    points = resp.json()["series"][0]["points"]
    assert len(points) == 2
    assert points[0]["value"] == 200.0
    assert points[1]["value"] == 300.0


def test_filter_digital_on_and_off(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    timestamps = _seed_data(db_session, data, start, end)

    # Filter PUMP = ON -> matches t0 (True) and t2 (True) -> speed: 100.0, 300.0
    filters_on = [{"variable_type_id": data["types"]["digital"].id, "value": "ON"}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters_on),
        },
    )
    assert resp.status_code == 200, resp.text
    points_on = resp.json()["series"][0]["points"]
    assert len(points_on) == 2
    assert points_on[0]["value"] == 100.0
    assert points_on[1]["value"] == 300.0

    # Filter PUMP = OFF -> matches t1 (False) and t3 (False) -> speed: 200.0, 400.0
    filters_off = [{"variable_type_id": data["types"]["digital"].id, "value": "OFF"}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters_off),
        },
    )
    assert resp.status_code == 200, resp.text
    points_off = resp.json()["series"][0]["points"]
    assert len(points_off) == 2
    assert points_off[0]["value"] == 200.0
    assert points_off[1]["value"] == 400.0


def test_filter_string_exact_wildcard_range(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    timestamps = _seed_data(db_session, data, start, end)

    # 1. Exact match: "p005" (case-insensitive) -> matches t1 -> speed 200.0
    filters_exact = [{"variable_type_id": data["types"]["string"].id, "expression": "p005"}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters_exact),
        },
    )
    assert resp.status_code == 200, resp.text
    pts = resp.json()["series"][0]["points"]
    assert len(pts) == 1
    assert pts[0]["value"] == 200.0

    # 2. Wildcard: "P00*" -> matches t0 (P001) and t1 (P005) -> speed 100.0, 200.0
    filters_wc = [{"variable_type_id": data["types"]["string"].id, "expression": "P00*"}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters_wc),
        },
    )
    assert resp.status_code == 200, resp.text
    pts = resp.json()["series"][0]["points"]
    assert len(pts) == 2
    assert pts[0]["value"] == 100.0
    assert pts[1]["value"] == 200.0

    # 3. Range: "P001:P005" -> matches t0 (P001) and t1 (P005)
    filters_rng = [{"variable_type_id": data["types"]["string"].id, "expression": "P001:P005"}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters_rng),
        },
    )
    assert resp.status_code == 200, resp.text
    pts = resp.json()["series"][0]["points"]
    assert len(pts) == 2

    # 4. Invalid expression syntax: "P001:X100" -> 422
    filters_invalid = [{"variable_type_id": data["types"]["string"].id, "expression": "P001:X100"}]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters_invalid),
        },
    )
    assert resp.status_code == 422
    assert "os prefixos das duas extremidades devem ser iguais" in resp.text


def test_multiple_combined_dynamic_filters(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    timestamps = _seed_data(db_session, data, start, end)

    # Combined: TEMP >= 70.0 AND PUMP = ON
    # t0: TEMP 50.0, PUMP True (fails TEMP)
    # t1: TEMP 75.0, PUMP False (fails PUMP)
    # t2: TEMP 90.0, PUMP True (SATISFIES BOTH!) -> SPEED 300.0
    # t3: TEMP 110.0, PUMP False (fails PUMP)
    filters = [
        {"variable_type_id": data["types"]["real"].id, "min": 70.0},
        {"variable_type_id": data["types"]["digital"].id, "value": "ON"},
    ]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters),
        },
    )
    assert resp.status_code == 200, resp.text
    points = resp.json()["series"][0]["points"]
    assert len(points) == 1
    assert points[0]["value"] == 300.0


def test_dynamic_filter_real_selection_and_all_ignored(client: TestClient, db_session: Session):
    data = _setup_section_with_tags(db_session)
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    _seed_data(db_session, data, start, end)

    # Exact selection on REAL tag: expression="75.0" and digital value="ALL"
    filters = [
        {"variable_type_id": data["types"]["real"].id, "expression": "75.0"},
        {"variable_type_id": data["types"]["digital"].id, "value": "ALL"},
    ]
    resp = client.get(
        "/api/time-series",
        params={
            "tag_ids": [data["tags"]["speed"].id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "section_id": data["section"].id,
            "analysis_filters": json.dumps(filters),
        },
    )
    assert resp.status_code == 200, resp.text
    points = resp.json()["series"][0]["points"]
    assert len(points) == 1
    assert points[0]["value"] == 200.0  # t1 point where TEMP was 75.0

