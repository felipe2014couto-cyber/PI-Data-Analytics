import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations.pi.provider import PiPoint, PiRecordedValues, PiValue
from app.models import Equipment, PiTag, PiTagDataType, Section, VariableType
from app.models.postgres import PiIngestionCoverage, PiIngestionState, PiSample
from app.services.coverage_service import CoverageService
from app.services.norm_limit_reload_service import _configured_limit_refs, reload_norm_limits
from tests.conftest import TestingSessionLocal

START = datetime(2026, 9, 28, tzinfo=UTC)


def _source(db, name, lower=None, upper=None, *, active=True):
    equipment = Equipment(code=f"E-{name}", name=name)
    vt = VariableType(code=f"V-{name}", name="Numeric")
    db.add_all([equipment, vt]); db.flush()
    section = Section(equipment_id=equipment.id, code=f"S-{name}", name=name)
    db.add(section); db.flush()
    tag = PiTag(equipment_id=equipment.id, section_id=section.id, variable_type_id=vt.id,
                pi_server="PIMS", pi_tag_name=name, display_name=name,
                lower_limit_tag=lower, upper_limit_tag=upper,
                data_type=PiTagDataType.NUMERIC, active=active)
    db.add(tag); db.commit(); return tag


class Provider:
    def __init__(self, events=None, failures=()):
        self.events = events or {}
        self.failures = set(failures)
        self.calls = []
        self.ranges = []

    async def resolve_point(self, path):
        name = path.rsplit("\\", 1)[-1]
        if name in self.failures:
            raise RuntimeError("PI test failure")
        self.calls.append(("resolve", name))
        return PiPoint(f"web-{name}", name)

    async def get_recorded_values_boundary(self, web_id, start, end, *, boundary_type, max_count=None):
        name = web_id.removeprefix("web-")
        self.calls.append((boundary_type, name))
        self.ranges.append((boundary_type, start, end))
        values = self.events.get(name, [])
        if boundary_type == "Outside":
            return PiRecordedValues(web_id, [p for p in values if p.timestamp < start][-1:])
        return PiRecordedValues(web_id, [p for p in values if start <= p.timestamp < end])

    async def get_recorded_values(self, web_id, start, end, max_count=None):
        return await self.get_recorded_values_boundary(web_id, start, end, boundary_type="Inside", max_count=max_count)


@pytest.fixture
def reload_session(monkeypatch):
    import app.services.norm_limit_reload_service as service
    monkeypatch.setattr(service, "SessionLocal", TestingSessionLocal)


def _point(minute, value, *, good=True, questionable=False, substituted=False):
    return PiValue(START + timedelta(minutes=minute), value, good, questionable, substituted)


def test_batch_collects_active_lower_upper_dedupes_and_ignores_empty_or_inactive(db_session):
    _source(db_session, "S1", "LOW", "SHARED")
    _source(db_session, "S2", "SHARED", "  ")
    _source(db_session, "OFF", "IGNORED", None, active=False)
    rows = _configured_limit_refs(db_session)
    assert {(row["pi_server"], row["tag_name"]) for row in rows} == {("PIMS", "LOW"), ("PIMS", "SHARED")}


@pytest.mark.asyncio
async def test_seven_day_reload_includes_seed_and_persists_quality_idempotently(reload_session, monkeypatch):
    import app.services.norm_limit_reload_service as service
    start = START
    end = START + timedelta(days=7)
    monkeypatch.setattr(service, "SessionLocal", TestingSessionLocal)
    with TestingSessionLocal() as db:
        _source(db, "SRC", lower="LOW", upper="UP")
    provider = Provider({
        "LOW": [_point(-1, 2), _point(10, 3, substituted=True), _point(20, 4, good=False)],
        "UP": [_point(-2, 20), _point(30, 21, good=False), _point(40, "Timeout", good=False)],
    })
    results = await reload_norm_limits(provider=provider, now=end)
    assert len(results) == 2 and all(r.status == "COMPLETE" for r in results)
    assert all(r.seeded for r in results)
    assert all(r.samples == 3 for r in results)
    assert set(provider.ranges) == {
        ("Outside", start, start + timedelta(microseconds=1)),
        ("Inside", start, end),
    }
    with TestingSessionLocal() as db:
        samples = db.query(PiSample).all()
        assert len(samples) == 6
        assert sum(not row.good for row in samples) == 3
        assert any(row.substituted for row in samples)
        assert {row.value_text for row in samples if row.value_type == "string"} == {"Timeout"}
        assert db.query(PiIngestionCoverage).count() == 2
        ids = {row.tag_id for row in samples}
    # Repeating the exact same range and events upserts by tag/timestamp.
    await reload_norm_limits(provider=provider, now=end)
    with TestingSessionLocal() as db:
        assert db.query(PiSample).count() == 6
        assert {row.tag_id for row in db.query(PiSample).all()} == ids


