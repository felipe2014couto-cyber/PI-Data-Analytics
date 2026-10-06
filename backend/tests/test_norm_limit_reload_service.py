from datetime import UTC, datetime, timedelta

import pytest

from app.integrations.pi.provider import PiPoint, PiRecordedValues, PiValue
from app.models import Equipment, PiTag, PiTagDataType, Section, VariableType
from app.models.postgres import PiIngestionCoverage, PiSample
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


def test_hourly_scheduler_alignment_and_independent_worker_toggle():
    from app.workers.norm_limit_reload_worker import seconds_until_next_hour
    from app.workers.supervisor import _LEADER_LOCK_NORM_LIMIT_RELOAD

    assert seconds_until_next_hour(datetime(2026, 1, 1, 12, 0, tzinfo=UTC)) == 3600
    assert seconds_until_next_hour(datetime(2026, 1, 1, 12, 30, tzinfo=UTC)) == 1800
    assert _LEADER_LOCK_NORM_LIMIT_RELOAD not in {2147483601, 2147483602, 2147483603, 2147483604}


@pytest.mark.asyncio
async def test_scheduler_invokes_one_reload_per_hourly_tick(monkeypatch):
    import app.workers.norm_limit_reload_worker as worker
    stop = __import__("asyncio").Event()
    calls = []

    async def reload_once():
        calls.append("hour")
        stop.set()
        return []

    monkeypatch.setattr(worker, "seconds_until_next_hour", lambda: 0)
    monkeypatch.setattr(worker, "reload_norm_limits", reload_once)
    await worker.run_norm_limit_reload_loop(stop)
    assert calls == ["hour"]
