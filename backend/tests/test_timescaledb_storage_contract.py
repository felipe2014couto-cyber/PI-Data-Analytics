from datetime import datetime, timedelta, timezone

from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.section import Section
from app.models.variable_type import VariableType
from app.services.coverage_service import CoverageService


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