@pytest.mark.asyncio
async def test_failure_of_one_limit_tag_does_not_abort_remaining_tags(reload_session):
    with TestingSessionLocal() as db:
        _source(db, "SRC", lower="BROKEN", upper="GOOD")
    provider = Provider({"GOOD": [_point(5, 8)]}, failures={"BROKEN"})
    results = await reload_norm_limits(provider=provider, now=START + timedelta(days=1))
    assert {result.tag_name: result.status for result in results} == {"BROKEN": "FAILED", "GOOD": "COMPLETE"}
    with TestingSessionLocal() as db:
        assert db.query(PiSample).count() == 1


@pytest.mark.asyncio
async def test_empty_recorded_window_is_confirmed_and_persisted_as_coverage(reload_session):
    with TestingSessionLocal() as db:
        _source(db, "EMPTY-SRC", lower="EMPTY-LIMIT")
    results = await reload_norm_limits(provider=Provider(), now=START + timedelta(days=1))
    assert len(results) == 1 and results[0].status == "COMPLETE" and results[0].samples == 0
    with TestingSessionLocal() as db:
        coverage = db.query(PiIngestionCoverage).one()
        assert coverage.status == "EMPTY_CONFIRMED"


@pytest.mark.asyncio
async def test_unconfigured_provider_reports_per_tag_and_empty_batch_is_noop(reload_session):
    with TestingSessionLocal() as db:
        _source(db, "NO-PI-SRC", lower="WAITING")
    results = await reload_norm_limits(provider=None, now=START + timedelta(days=1))
    assert len(results) == 1 and results[0].status == "FAILED"
    assert "PI Web API nao configurada" in results[0].error


def test_configured_limit_save_has_no_reload_or_pi_provider_dependency(db_session):
    from app.services.pi_tag_service import PiTagService
    from app.schemas.pi_tag import PiTagUpdate
    from app.schemas.pi_tag import PiTagCreate
    from app.models.postgres import PiSample

    service = PiTagService(db_session)
    equipment = Equipment(code="E-CREATE-EDIT", name="Create/edit")
    vt = VariableType(code="V-CREATE-EDIT", name="Numeric")
    db_session.add_all([equipment, vt]); db_session.commit()
    before = db_session.query(PiSample).count()
    item = service.create(PiTagCreate(
        equipment_id=equipment.id, variable_type_id=vt.id, pi_server="PIMS",
        pi_tag_name="CREATE-EDIT", display_name="Create/edit", lower_limit_tag="LOW",
    ))
    service.update(item.id, PiTagUpdate(lower_limit_tag="NEW", upper_limit_tag="HIGH"))
    assert db_session.query(PiSample).count() == before


def test_minute_scheduler_alignment_and_independent_worker_toggle():
    from app.workers.norm_limit_reload_worker import seconds_until_next_minute
    from app.workers.supervisor import _LEADER_LOCK_NORM_LIMIT_RELOAD

    assert seconds_until_next_minute(datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC)) == 60
    assert seconds_until_next_minute(datetime(2026, 1, 1, 12, 30, 30, tzinfo=UTC)) == 30
    assert _LEADER_LOCK_NORM_LIMIT_RELOAD not in {2147483601, 2147483602, 2147483603, 2147483604}


@pytest.mark.asyncio
async def test_scheduler_invokes_one_incremental_reload_per_minute_tick(monkeypatch):
    import app.workers.norm_limit_reload_worker as worker
    stop = __import__("asyncio").Event()
    calls = []

    async def reload_once(now=None):
        calls.append(now)
        stop.set()
        return []

    monkeypatch.setattr(worker, "seconds_until_next_minute", lambda: 0)
    monkeypatch.setattr(worker, "run_norm_limit_reload_cycle", reload_once)
    await worker.run_norm_limit_reload_loop(stop)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_scheduler_never_invokes_manual_seven_day_reload_even_at_hour_boundary(monkeypatch):
    import app.workers.norm_limit_reload_worker as worker
    calls = []

    async def incremental(*, now=None):
        calls.append(("incremental", now))
        return []

    monkeypatch.setattr(worker, "reload_norm_limits_incremental", incremental)
    await worker.run_norm_limit_reload_cycle(datetime(2026, 1, 1, 13, 0, tzinfo=UTC))
    await worker.run_norm_limit_reload_cycle(datetime(2026, 1, 1, 13, 1, tzinfo=UTC))
    assert [mode for mode, _ in calls] == ["incremental", "incremental"]


