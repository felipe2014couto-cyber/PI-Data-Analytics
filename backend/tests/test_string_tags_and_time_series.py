"""Unit and integration tests for STRING tag temporal queries, selection, and API contracts."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.integrations.pi.provider import PiRecordedValues, PiValue
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiSample
from app.models.section import Section
from app.models.variable_type import VariableFilterDataType, VariableType
from app.schemas.pi import (
    TimeSeriesPoint,
    TimeSeriesRequest,
    determine_series_data_type,
    is_string_tag,
)
from app.services.coverage_service import CoverageService
from app.services.pi_service import PiService


def _create_string_tag(
    db: Session,
    code: str = "STR_TAG_1",
    *,
    filter_data_type: VariableFilterDataType = VariableFilterDataType.STRING,
    tag_data_type: PiTagDataType = PiTagDataType.NON_NUMERIC,
) -> PiTag:
    eq = Equipment(code=f"EQ-{code}", name=f"Equipment {code}")
    db.add(eq)
    db.flush()
    sec = Section(equipment_id=eq.id, code="S1", name="Section 1")
    vt = VariableType(
        code=f"VT-{code}",
        name=f"VarType {code}",
        filter_data_type=filter_data_type,
    )
    db.add_all([sec, vt])
    db.flush()
    tag = PiTag(
        equipment_id=eq.id,
        section_id=sec.id,
        variable_type_id=vt.id,
        pi_server="PIMS",
        pi_tag_name=code,
        display_name=f"Display {code}",
        engineering_unit="",
        data_type=tag_data_type,
        active=True,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def _create_numeric_tag(db: Session, code: str = "NUM_TAG_1") -> PiTag:
    eq = Equipment(code=f"EQ-{code}", name=f"Equipment {code}")
    db.add(eq)
    db.flush()
    sec = Section(equipment_id=eq.id, code="S1", name="Section 1")
    vt = VariableType(
        code=f"VT-{code}",
        name=f"VarType {code}",
        filter_data_type=VariableFilterDataType.REAL,
    )
    db.add_all([sec, vt])
    db.flush()
    tag = PiTag(
        equipment_id=eq.id,
        section_id=sec.id,
        variable_type_id=vt.id,
        pi_server="PIMS",
        pi_tag_name=code,
        display_name=f"Display {code}",
        engineering_unit="m/min",
        data_type=PiTagDataType.NUMERIC,
        active=True,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def _seed_string_samples(
    db: Session,
    tag: PiTag,
    start: datetime,
    end: datetime,
    samples: list[tuple[datetime, str | None, bool, bool]],
) -> None:
    for ts, val, good, quest in samples:
        db.add(
            PiSample(
                tag_id=tag.id,
                ts=ts,
                value_type="string",
                value_double=None,
                value_boolean=None,
                value_text=val,
                good=good,
                questionable=quest,
                substituted=False,
                source_mode="RECORDED",
            )
        )
    CoverageService.record_coverage(db, tag.id, start, end, "RECORDED", None)
    db.commit()


def test_series_data_type_determination() -> None:
    class FakeTag:
        def __init__(self, fdt=None, dt=None):
            self.variable_type = MagicMock(filter_data_type=fdt) if fdt else None
            self.data_type = dt

    assert determine_series_data_type(FakeTag(VariableFilterDataType.STRING)) == "STRING"
    assert determine_series_data_type(FakeTag(VariableFilterDataType.DIGITAL)) == "DIGITAL"
    assert determine_series_data_type(FakeTag(VariableFilterDataType.REAL)) == "REAL"
    assert determine_series_data_type(FakeTag(None, PiTagDataType.NON_NUMERIC)) == "STRING"
    assert determine_series_data_type(FakeTag(None, PiTagDataType.NUMERIC)) == "REAL"
    assert is_string_tag(FakeTag(VariableFilterDataType.STRING)) is True
    assert is_string_tag(FakeTag(VariableFilterDataType.REAL)) is False


def test_string_tag_exact_text_empty_string_and_duplicates(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    tag = _create_string_tag(db_session, "LINE_STATUS_TXT")

    # Sequence with exact string, empty string, numeric-looking string, and repeated strings
    samples = [
        (start + timedelta(minutes=10), "BATCH_100_START", True, False),
        (start + timedelta(minutes=20), "", True, False),  # empty string preserved
        (start + timedelta(minutes=30), "450.75", True, False),  # numeric string NOT coerced to float
        (start + timedelta(minutes=40), "BATCH_100_RUNNING", True, False),
        (start + timedelta(minutes=50), "BATCH_100_RUNNING", True, False),  # repeated string preserved
        (start + timedelta(minutes=60), "BATCH_100_END", True, False),
    ]
    _seed_string_samples(db_session, tag, start, end, samples)

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["series"]) == 1
    series = data["series"][0]

    # Verify series metadata contract
    assert series["data_type"] == "STRING"
    assert series["tag_id"] == tag.id
    assert series["tag_name"] == "LINE_STATUS_TXT"

    # Verify points preservation
    points = series["points"]
    assert len(points) == 6
    assert [p["value"] for p in points] == [
        "BATCH_100_START",
        "",
        "450.75",
        "BATCH_100_RUNNING",
        "BATCH_100_RUNNING",
        "BATCH_100_END",
    ]
    # Exact types: all strings, not float or NaN
    for p in points:
        assert isinstance(p["value"], str)
        assert p["good"] is True

    # Check timestamps strictly sorted ascending
    ts_list = [p["timestamp"] for p in points]
    assert ts_list == sorted(ts_list)


def test_string_tag_bad_quality_vs_absence(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=3)
    tag = _create_string_tag(db_session, "QUALITY_TEST_TAG")

    samples = [
        (start + timedelta(minutes=15), "VAL_NORMAL", True, False),
        (start + timedelta(minutes=30), "Scan Off", False, False),  # Bad quality
        (start + timedelta(minutes=45), None, False, False),  # Bad quality without text
        (start + timedelta(minutes=60), "QUESTIONABLE_VAL", True, True),  # Questionable
        (start + timedelta(minutes=120), "RECOVERED", True, False),
    ]
    _seed_string_samples(db_session, tag, start, end, samples)

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    points = response.json()["series"][0]["points"]
    assert len(points) == 5

    # Point 0: Good valid text
    assert points[0]["value"] == "VAL_NORMAL"
    assert points[0]["good"] is True

    # Point 1: Bad quality with status text
    assert points[1]["value"] == "Scan Off"
    assert points[1]["good"] is False

    # Point 2: Bad quality with null
    assert points[2]["value"] is None
    assert points[2]["good"] is False

    # Point 3: Questionable quality
    assert points[3]["value"] == "QUESTIONABLE_VAL"
    assert points[3]["good"] is True
    assert points[3]["questionable"] is True

    # Point 4: Recovered text
    assert points[4]["value"] == "RECOVERED"
    assert points[4]["good"] is True


def test_string_tag_historical_query_accepts_recorded_only(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    tag = _create_string_tag(db_session, "INTERP_STRING_TAG")

    samples = [
        (start + timedelta(minutes=10), "MODE_A", True, False),
        (start + timedelta(minutes=25), "MODE_B", True, False),
    ]
    _seed_string_samples(db_session, tag, start, end, samples)

    # A STRING history is queried as RECORDED and never synthesized.
    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag.id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    series = response.json()["series"][0]
    assert series["data_type"] == "STRING"
    assert [p["value"] for p in series["points"]] == ["MODE_A", "MODE_B"]


def test_mixed_real_and_string_tags_query(client: TestClient, db_session: Session) -> None:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)

    tag_real = _create_numeric_tag(db_session, "SPEED_RPM")
    tag_str = _create_string_tag(db_session, "OP_STATE")

    # Seed numeric tag
    for ts, val in [(start + timedelta(minutes=10), 1500.5), (start + timedelta(minutes=30), 1600.0)]:
        db_session.add(
            PiSample(
                tag_id=tag_real.id,
                ts=ts,
                value_type="double",
                value_double=val,
                good=True,
                questionable=False,
                substituted=False,
                source_mode="RECORDED",
            )
        )
    CoverageService.record_coverage(db_session, tag_real.id, start, end, "RECORDED", None)

    # Seed string tag
    _seed_string_samples(
        db_session,
        tag_str,
        start,
        end,
        [
            (start + timedelta(minutes=10), "CRUISING", True, False),
            (start + timedelta(minutes=30), "ACCELERATING", True, False),
        ],
    )

    response = client.get(
        "/api/time-series",
        params={
            "tag_ids": [tag_real.id, tag_str.id],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "mode": "recorded",
        },
    )
    assert response.status_code == 200, response.text
    all_series = response.json()["series"]
    assert len(all_series) == 2

    real_series = next(s for s in all_series if s["tag_id"] == tag_real.id)
    str_series = next(s for s in all_series if s["tag_id"] == tag_str.id)

    assert real_series["data_type"] == "REAL"
    assert [p["value"] for p in real_series["points"]] == [1500.5, 1600.0]
    for p in real_series["points"]:
        assert isinstance(p["value"], float)

    assert str_series["data_type"] == "STRING"
    assert [p["value"] for p in str_series["points"]] == ["CRUISING", "ACCELERATING"]
    for p in str_series["points"]:
        assert isinstance(p["value"], str)


@pytest.mark.asyncio
async def test_pi_service_routes_string_tag_to_recorded() -> None:
    provider = MagicMock()
    recorded_response = PiRecordedValues(
        web_id="W123",
        values=[
            PiValue(timestamp=datetime(2026, 9, 1, 0, 10, tzinfo=UTC), value="STEP_2", good=True),
            PiValue(timestamp=datetime(2026, 9, 1, 0, 10, tzinfo=UTC), value="", good=True),
            PiValue(timestamp=datetime(2026, 9, 1, 0, 0, tzinfo=UTC), value="STEP_1", good=True),
        ],
    )
    provider.get_recorded_values = AsyncMock(return_value=recorded_response)
    provider.get_interpolated_values = AsyncMock()

    service = PiService(db=None, provider=provider)
    tag = MagicMock(
        id=99,
        pi_web_id="W123",
        pi_tag_name="PI_STR_TAG",
        display_name="String Tag",
        engineering_unit=None,
        equipment=None,
        section=None,
        variable_type=MagicMock(filter_data_type=VariableFilterDataType.STRING),
        data_type=PiTagDataType.NON_NUMERIC,
    )
    request = TimeSeriesRequest(
        tag_ids=[99],
        start_time=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
        mode="recorded",
    )

    series = await service._fetch_series(tag, request, max_count=1000)

    # Must call get_recorded_values, NOT get_interpolated_values
    provider.get_recorded_values.assert_called_once()
    provider.get_interpolated_values.assert_not_called()
    assert series.data_type == "STRING"
    assert [p.value for p in series.points] == ["STEP_1", "STEP_2", ""]
    assert [p.timestamp for p in series.points] == sorted(p.timestamp for p in series.points)


def test_pi_tags_list_filter_by_data_type(client: TestClient, db_session: Session) -> None:
    _create_string_tag(db_session, "NON_NUM_1")
    _create_numeric_tag(db_session, "NUM_1")

    res_all = client.get("/api/pi-tags")
    assert res_all.status_code == 200
    assert res_all.json()["total"] >= 2

    res_non_numeric = client.get("/api/pi-tags", params={"data_type": "NON_NUMERIC"})
    assert res_non_numeric.status_code == 200
    items = res_non_numeric.json()["items"]
    assert len(items) >= 1
    assert all(item["data_type"] == "NON_NUMERIC" for item in items)

    res_numeric = client.get("/api/pi-tags", params={"data_type": "NUMERIC"})
    assert res_numeric.status_code == 200
    num_items = res_numeric.json()["items"]
    assert len(num_items) >= 1
    assert all(item["data_type"] == "NUMERIC" for item in num_items)


def test_render_sentinel_schema_contract() -> None:
    point = TimeSeriesPoint(
        timestamp=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        value=None,
        good=False,
        is_render_sentinel=True,
    )
    dumped = point.model_dump(mode="json")
    assert dumped["is_render_sentinel"] is True
    assert dumped["good"] is False
    assert dumped["value"] is None
