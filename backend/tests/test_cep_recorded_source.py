"""CEP reads the recorded history maintained by the live ingestion worker."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.api.cep import _load_and_materialize, _validate_historical_coverage
from app.core.exceptions import HistoricalDataNotLoadedError
from app.models.cep_variable import CepVariable
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.postgres import PiSample
from app.models.section import Section
from app.models.variable_type import VariableType
from app.schemas.cep_analysis import CepAnalysisRequest, MaterializedTag
from app.services.coverage_service import CoverageService
from app.services.timescale_cep_provider import TimescaleCepProvider


def test_cep_accepts_recorded_coverage_without_legacy_interpolated_coverage(db_session):
    equipment = Equipment(code="CEPREC", name="CEP recorded")
    kind = VariableType(code="CEPREC", name="CEP recorded")
    db_session.add_all([equipment, kind])
    db_session.flush()
    section = Section(equipment_id=equipment.id, code="CEPREC", name="CEP recorded")
    db_session.add(section)
    db_session.flush()
    tags = []
    for name in ("READ", "LOW", "HIGH"):
        tag = PiTag(equipment_id=equipment.id, section_id=section.id,
                    variable_type_id=kind.id, pi_server="PI", pi_tag_name=f"CEPREC.{name}",
                    display_name=name, data_type=PiTagDataType.NUMERIC, active=True)
        db_session.add(tag)
        tags.append(tag)
    db_session.flush()
    db_session.add(CepVariable(equipment_id=equipment.id, section_id=section.id,
                               variable_type_id=kind.id, reading_tag_id=tags[0].id,
                               lower_limit_tag_id=tags[1].id, upper_limit_tag_id=tags[2].id,
                               code="CEPREC", name="CEP recorded", active=True))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    for tag in tags:
        CoverageService.record_coverage(db_session, tag.id, start, end, "RECORDED")
    db_session.commit()
    materialized = _load_and_materialize(db_session, CepAnalysisRequest(
        start_time=start, end_time=end, equipment_id=equipment.id, section_id=section.id,
    ))
    _validate_historical_coverage(db_session, materialized)
    db_session.execute(text("DELETE FROM pi_ingestion_coverage WHERE tag_id = :id"), {"id": tags[0].id})
    db_session.flush()
    with pytest.raises(HistoricalDataNotLoadedError) as exc:
        _validate_historical_coverage(db_session, materialized)
    assert exc.value.details["affected_tags"][0]["mode"] == "recorded"


def test_provider_interpolates_recorded_values_and_preserves_quality(db_session):
    equipment = Equipment(code="SAMPLE", name="Sample")
    kind = VariableType(code="SAMPLE", name="Sample")
    db_session.add_all([equipment, kind])
    db_session.flush()
    section = Section(equipment_id=equipment.id, code="SAMPLE", name="Sample")
    db_session.add(section)
    db_session.flush()
    tag = PiTag(equipment_id=equipment.id, section_id=section.id,
                variable_type_id=kind.id, pi_server="PI", pi_tag_name="SAMPLE.READ",
                display_name="Sample", data_type=PiTagDataType.NUMERIC,
                pi_web_id="SAMPLE.WEB", active=True)
    db_session.add(tag)
    db_session.flush()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add_all([
        PiSample(tag_id=tag.id, ts=start, value_type="double", value_double=10,
                 source_mode="RECORDED", good=True, questionable=False, substituted=False),
        PiSample(tag_id=tag.id, ts=start + timedelta(minutes=10), value_type="double", value_double=20,
                 source_mode="RECORDED", good=True, questionable=True, substituted=False),
    ])
    db_session.commit()
    provider = TimescaleCepProvider(db_session, [MaterializedTag(
        id=tag.id, pi_server=tag.pi_server, pi_tag_name=tag.pi_tag_name, pi_web_id=tag.pi_web_id,
    )])
    result = asyncio.get_event_loop().run_until_complete(provider.get_interpolated_values(
        "SAMPLE.WEB", start, start + timedelta(minutes=15), "5m",
    ))
    assert [point.value for point in result.values] == [10, 15, 20]
    assert [point.questionable for point in result.values] == [False, True, True]