@pytest.mark.asyncio
async def test_incremental_reload_fetches_only_recent_tail_and_is_idempotent(reload_session):
    from app.services.norm_limit_reload_service import reload_norm_limits_incremental

    initial_load_end = START + timedelta(days=7)
    with TestingSessionLocal() as db:
        _source(db, "INCREMENTAL-SRC", lower="INCREMENTAL-LIMIT")
    provider = Provider({
        "INCREMENTAL-LIMIT": [
            _point(-1, 10),
            _point(7 * 24 * 60 - 10, 11),
        ],
    })

    # The explicit seven-day command establishes the materialization watermark.
    first = await reload_norm_limits(provider=provider, now=initial_load_end)
    assert len(first) == 1 and first[0].status == "COMPLETE"
    assert first[0].start == initial_load_end - timedelta(days=7)

    # One minute later, request only the new minute, not seven days or an overlap.
    tail = _point(7 * 24 * 60 + 0.5, 12)
    provider.events["INCREMENTAL-LIMIT"].append(tail)
    now = initial_load_end + timedelta(minutes=1, seconds=20)
    incremental = await reload_norm_limits_incremental(provider=provider, now=now)
    assert len(incremental) == 1 and incremental[0].status == "COMPLETE"
    assert incremental[0].samples == 1
    assert incremental[0].pi_calls == 1
    assert incremental[0].event_calls == 1
    assert incremental[0].seed_calls == 0
    assert incremental[0].resolve_calls == 0
    assert incremental[0].start == initial_load_end
    assert incremental[0].end == initial_load_end + timedelta(minutes=1)
    assert provider.ranges[-1] == (
        "Inside", initial_load_end, initial_load_end + timedelta(minutes=1),
    )

    with TestingSessionLocal() as db:
        assert db.query(PiSample).count() == 3
        watermark_before = _materialized_watermark(db, db.query(PiSample.tag_id).first()[0])

    # A second pass with no new PI event confirms the next empty minute.
    repeated = await reload_norm_limits_incremental(provider=provider, now=now + timedelta(minutes=1))
    assert repeated[0].status == "COMPLETE"
    assert repeated[0].samples == 0
    with TestingSessionLocal() as db:
        assert db.query(PiSample).count() == 3
        watermark_after = _materialized_watermark(db, db.query(PiSample.tag_id).first()[0])
        assert watermark_after == now + timedelta(minutes=1) - timedelta(seconds=20)
        assert watermark_after > watermark_before


@pytest.mark.asyncio
async def test_incremental_catches_up_from_persisted_cursor_in_bounded_minute_batches(reload_session, monkeypatch):
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 3)
    with TestingSessionLocal() as db:
        source = _source(db, "CATCHUP-SRC", lower="CATCHUP-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "CATCHUP-LIMIT", "web-CATCHUP-LIMIT",
        )
        cursor = START + timedelta(minutes=1)
        CoverageService.record_coverage(db, tag_id, START, cursor)
        db.add(PiIngestionState(tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=cursor))
        db.commit()

    provider = Provider({"CATCHUP-LIMIT": [_point(minute, minute) for minute in range(2, 6)]})
    now = START + timedelta(minutes=6, seconds=20)
    first = await reload_norm_limits_incremental(provider=provider, now=now)
    assert first[0].status == "CATCHING_UP"
    assert first[0].start == START + timedelta(minutes=1)
    assert first[0].end == START + timedelta(minutes=4)
    assert len(provider.ranges) == 3
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=4)

    second = await reload_norm_limits_incremental(provider=provider, now=now)
    assert second[0].status == "COMPLETE"
    assert second[0].start == START + timedelta(minutes=4)
    assert second[0].end == START + timedelta(minutes=6)
    assert len(provider.ranges) == 5
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=6)
        assert db.query(PiSample).count() == 4


