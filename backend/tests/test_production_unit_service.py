from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.models import (
    Equipment, PiTag, PiTagDataType, PiTagValidationStatus, Section,
    VariableFilterDataType, VariableType,
)
from app.services.production_unit_service import ProductionUnitService, _build_segments


def event(minute, value, *, good=True, questionable=False, substituted=False):
    return SimpleNamespace(
        ts=datetime(2026, 10, 2, 10, minute, tzinfo=timezone.utc),
        value_text=value, value_double=None, value_boolean=None,
        good=good, questionable=questionable, substituted=substituted,
    )


def test_consecutive_repeated_um_values_consolidate_and_reappearing_value_starts_new_segment():
    start = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, 10, 9, tzinfo=timezone.utc)
    segments = _build_segments([
        event(0, "UM_A"), event(1, "UM_A"), event(2, "UM_A"),
        event(5, "UM_B"), event(7, "UM_A"),
    ], start, end)

    assert [(item.value, item.start.minute, item.end.minute) for item in segments] == [
        ("UM_A", 0, 5), ("UM_B", 5, 7), ("UM_A", 7, 9),
    ]
    assert all(left.end == right.start for left, right in zip(segments, segments[1:]))
    assert segments[-1].end_reason == "QUERY_END"


def test_prior_recorded_event_seeds_window_without_moving_query_boundary():
    start = datetime(2026, 10, 2, 10, 3, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, 10, 9, tzinfo=timezone.utc)
    segments = _build_segments([event(0, "UM_A"), event(8, "UM_B")], start, end)

    assert [(item.value, item.start.minute, item.end.minute) for item in segments] == [
        ("UM_A", 3, 8), ("UM_B", 8, 9),
    ]
    assert segments[0].start_reason == "QUERY_START"
    assert segments[0].state_source_timestamp.minute == 0


def test_transition_at_start_belongs_to_new_um_and_end_is_exclusive():
    start = datetime(2026, 10, 2, 10, 3, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, 10, 9, tzinfo=timezone.utc)
    segments = _build_segments([event(0, "UM_A"), event(3, "UM_B"), event(9, "UM_C")], start, end)

    assert [(item.value, item.start.minute, item.end.minute, item.end_reason) for item in segments] == [
        ("UM_B", 3, 9, "NEXT_UM"),
    ]


def test_bad_or_empty_um_state_closes_assignment_until_a_good_state_returns():
    start = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, 10, 8, tzinfo=timezone.utc)
    segments = _build_segments([
        event(0, "UM_A"), event(3, "BAD", good=False), event(5, ""), event(6, "UM_B"),
    ], start, end)

    assert [(item.value, item.status, item.start.minute, item.end.minute, item.end_reason) for item in segments] == [
        ("UM_A", "ASSIGNED", 0, 3, "INVALID_UM_STATE"),
        (None, "UNASSIGNED", 3, 6, "NEXT_UM"),
        ("UM_B", "ASSIGNED", 6, 8, "QUERY_END"),
    ]


def test_questionable_and_substituted_states_are_not_trusted():
    start = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, 10, 3, tzinfo=timezone.utc)
    segments = _build_segments([
        event(0, "UM_A"), event(1, "UM_BAD", questionable=True),
        event(2, "UM_BAD2", substituted=True),
    ], start, end)
    assert [(item.value, item.status, item.start.minute, item.end.minute) for item in segments] == [
        ("UM_A", "ASSIGNED", 0, 1), (None, "UNASSIGNED", 1, 3),
    ]


def make_um_scope(db, *, section_id=None, active=True):
    suffix = uuid4().hex[:8]
    equipment = Equipment(code=f"EQ-{suffix}", name=f"Equipamento {suffix}", active=True)
    variable_type = VariableType(code="UM", name="UM", filter_data_type=VariableFilterDataType.STRING, active=True)
    db.add_all([equipment, variable_type])
    db.flush()
    def add_tag(name, *, tag_section_id=section_id, is_active=active):
        tag = PiTag(
            equipment_id=equipment.id, section_id=tag_section_id, variable_type_id=variable_type.id,
            pi_server="PIMS", pi_tag_name=name, display_name=name, data_type=PiTagDataType.NON_NUMERIC,
            active=is_active, validation_status=PiTagValidationStatus.VALID,
        )
        db.add(tag)
        db.flush()
        return tag
    return equipment, add_tag


