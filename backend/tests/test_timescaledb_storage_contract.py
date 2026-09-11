import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.section import Section
from app.models.variable_type import VariableType
from app.models.postgres import PiSample
from app.core.exceptions import HistoricalDataNotLoadedError
from app.services.coverage_service import CoverageService
from app.services.database_time_series_service import DatabaseTimeSeriesService
from app.schemas.pi import TimeSeriesRequest
from tests.pi_fakes import FakePiDataProvider


def _tag(db_session):
    equipment = Equipment(code="EQ-TS", name="Timescale")
    variable_type = VariableType(code="VT-TS", name="Numeric")
    db_session.add_all([equipment, variable_type])
    db_session.flush()
    section = Section(equipment_id=equipment.id, code="S1", name="Section")
    db_session.add(section)
    db_session.flush()
    tag = PiTag(
        equipment_id=equipment.id,
        section_id=section.id,
        variable_type_id=variable_type.id,
        pi_server="PI",
        pi_tag_name="TS.TAG",
        display_name="TS.TAG",
        engineering_unit="C",
        data_type=PiTagDataType.NUMERIC,
        active=True,
        pi_web_id="W-TS",
    )
    db_session.add(tag)
    db_session.commit()
    return tag


def test_coverage_is_semi_open_mode_specific_and_consolidated(db_session):
    tag = _tag(db_session)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    middle = start + timedelta(hours=1)
    end = middle + timedelta(hours=1)

    CoverageService.record_coverage(db_session, tag.id, start, middle, "RECORDED")
    CoverageService.record_coverage(db_session, tag.id, middle, end, "RECORDED")
    CoverageService.record_coverage(db_session, tag.id, start, end, "INTERPOLATED", 10)
    db_session.commit()

    assert CoverageService.get_coverage(db_session, tag.id, start, end, "RECORDED") == [(start, end)]
    assert CoverageService.get_coverage(db_session, tag.id, start, end, "INTERPOLATED", 10) == [(start, end)]
    assert CoverageService.get_coverage(db_session, tag.id, start, end, "INTERPOLATED", 1) == []
    assert CoverageService.get_missing_intervals(db_session, tag.id, start, end, "RECORDED") == []


def test_historical_query_reads_timescaledb_and_never_calls_pi(db_session):
    tag = _tag(db_session)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=1)
    provider = FakePiDataProvider()
    db_session.add(PiSample(tag_id=tag.id, ts=start, value_type="double", value_double=1.0, source_mode="RECORDED"))
    db_session.add(PiSample(tag_id=tag.id, ts=end, value_type="double", value_double=2.0, source_mode="RECORDED"))
    CoverageService.record_coverage(db_session, tag.id, start, end, "RECORDED")
    db_session.commit()
    service = DatabaseTimeSeriesService(db_session, provider)

    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    first = loop.run_until_complete(service.fetch_time_series(TimeSeriesRequest(
        tag_ids=[tag.id], start_time=start, end_time=end, mode="recorded"
    )))
    second = loop.run_until_complete(service.fetch_time_series(TimeSeriesRequest(
        tag_ids=[tag.id], start_time=start, end_time=end, mode="recorded"
    )))

    assert [point.timestamp for point in first.series[0].points] == [start]
    assert [point.timestamp for point in second.series[0].points] == [start]
    assert len(provider.recorded_calls) == 0


def test_missing_historical_coverage_is_structured_and_does_not_fallback(db_session):
    tag = _tag(db_session)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=1)
    provider = FakePiDataProvider()
    service = DatabaseTimeSeriesService(db_session, provider)
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    with pytest.raises(HistoricalDataNotLoadedError) as exc:
        loop.run_until_complete(service.fetch_time_series(TimeSeriesRequest(
            tag_ids=[tag.id], start_time=start, end_time=end, mode="recorded"
        )))
    assert exc.value.code == "HISTORICAL_DATA_NOT_LOADED"
    assert exc.value.status_code == 409
    assert exc.value.details["reload_available"] is True
    assert provider.recorded_calls == []