@pytest.mark.asyncio
async def test_incremental_queries_gap_from_pi_even_if_sample_exists_without_coverage(reload_session):
    from app.services.norm_limit_reload_service import (
        _coverage_gaps_to_cursor, _register_dependency, reload_norm_limits_incremental,
    )

    with TestingSessionLocal() as db:
        source = _source(db, "COVERAGE-REPAIR-SRC", lower="COVERAGE-REPAIR-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "COVERAGE-REPAIR-LIMIT", "web-COVERAGE-REPAIR-LIMIT",
        )
        db.add(PiSample(
            tag_id=tag_id, ts=START + timedelta(minutes=1, seconds=30), source_mode="RECORDED",
            value_type="double", value_double=55, good=True,
        ))
        CoverageService.record_coverage(db, tag_id, START, START + timedelta(minutes=1))
        CoverageService.record_coverage(db, tag_id, START + timedelta(minutes=2), START + timedelta(minutes=3))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=3),
        ))
        db.commit()

    provider = Provider({"COVERAGE-REPAIR-LIMIT": [_point(1.5, 55)]})
    result = await reload_norm_limits_incremental(
        provider=provider, now=START + timedelta(minutes=3, seconds=20),
    )
    assert result[0].status == "COMPLETE"
    assert result[0].pi_calls == 1
    assert provider.ranges == [(
        "Inside", START + timedelta(minutes=1), START + timedelta(minutes=2),
    )]
    with TestingSessionLocal() as db:
        assert _coverage_gaps_to_cursor(db, tag_id, START + timedelta(minutes=3)) == []
        assert db.query(PiSample).count() == 1
        assert CoverageService.get_coverage(db, tag_id, START, START + timedelta(minutes=3)) == [(START, START + timedelta(minutes=3))]

    repeat_provider = Provider()
    repeated = await reload_norm_limits_incremental(
        provider=repeat_provider, now=START + timedelta(minutes=3, seconds=20),
    )
    assert repeated[0].status == "COMPLETE"
    assert repeated[0].pi_calls == 0
    assert repeat_provider.ranges == []
    with TestingSessionLocal() as db:
        assert db.query(PiSample).count() == 1


@pytest.mark.asyncio
async def test_incremental_adopts_contiguous_confirmed_coverage_with_zero_pi_calls(reload_session):
    from app.services.norm_limit_reload_service import (
        _materialized_watermark, _register_dependency, reload_norm_limits_incremental,
    )

    with TestingSessionLocal() as db:
        source = _source(db, "CONTIG-SRC", lower="CONTIG-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "CONTIG-LIMIT", "web-CONTIG-LIMIT",
        )
        CoverageService.record_coverage(db, tag_id, START, START + timedelta(minutes=1))
        CoverageService.record_coverage(db, tag_id, START + timedelta(minutes=1), START + timedelta(minutes=2))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START,
        ))
        db.commit()

    class ForbiddenProvider(Provider):
        async def get_recorded_values(self, *args, **kwargs):
            raise AssertionError("Contiguous coverage adoption must not call PI")

        async def get_recorded_values_boundary(self, *args, **kwargs):
            raise AssertionError("Contiguous coverage adoption must not call PI")

    result = await reload_norm_limits_incremental(
        provider=ForbiddenProvider(), now=START + timedelta(minutes=2, seconds=20),
    )
    assert result[0].status == "COMPLETE"
    assert result[0].pi_calls == 0
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=2)



@pytest.mark.asyncio
async def test_incremental_confirms_empty_coverage_gap_before_tail(reload_session):
    from app.services.coverage_service import CoverageService
    from app.services.norm_limit_reload_service import (
        _coverage_gaps_to_cursor, _register_dependency, reload_norm_limits_incremental,
    )

    with TestingSessionLocal() as db:
        source = _source(db, "EMPTY-GAP-SRC", lower="EMPTY-GAP-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "EMPTY-GAP-LIMIT", "web-EMPTY-GAP-LIMIT",
        )
        CoverageService.record_coverage(db, tag_id, START, START + timedelta(minutes=1))
        CoverageService.record_coverage(db, tag_id, START + timedelta(minutes=2), START + timedelta(minutes=3))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=3),
        ))
        db.commit()

    provider = Provider()
    result = await reload_norm_limits_incremental(
        provider=provider, now=START + timedelta(minutes=3, seconds=20),
    )
    assert result[0].status == "COMPLETE"
    assert provider.ranges == [(
        "Inside", START + timedelta(minutes=1), START + timedelta(minutes=2),
    )]
    with TestingSessionLocal() as db:
        assert _coverage_gaps_to_cursor(db, tag_id, START + timedelta(minutes=3)) == []
        assert db.query(PiIngestionCoverage).filter_by(status="EMPTY_CONFIRMED").count() == 1