def test_resolves_only_active_equipment_wide_um_and_reports_missing_or_ambiguous(db_session):
    equipment, add_tag = make_um_scope(db_session)
    service = ProductionUnitService(db_session)
    first = add_tag("UM_GLOBAL_A")
    assert service.resolve_um_tag(equipment.id, None).id == first.id

    db_session.flush()
    add_tag("UM_GLOBAL_B")
    with pytest.raises(ValidationError, match="ambígua"):
        service.resolve_um_tag(equipment.id, None)


def test_equipment_wide_um_ignores_inactive_and_does_not_choose_a_section_um(db_session):
    equipment, add_tag = make_um_scope(db_session)
    section = Section(equipment_id=equipment.id, code="FORNO", name="Forno", active=True)
    db_session.add(section)
    db_session.flush()
    add_tag("UM_INACTIVE", is_active=False)
    section_tag = add_tag("UM_FORNO", tag_section_id=section.id)
    with pytest.raises(ValidationError, match="equipamento inteiro"):
        ProductionUnitService(db_session).resolve_um_tag(equipment.id, None)
    assert ProductionUnitService(db_session).resolve_um_tag(equipment.id, section.id).id == section_tag.id


def test_specific_section_uses_only_its_um_and_never_falls_back_to_global_or_other_section(db_session):
    equipment, add_tag = make_um_scope(db_session)
    section_a = Section(equipment_id=equipment.id, code="A", name="A", active=True)
    section_b = Section(equipment_id=equipment.id, code="B", name="B", active=True)
    db_session.add_all([section_a, section_b])
    db_session.flush()
    global_tag = add_tag("UM_GLOBAL", tag_section_id=None)
    tag_a = add_tag("UM_A", tag_section_id=section_a.id)
    tag_b = add_tag("UM_B", tag_section_id=section_b.id)
    service = ProductionUnitService(db_session)
    assert service.resolve_um_tag(equipment.id, section_a.id).id == tag_a.id
    assert service.resolve_um_tag(equipment.id, section_b.id).id == tag_b.id
    section_c = Section(equipment_id=equipment.id, code="C", name="C", active=True)
    db_session.add(section_c)
    db_session.flush()
    with pytest.raises(ValidationError, match="esta seção"):
        service.resolve_um_tag(equipment.id, section_c.id)
    assert service.resolve_um_tag(equipment.id, None).id == global_tag.id


def test_section_um_reference_is_respected_and_inactive_reference_is_rejected(db_session):
    equipment, add_tag = make_um_scope(db_session)
    tag = add_tag("UM_ASSIGNED_GLOBAL", tag_section_id=None)
    section = Section(equipment_id=equipment.id, code="A", name="A", active=True, um_tag_id=tag.id)
    db_session.add(section)
    db_session.flush()
    service = ProductionUnitService(db_session)
    assert service.resolve_um_tag(equipment.id, section.id).id == tag.id
    tag.active = False
    db_session.flush()
    with pytest.raises(ValidationError, match="ausente ou inativa"):
        service.resolve_um_tag(equipment.id, section.id)


def test_duplicate_active_ums_in_specific_section_are_an_explicit_configuration_error(db_session):
    equipment, add_tag = make_um_scope(db_session)
    section = Section(equipment_id=equipment.id, code="A", name="A", active=True)
    db_session.add(section)
    db_session.flush()
    add_tag("UM_A", tag_section_id=section.id)
    add_tag("UM_B", tag_section_id=section.id)
    with pytest.raises(ValidationError, match="ambígua"):
        ProductionUnitService(db_session).resolve_um_tag(equipment.id, section.id)
