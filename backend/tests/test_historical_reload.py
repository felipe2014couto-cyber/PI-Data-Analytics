from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import ValidationError
from app.models.equipment import Equipment
from app.models.section import Section
from app.models.variable_type import VariableType
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiBackfillJob
from app.services.historical_reload_service import HistoricalReloadService
from app.schemas.historical_reload import HistoricalReloadRequest


def _tag(db_session) -> PiTag:
    equipment = Equipment(code="RELOAD-EQ", name="Reload")
    variable_type = VariableType(code="RELOAD-VT", name="Numeric")
    db_session.add_all([equipment, variable_type]); db_session.flush()
    section = Section(equipment_id=equipment.id, code="RELOAD-S", name="Reload")
    db_session.add(section); db_session.flush()
    tag = PiTag(
        equipment_id=equipment.id, section_id=section.id, variable_type_id=variable_type.id,
        pi_server="PI", pi_tag_name="RELOAD.TAG", display_name="Reload",
        data_type=PiTagDataType.NUMERIC, active=True,
    )
    db_session.add(tag); db_session.commit(); db_session.refresh(tag)
    return tag


def test_reload_creates_idempotent_missing_job_and_cancel(db_session):
    tag = _tag(db_session)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    payload = HistoricalReloadRequest(start_time=start, end_time=end, tag_id=tag.id)
    service = HistoricalReloadService(db_session)
    first = service.create(payload)
    second = service.create(payload)
    assert len(first) == len(second) == 1
    assert len(db_session.query(PiBackfillJob).all()) == 1
    cancelled = service.cancel(first[0].id)
    assert cancelled.status == "CANCELLED"


def test_reload_rejects_more_than_one_calendar_year(db_session):
    tag = _tag(db_session)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        HistoricalReloadService(db_session).create(HistoricalReloadRequest(
            start_time=start, end_time=start + timedelta(days=367), tag_id=tag.id,
        ))


def test_reload_rejects_future_dates(db_session):
    tag = _tag(db_session)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="no futuro"):
        HistoricalReloadRequest(
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=2),
            tag_id=tag.id,
        )
    with pytest.raises(ValueError, match="no futuro"):
        HistoricalReloadRequest(
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
            tag_id=tag.id,
        )


def test_reload_requires_explicit_timezone():
    with pytest.raises(ValueError):
        HistoricalReloadRequest(
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 2),
            tag_id=1,
        )


def test_reload_unifies_fragmented_coverage_gaps(db_session):
    tag = _tag(db_session)
    from app.models.postgres import PiIngestionCoverage
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    # Minute 1 covered, minute 3 covered -> multiple gaps between 10:00 and 10:05
    c1 = PiIngestionCoverage(tag_id=tag.id, range_start=t0, range_end=t0 + timedelta(minutes=1), mode="RECORDED", status="COMPLETE")
    c2 = PiIngestionCoverage(tag_id=tag.id, range_start=t0 + timedelta(minutes=2), range_end=t0 + timedelta(minutes=3), mode="RECORDED", status="COMPLETE")
    db_session.add_all([c1, c2])
    db_session.commit()

    service = HistoricalReloadService(db_session)
    jobs = service.create(HistoricalReloadRequest(
        start_time=t0,
        end_time=t0 + timedelta(minutes=5),
        tag_id=tag.id,
    ))
    # Must produce exactly 1 continuous job per tag, not fragmented micro-jobs
    assert len(jobs) == 1
    job_start = jobs[0].target_start if jobs[0].target_start.tzinfo is not None else jobs[0].target_start.replace(tzinfo=UTC)
    job_end = jobs[0].target_end if jobs[0].target_end.tzinfo is not None else jobs[0].target_end.replace(tzinfo=UTC)
    assert job_start <= t0 + timedelta(minutes=1)
    assert job_end >= t0 + timedelta(minutes=5)


def test_reload_by_equipment_and_section(db_session):
    tag = _tag(db_session)
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    service = HistoricalReloadService(db_session)

    # Reload by Equipment
    eq_jobs = service.create(HistoricalReloadRequest(
        start_time=t0,
        end_time=t0 + timedelta(hours=2),
        equipment_id=tag.equipment_id,
    ))
    assert len(eq_jobs) == 1
    assert eq_jobs[0].tag_id == tag.id

    # Reload by Section / Zona
    sec_jobs = service.create(HistoricalReloadRequest(
        start_time=t0 + timedelta(hours=3),
        end_time=t0 + timedelta(hours=5),
        section_id=tag.section_id,
    ))
    assert len(sec_jobs) == 1
    assert sec_jobs[0].tag_id == tag.id