def _materialized_watermark(db, tag_id):
    from app.services.norm_limit_reload_service import _materialized_watermark as get_watermark
    return get_watermark(db, tag_id)


@pytest.mark.asyncio
async def test_new_incremental_tag_starts_at_recent_edge_without_historical_seed(reload_session):
    from app.services.norm_limit_reload_service import reload_norm_limits_incremental

    with TestingSessionLocal() as db:
        _source(db, "FIRST-INCREMENTAL", lower="FIRST-LIMIT")
    now = START + timedelta(minutes=3, seconds=15)
    provider = Provider({"FIRST-LIMIT": [_point(1, -999, good=True), _point(2, 8, good=False)]})
    results = await reload_norm_limits_incremental(provider=provider, now=now)

    assert results[0].status == "COMPLETE"
    assert results[0].seeded is False
    assert results[0].seed_calls == 0
    assert results[0].pi_calls == 2  # resolve and one recent RECORDED interval
    assert results[0].start == START + timedelta(minutes=2)
    assert results[0].end == START + timedelta(minutes=3)
    assert results[0].duration_ms >= 0
    with TestingSessionLocal() as db:
        rows = db.query(PiSample).order_by(PiSample.ts).all()
        assert [row.value_double for row in rows] == [8]
        assert [row.good for row in rows] == [False]
        coverage = db.query(PiIngestionCoverage).one()
        state = db.query(PiIngestionState).filter_by(source_mode="NORM_LIMIT").one()
        assert coverage.range_start.replace(tzinfo=UTC) == START + timedelta(minutes=2)
        assert state.watermark_ts.replace(tzinfo=UTC) == START + timedelta(minutes=3)


@pytest.mark.asyncio
async def test_incremental_failure_keeps_watermark_and_does_not_record_coverage(reload_session):
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    with TestingSessionLocal() as db:
        source = _source(db, "FAIL-INCREMENTAL-SRC", lower="FAIL-INCREMENTAL-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "FAIL-INCREMENTAL-LIMIT", "web-FAIL-INCREMENTAL-LIMIT",
        )
        db.add(PiSample(
            tag_id=tag_id, ts=START + timedelta(minutes=1), source_mode="RECORDED",
            value_type="double", value_double=1, good=True,
        ))
        CoverageService.record_coverage(db, tag_id, START, START + timedelta(minutes=2))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=2),
        ))
        db.commit()

    class FailingRecordedProvider(Provider):
        async def get_recorded_values_boundary(self, web_id, start, end, *, boundary_type, max_count=None):
            if boundary_type == "Inside":
                self.ranges.append((boundary_type, start, end))
                raise RuntimeError("PI recorded timeout")
            return await super().get_recorded_values_boundary(web_id, start, end, boundary_type=boundary_type, max_count=max_count)

    provider = FailingRecordedProvider({"FAIL-INCREMENTAL-LIMIT": [_point(1, 1)]})
    result = await reload_norm_limits_incremental(
        provider=provider, now=START + timedelta(minutes=3, seconds=10),
    )
    assert result[0].status == "FAILED"
    assert result[0].pi_calls == 1
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=2)
        assert db.query(PiIngestionCoverage).count() == 1
        state = db.query(PiIngestionState).filter_by(tag_id=tag_id, source_mode="NORM_LIMIT").one()
        assert state.consecutive_failures == 1
        assert state.last_error_code == "RuntimeError"
        assert state.last_error_message == "RuntimeError"
        assert state.next_attempt_at is not None

    resumed_provider = Provider({"FAIL-INCREMENTAL-LIMIT": [_point(2, 2)]})
    resumed = await reload_norm_limits_incremental(
        provider=resumed_provider, now=START + timedelta(minutes=3, seconds=10),
    )
    assert resumed[0].status == "COMPLETE"
    assert resumed[0].start == START + timedelta(minutes=2)
    assert resumed_provider.ranges == [(
        "Inside", START + timedelta(minutes=2), START + timedelta(minutes=3),
    )]
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=3)
        state = db.query(PiIngestionState).filter_by(tag_id=tag_id, source_mode="NORM_LIMIT").one()
        assert state.consecutive_failures == 0
        assert state.next_attempt_at is None


