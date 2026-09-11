import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import ConflictError
from app.models.cep_variable import CepVariable
from app.models.cep_variable_tag_dependency import CepVariableTagDependency
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType, PiTagKind
from app.models.section import Section
from app.models.variable_type import VariableType
from app.services.cep_dependency_service import CepDependencyService
from app.services.historical_reload_service import HistoricalReloadService
from app.services.pi_tag_service import PiTagService
from app.schemas.historical_reload import HistoricalReloadRequest
from tests.pi_fakes import FakePiDataProvider
from app.integrations.pi.provider import PiPoint


def _configuration(db_session):
    equipment = Equipment(code="DEP-EQ", name="Dependency equipment")
    section = Section(code="DEP-S", name="Dependency section", equipment=equipment)
    variable_type = VariableType(code="DEP-VT", name="Numeric")
    owner = PiTag(
        equipment=equipment,
        section=section,
        variable_type=variable_type,
        pi_server="PI",
        pi_tag_name="READING",
        lower_limit_tag="LOW",
        upper_limit_tag="UP",
        display_name="Reading",
        data_type=PiTagDataType.NUMERIC,
    )
    db_session.add_all([equipment, section, variable_type, owner])
    db_session.flush()
    variable = CepVariable(
        equipment_id=equipment.id,
        section_id=section.id,
        variable_type_id=variable_type.id,
        reading_tag_id=owner.id,
        lower_limit_tag_id=owner.id,
        upper_limit_tag_id=owner.id,
        code="DEP-1",
        name="Dependency variable",
    )
    db_session.add(variable)
    db_session.commit()
    return variable, owner


def _provider():
    return FakePiDataProvider(points={
        "\\\\PI\\LOW": PiPoint(web_id="web-low", name="LOW"),
        "\\\\PI\\UP": PiPoint(web_id="web-up", name="UP"),
    })


def test_reconcile_grouped_dependencies_is_idempotent_and_shared(db_session):
    variable, _ = _configuration(db_session)
    provider = _provider()
    service = CepDependencyService(db_session)

    first = asyncio.run(service.reconcile(provider))
    second = asyncio.run(service.reconcile(provider))

    assert first["created"] == 2
    assert second["created"] == 0
    assert len(provider.resolve_calls) == 2
    assert db_session.query(CepVariableTagDependency).count() == 2
    assert db_session.query(PiTag).filter(PiTag.tag_kind == PiTagKind.DEPENDENCY).count() == 2
    assert len({row.tag_id for row in db_session.query(CepVariableTagDependency).all()}) == 2


def test_dependency_is_included_in_variable_reload_and_not_common_tag_list(db_session):
    variable, owner = _configuration(db_session)
    asyncio.run(CepDependencyService(db_session).reconcile(_provider()))
    start = datetime(2025, 1, 1, tzinfo=UTC)
    jobs = HistoricalReloadService(db_session).create(HistoricalReloadRequest(
        start_time=start, end_time=start + timedelta(hours=1), variable_id=variable.id,
    ))
    assert {job.tag_id for job in jobs} == {owner.id, *(row.tag_id for row in db_session.query(CepVariableTagDependency).all())}
    assert db_session.query(PiTag).filter(PiTag.tag_kind == PiTagKind.PRIMARY).count() == 1


def test_removing_one_reference_keeps_shared_dependency_safe(db_session):
    variable, owner = _configuration(db_session)
    asyncio.run(CepDependencyService(db_session).reconcile(_provider()))
    owner.lower_limit_tag = None
    db_session.commit()
    asyncio.run(CepDependencyService(db_session).reconcile(_provider()))
    assert db_session.query(CepVariableTagDependency).filter_by(dependency_type="LOWER_LIMIT").count() == 0
    upper = db_session.query(CepVariableTagDependency).filter_by(dependency_type="UPPER_LIMIT").one()
    with pytest.raises(ConflictError):
        PiTagService(db_session).delete(upper.tag_id)


def test_invalid_dependency_is_recorded_without_historical_fetch(db_session):
    variable, _ = _configuration(db_session)
    provider = FakePiDataProvider()
    report = asyncio.run(CepDependencyService(db_session).reconcile(provider))
    relation = db_session.query(CepVariableTagDependency).filter_by(variable_id=variable.id, dependency_type="LOWER_LIMIT").one()
    assert report["invalid"] == 2
    assert relation.status == "INVALID"
    assert relation.tag_id is None
    assert provider.recorded_calls == []
    assert provider.interpolated_calls == []
