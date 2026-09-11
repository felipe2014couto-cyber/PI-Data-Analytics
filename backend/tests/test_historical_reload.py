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
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        HistoricalReloadService(db_session).create(HistoricalReloadRequest(
            start_time=start, end_time=start + timedelta(days=366), tag_id=tag.id,
        ))


def test_reload_requires_explicit_timezone():
    with pytest.raises(ValueError):
        HistoricalReloadRequest(
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 2),
            tag_id=1,
        )