@pytest.mark.asyncio
async def test_incremental_fetches_oldest_gap_before_tail(reload_session, monkeypatch):
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 1)
    with TestingSessionLocal() as db:
        source = _source(db, "GAP-BEFORE-TAIL-SRC", lower="GAP-BEFORE-TAIL-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "GAP-BEFORE-TAIL-LIMIT", "web-GAP-BEFORE-TAIL-LIMIT",
        )
        CoverageService.record_coverage(db, tag_id, START, START + timedelta(minutes=1))
        CoverageService.record_coverage(db, tag_id, START + timedelta(minutes=2), START + timedelta(minutes=3))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=3),
        ))
        db.commit()

    provider = Provider({"GAP-BEFORE-TAIL-LIMIT": [_point(1.5, 99)]})
    now = START + timedelta(minutes=4, seconds=20)
    result = await reload_norm_limits_incremental(provider=provider, now=now)
    assert result[0].status == "CATCHING_UP"
    # Oldest gap (minute 1-2) must be fetched first, NOT recent tail (minute 3-4)
    assert provider.ranges == [(
        "Inside", START + timedelta(minutes=1), START + timedelta(minutes=2),
    )]
    with TestingSessionLocal() as db:
        assert CoverageService.get_coverage(db, tag_id, START, START + timedelta(minutes=3)) == [(START, START + timedelta(minutes=3))]
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=3)


@pytest.mark.asyncio
async def test_old_historical_gap_does_not_block_current_cursor(reload_session, monkeypatch):
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 5)
    now = START + timedelta(days=40)
    with TestingSessionLocal() as db:
        source = _source(db, "OLD-GAP-SRC", lower="OLD-GAP-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "OLD-GAP-LIMIT", "web-OLD-GAP-LIMIT",
        )
        # Old uncovered history followed by complete, current materialization.
        CoverageService.record_coverage(
            db, tag_id, now - timedelta(days=10), now - timedelta(minutes=1),
        )
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=1),
        ))
        db.commit()

    provider = Provider({"OLD-GAP-LIMIT": [PiValue(now - timedelta(seconds=30), 23, True)]})
    result = await reload_norm_limits_incremental(provider=provider, now=now)

    assert result[0].status == "COMPLETE"
    assert result[0].start == now - timedelta(minutes=1)
    assert provider.ranges == [("Inside", now - timedelta(minutes=1), now)]
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == now
        # The older gap remains honestly uncovered; it was not silently
        # converted into COMPLETE or EMPTY_CONFIRMED.
        assert CoverageService.get_missing_intervals(
            db, tag_id, START, now - timedelta(days=10),
        ) == [(START, now - timedelta(days=10))]
        assert db.query(PiIngestionCoverage).filter_by(status="EMPTY_CONFIRMED").count() == 0


@pytest.mark.parametrize("lag", [timedelta(hours=48), timedelta(days=7)])
@pytest.mark.asyncio
async def test_post_materialization_downtime_recovers_incrementally_without_age_cutoff(reload_session, monkeypatch, lag):
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 5)
    monkeypatch.setattr(service.settings, "ingestion_tag_request_budget", 3)
    now = START + timedelta(days=14)
    cursor = now - lag
    baseline = now - timedelta(days=20)
    with TestingSessionLocal() as db:
        source = _source(db, f"DOWNTIME-{int(lag.total_seconds())}", lower=f"DOWNTIME-LIMIT-{int(lag.total_seconds())}")
        tag_name = source.lower_limit_tag
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            tag_name, f"web-{tag_name}",
        )
        CoverageService.record_coverage(db, tag_id, baseline, cursor)
        db.add(PiIngestionState(tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=cursor))
        db.commit()

    provider = Provider()
    result = await reload_norm_limits_incremental(provider=provider, now=now)
    assert result[0].status == "CATCHING_UP"
    assert len(provider.ranges) == 3
    assert provider.ranges[0] == ("Inside", cursor, cursor + timedelta(minutes=1))
    with TestingSessionLocal() as db:
        next_cursor = _materialized_watermark(db, tag_id)
        assert next_cursor == cursor + timedelta(minutes=3)

    # The next worker turn resumes from the persisted point in the outage,
    # even though it began 48h or a week earlier.
    resumed_provider = Provider()
    resumed = await reload_norm_limits_incremental(
        provider=resumed_provider, now=now + timedelta(minutes=1),
    )
    assert resumed[0].status == "CATCHING_UP"
    assert resumed_provider.ranges[0] == ("Inside", next_cursor, next_cursor + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_pre_materialization_gap_is_not_queried_automatically(reload_session, monkeypatch):
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 5)
    now = START + timedelta(days=40)
    current_coverage_start = now - timedelta(hours=24)
    with TestingSessionLocal() as db:
        source = _source(db, "OVER-24H-SRC", lower="OVER-24H-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "OVER-24H-LIMIT", "web-OVER-24H-LIMIT",
        )
        CoverageService.record_coverage(db, tag_id, current_coverage_start, now - timedelta(minutes=1))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=1),
        ))
        db.commit()

    provider = Provider()
    result = await reload_norm_limits_incremental(provider=provider, now=now)
    assert result[0].status == "COMPLETE"
    # Only the current one-minute tail is queried; the old gap before the
    # confirmed materialization baseline remains untouched.
    assert provider.ranges == [("Inside", now - timedelta(minutes=1), now)]


