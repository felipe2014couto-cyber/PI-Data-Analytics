"""Persistence and invalidation independent of PI and the production database."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.models import Equipment, PiTag, PiTagDataType, PiTagValidationStatus, Section, VariableType, VariableFilterDataType
from app.models.postgres import PiIngestionCoverage
from app.models.production_unit import ProductionUnitMaterialization, ProductionUnitStoredSegment, ProductionUnitTagStats
from app.schemas.production_unit import ProductionUnitAnalysisResponse, ProductionUnitSegment, ProductionUnitVariable
from app.services.production_unit_service import ProductionUnitService
from app.services.production_unit_store import ProductionUnitStore

T = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def stored(db_session, monkeypatch):
    db = db_session
    eq = Equipment(code=uuid4().hex, name="RB1", active=True)
    vt = VariableType(code="UM", name="UM", filter_data_type=VariableFilterDataType.STRING, active=True)
    process_type = VariableType(code="PROCESS", name="Process", filter_data_type=VariableFilterDataType.REAL, active=True)
    db.add_all([eq, vt, process_type]); db.flush()
    def tag(name, kind):
        row = PiTag(equipment_id=eq.id, section_id=None, variable_type_id=vt.id if name == "UM" else process_type.id,
            pi_server="PIMS", pi_tag_name=name, display_name=name, data_type=kind, active=True, validation_status=PiTagValidationStatus.VALID)
        db.add(row); db.flush(); return row
    um = tag("UM", PiTagDataType.NON_NUMERIC)
    numeric = tag("Speed", PiTagDataType.NUMERIC)
    string = tag("Text", PiTagDataType.NON_NUMERIC)
    for row in (um, numeric, string):
        db.add(PiIngestionCoverage(tag_id=row.id, range_start=T, range_end=T+timedelta(hours=1), mode="RECORDED", status="COMPLETE", created_at=T, updated_at=T))
    db.flush()
    segments = []
    for index, code in enumerate(("A", "B", "A", None)):
        variables = []
        for row in (numeric, string):
            value = [0, -2, None, 5][index]
            variables.append(ProductionUnitVariable(tag_id=row.id, tag_name=row.pi_tag_name, display_name=row.display_name,
                data_type=row.data_type.value, sample_count=0 if value is None else 3, raw_sample_count=3, filtered_sample_count=3, excluded_quality_count=0,
                average=value if row.id == numeric.id else None, minimum=value if row.id == numeric.id else None, maximum=value if row.id == numeric.id else None,
                first_value="ON" if row.id == string.id else None, last_value="OFF" if row.id == string.id else None))
        segments.append(ProductionUnitSegment(segment_id=str(index), um_value=code, status="ASSIGNED" if code else "UNASSIGNED",
            start_time=T+timedelta(minutes=index*10), end_time=T+timedelta(minutes=(index+1)*10), duration_seconds=600,
            start_reason="UM_TRANSITION" if code else "UNKNOWN_STATE", end_reason="QUERY_END" if index == 3 else "NEXT_UM", variables=variables))
    response = ProductionUnitAnalysisResponse(equipment_id=eq.id, section_id=None, um_tag_id=um.id, um_tag_name="UM", start_time=T, end_time=T+timedelta(minutes=40), segments=segments)
    def analyze(service, section_id, tag_ids, start, end, **kwargs):
        assert kwargs["use_store"] is False
        selected = []
        for segment in response.segments:
            if segment.start_time >= end or segment.end_time <= start:
                continue
            item = segment.model_copy(deep=True)
            item.start_time = max(start, item.start_time)
            if end < item.end_time:
                item.end_reason = "QUERY_END"
            item.end_time = min(end, item.end_time)
            item.variables = [variable for variable in item.variables if variable.tag_id in tag_ids]
            selected.append(item)
        service.last_aggregate_rows = [dict(segment_index=i, tag_id=v.tag_id, **{f"quality_count_{mask}":3 for mask in range(8)}) for i,s in enumerate(selected) for v in s.variables]
        return response.model_copy(update={"start_time": start, "end_time": end, "segments": selected})
    monkeypatch.setattr(ProductionUnitService, "analyze", analyze)
    store = ProductionUnitStore(db)
    store.rebuild(eq.id, None, [numeric.id, string.id], T, response.end_time)
    return db, store, eq, um, [numeric, string], response


def test_persists_repeated_occurrences_and_open_unassigned_segment(stored):
    db, store, eq, um, tags, response = stored
    occurrences = db.query(ProductionUnitStoredSegment).order_by(ProductionUnitStoredSegment.start_ts).all()
    assert [row.um_value for row in occurrences] == ["A", "B", "A", None]
    assert occurrences[-1].end_ts is None
    assert db.query(ProductionUnitTagStats).count() == 6
    assert db.query(ProductionUnitTagStats).filter_by(tag_id=tags[0].id).order_by(ProductionUnitTagStats.segment_id).first().average == 0


def test_load_uses_stats_preserves_zero_negative_null_and_text_first_last(stored):
    db, store, eq, um, tags, response = stored
    segments, rows = store.load(eq.id, None, um, tags, T, response.end_time, True)
    assert len(segments) == 4
    assert [row['average'] for row in rows if row['tag_id'] == tags[0].id] == [0, -2, None]
    assert all(row['first_value'] == 'ON' and row['last_value'] == 'OFF' for row in rows if row['tag_id'] == tags[1].id)
    assert all(len(row['quality_counts']) == 8 for row in rows)


def test_filters_reuse_structure_but_never_base_stats(stored):
    db, store, eq, um, tags, response = stored
    segments, rows = store.load(eq.id, None, um, tags, T, response.end_time, False)
    assert len(segments) == 4 and not rows


def test_zoom_does_not_use_full_stats_for_clipped_boundary(stored):
    db, store, eq, um, tags, response = stored
    segments, rows = store.load(eq.id, None, um, tags, T+timedelta(minutes=5), T+timedelta(minutes=25), True)
    assert len(segments) == 3 and segments[0].start_reason == "QUERY_START" and segments[-1].end_reason == "QUERY_END"
    assert {row['segment_index'] for row in rows} == {1}


def test_coverage_change_invalidates_only_changed_tag_statistics(stored):
    db, store, eq, um, tags, response = stored
    coverage = db.query(PiIngestionCoverage).filter_by(tag_id=tags[0].id).one()
    coverage.updated_at = T+timedelta(days=1); db.flush()
    segments, rows = store.load(eq.id, None, um, tags, T, response.end_time, True)
    assert len(segments) == 4 and {row['tag_id'] for row in rows} == {tags[1].id}


def test_um_coverage_change_invalidates_structure(stored):
    db, store, eq, um, tags, response = stored
    coverage = db.query(PiIngestionCoverage).filter_by(tag_id=um.id).one()
    coverage.updated_at = T+timedelta(days=1); db.flush()
    assert store.load(eq.id, None, um, tags, T, response.end_time, True) is None


def test_configuration_change_and_other_scope_never_reuse_materialization(stored):
    db, store, eq, um, tags, response = stored
    assert store.load(eq.id, 999, um, tags, T, response.end_time, True) is None
    assert store.load(eq.id, None, SimpleNamespace(id=um.id+999), tags, T, response.end_time, True) is None


def test_refresh_current_window_performs_no_rebuild(stored):
    db, store, eq, um, tags, response = stored
    window = db.query(ProductionUnitMaterialization).one()
    assert store.refresh(window.id) == {"status":"current", "updated":False}


def test_rebuild_is_idempotent(stored):
    db, store, eq, um, tags, response = stored
    store.rebuild(eq.id, None, [row.id for row in tags], T, response.end_time)
    assert db.query(ProductionUnitStoredSegment).count() == 4
    assert db.query(ProductionUnitTagStats).count() == 6
    assert db.query(ProductionUnitMaterialization).count() == 1


def test_incremental_refresh_recalculates_only_affected_tag_and_interval(stored):
    db, store, eq, um, tags, response = stored
    window = db.query(ProductionUnitMaterialization).one()
    modified = datetime.now(timezone.utc) + timedelta(seconds=1)
    db.add(PiIngestionCoverage(tag_id=tags[0].id, range_start=T+timedelta(minutes=11), range_end=T+timedelta(minutes=19), mode="RECORDED", status="COMPLETE", created_at=modified, updated_at=modified))
    db.flush()
    result = store.refresh(window.id)
    assert result["status"] == "incremental"
    assert result["tag_ids"] == [tags[0].id]
    assert result["start"] == (T+timedelta(minutes=10)).isoformat()
    assert result["end"] == (T+timedelta(minutes=20)).isoformat()
    assert db.query(ProductionUnitTagStats).count() == 6
    assert db.query(ProductionUnitMaterialization).count() == 1
    segments, rows = store.load(eq.id, None, um, tags, T, response.end_time, True)
    assert len(segments) == 4 and len(rows) == 6


def test_new_transition_closes_previously_open_occurrence(stored):
    db, store, eq, um, tags, response = stored
    response.segments[-1].end_reason = "NEXT_UM"
    response.segments.append(response.segments[-1].model_copy(update={"segment_id":"new", "um_value":"C", "status":"ASSIGNED", "start_time":T+timedelta(minutes=40), "end_time":T+timedelta(minutes=50), "start_reason":"STATE_RECOVERED", "end_reason":"QUERY_END"}))
    response.end_time = T+timedelta(minutes=50)
    store.rebuild(eq.id, None, [tag.id for tag in tags], T, response.end_time)
    occurrences = db.query(ProductionUnitStoredSegment).order_by(ProductionUnitStoredSegment.start_ts).all()
    assert len(occurrences) == 5
    assert occurrences[3].end_ts is not None and occurrences[4].end_ts is None
    assert db.query(ProductionUnitTagStats).count() == 8


def test_query_end_cut_never_reopens_a_closed_occurrence(stored):
    db, store, eq, um, tags, response = stored
    store.rebuild(eq.id, None, [tag.id for tag in tags], T, T+timedelta(minutes=15))
    occurrence = db.query(ProductionUnitStoredSegment).filter_by(um_tag_id=um.id, start_ts=T+timedelta(minutes=10)).one()
    assert occurrence.end_ts.replace(tzinfo=timezone.utc) == T+timedelta(minutes=20)
    assert occurrence.end_reason == "NEXT_UM"
    assert db.query(ProductionUnitTagStats).filter_by(segment_id=occurrence.id).count() == 2


def test_incremental_um_transition_refreshes_structure_and_all_selected_tags(stored):
    db, store, eq, um, tags, response = stored
    window = db.query(ProductionUnitMaterialization).one()
    previous = response.segments[2]
    new = previous.model_copy(deep=True, update={"segment_id":"new", "start_time":T+timedelta(minutes=25), "um_value":"NEW"})
    previous.end_time = T+timedelta(minutes=25)
    response.segments.insert(3, new)
    modified = datetime.now(timezone.utc) + timedelta(seconds=1)
    db.add(PiIngestionCoverage(tag_id=um.id, range_start=T+timedelta(minutes=25), range_end=T+timedelta(minutes=26), mode="RECORDED", status="COMPLETE", created_at=modified, updated_at=modified))
    db.flush()
    result = store.refresh(window.id)
    assert result["status"] == "incremental" and set(result["tag_ids"]) == {tag.id for tag in tags}
    segments, rows = store.load(eq.id, None, um, tags, T, response.end_time, True)
    assert [segment.um_value for segment in segments] == ["A","B","A","NEW",None]
    assert len(rows) == 8