@pytest.mark.asyncio
async def test_rb3_ten_hour_operational_lag_is_recovered_without_manual_backfill(reload_session, monkeypatch):
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 11 * 60)
    monkeypatch.setattr(service.settings, "ingestion_tag_request_budget", 11 * 60)
    now = START + timedelta(days=2)
    cursor = now - timedelta(hours=10)
    with TestingSessionLocal() as db:
        source = _source(db, "RB3-LAG-SRC", lower="RB3-LAG-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "RB3-LAG-LIMIT", "web-RB3-LAG-LIMIT",
        )
        CoverageService.record_coverage(db, tag_id, cursor - timedelta(minutes=1), cursor)
        db.add(PiIngestionState(tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=cursor))
        db.commit()

    provider = Provider()
    result = await reload_norm_limits_incremental(provider=provider, now=now)

    assert result[0].status == "COMPLETE"
    assert result[0].start == cursor
    assert result[0].end == now
    assert len(provider.ranges) == 10 * 60
    assert provider.ranges[0] == ("Inside", cursor, cursor + timedelta(minutes=1))
    assert provider.ranges[-1] == ("Inside", now - timedelta(minutes=1), now)
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == now
        assert CoverageService.get_missing_intervals(db, tag_id, cursor, now) == []


@pytest.mark.asyncio
async def test_empty_interval_with_seed_is_empty_confirmed(reload_session):
    from app.services.norm_limit_reload_service import reload_norm_limits

    with TestingSessionLocal() as db:
        _source(db, "EMPTY-SEED-SRC", lower="EMPTY-SEED-LIMIT")
    now = START + timedelta(minutes=2)
    provider = Provider({
        "EMPTY-SEED-LIMIT": [_point(-7 * 24 * 60 - 10, 42)],
    })
    results = await reload_norm_limits(provider=provider, now=now)
    assert results[0].status == "COMPLETE"
    with TestingSessionLocal() as db:
        coverage = db.query(PiIngestionCoverage).filter_by(mode="RECORDED").first()
        assert coverage is not None
        assert coverage.status == "EMPTY_CONFIRMED"


@pytest.mark.asyncio
async def test_incremental_failure_after_partial_progress_preserves_committed_intervals(reload_session, monkeypatch):
    from datetime import timezone
    import app.services.norm_limit_reload_service as service
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    monkeypatch.setattr(service.settings, "ingestion_tag_budget_minutes", 2)
    with TestingSessionLocal() as db:
        source = _source(db, "PARTIAL-SRC", lower="PARTIAL-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "PARTIAL-LIMIT", "web-PARTIAL-LIMIT",
        )
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START,
        ))
        db.commit()

    class PartialFailingProvider(Provider):
        async def get_recorded_values_boundary(self, web_id, start, end, *, boundary_type, max_count=None):
            if boundary_type == "Inside" and start >= START + timedelta(minutes=1):
                raise RuntimeError("Transient PI failure on second interval")
            return await super().get_recorded_values_boundary(web_id, start, end, boundary_type=boundary_type, max_count=max_count)

    provider = PartialFailingProvider({"PARTIAL-LIMIT": [_point(0.5, 10)]})
    now = START + timedelta(minutes=2, seconds=20)
    result = await reload_norm_limits_incremental(provider=provider, now=now)
    assert result[0].status == "FAILED"
    with TestingSessionLocal() as db:
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=1)
        assert db.query(PiSample).count() == 1
        assert db.query(PiIngestionCoverage).filter_by(tag_id=tag_id, status="COMPLETE").count() == 1
        state = db.query(PiIngestionState).filter_by(tag_id=tag_id, source_mode="NORM_LIMIT").one()
        assert state.watermark_ts.replace(tzinfo=timezone.utc) == START + timedelta(minutes=1)
        assert state.consecutive_failures == 1
        assert state.last_error_code == "RuntimeError"


@pytest.mark.asyncio
async def test_incremental_cancellation_keeps_committed_gap_and_stops_before_next_gap(reload_session):
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    with TestingSessionLocal() as db:
        source = _source(db, "CANCEL-PARTIAL-SRC", lower="CANCEL-PARTIAL-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "CANCEL-PARTIAL-LIMIT", "web-CANCEL-PARTIAL-LIMIT",
        )
        CoverageService.record_coverage(db, tag_id, START, START + timedelta(minutes=1))
        CoverageService.record_coverage(db, tag_id, START + timedelta(minutes=2), START + timedelta(minutes=3))
        db.add(PiIngestionState(
            tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START + timedelta(minutes=3),
        ))
        db.commit()

    class CancelSecondGapProvider(Provider):
        async def get_recorded_values_boundary(self, web_id, start, end, *, boundary_type, max_count=None):
            if boundary_type == "Inside":
                self.ranges.append((boundary_type, start, end))
                if start == START + timedelta(minutes=3):
                    raise asyncio.CancelledError()
                return PiRecordedValues(web_id, [_point(1.5, 77)])
            return await super().get_recorded_values_boundary(
                web_id, start, end, boundary_type=boundary_type, max_count=max_count,
            )

    provider = CancelSecondGapProvider()
    with pytest.raises(asyncio.CancelledError):
        await reload_norm_limits_incremental(
            provider=provider, now=START + timedelta(minutes=4, seconds=20),
        )
    assert provider.ranges == [
        ("Inside", START + timedelta(minutes=1), START + timedelta(minutes=2)),
        ("Inside", START + timedelta(minutes=3), START + timedelta(minutes=4)),
    ]
    with TestingSessionLocal() as db:
        state = db.query(PiIngestionState).filter_by(tag_id=tag_id, source_mode="NORM_LIMIT").one()
        assert _materialized_watermark(db, tag_id) == START + timedelta(minutes=3)
        assert state.consecutive_failures == 1
        assert state.last_error_code == "CancelledError"
        assert state.last_error_message == "CancelledError"
        assert state.next_attempt_at is not None
        assert db.query(PiSample).filter_by(tag_id=tag_id, ts=START + timedelta(minutes=1, seconds=30)).count() == 1
        assert CoverageService.get_coverage(db, tag_id, START, START + timedelta(minutes=4)) == [
            (START, START + timedelta(minutes=3)),
        ]


@pytest.mark.asyncio
async def test_incremental_commit_failure_rolls_back_samples_coverage_and_cursor(reload_session, monkeypatch):
    from sqlalchemy.orm import Session
    from app.services.norm_limit_reload_service import _register_dependency, reload_norm_limits_incremental

    with TestingSessionLocal() as db:
        source = _source(db, "COMMIT-FAIL-SRC", lower="COMMIT-FAIL-LIMIT")
        tag_id = _register_dependency(
            db,
            {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
            "COMMIT-FAIL-LIMIT", "web-COMMIT-FAIL-LIMIT",
        )
        db.add(PiIngestionState(tag_id=tag_id, source_mode="NORM_LIMIT", watermark_ts=START))
        db.commit()

    original_commit = Session.commit
    fail_once = {"enabled": True}

    def fail_interval_commit_once(session):
        if fail_once["enabled"]:
            fail_once["enabled"] = False
            raise RuntimeError("commit failed after interval writes")
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_interval_commit_once)
    provider = Provider({"COMMIT-FAIL-LIMIT": [_point(0.5, 55)]})
    result = await reload_norm_limits_incremental(
        provider=provider, now=START + timedelta(minutes=1, seconds=20),
    )
    assert result[0].status == "FAILED"
    with TestingSessionLocal() as db:
        state = db.query(PiIngestionState).filter_by(tag_id=tag_id, source_mode="NORM_LIMIT").one()
        assert _materialized_watermark(db, tag_id) == START
        assert state.consecutive_failures == 1
        assert state.last_error_code == "RuntimeError"
        assert state.last_error_message == "RuntimeError"
        assert db.query(PiSample).filter_by(tag_id=tag_id).count() == 0
        assert db.query(PiIngestionCoverage).filter_by(tag_id=tag_id).count() == 0
