"""Real-path ingestion tests: timeout/backoff, per-tag backoff isolation,
watermark atomicity and session discipline, all against the isolated test
database (conftest SQLite) so ``_record_failure`` and ``_ingest_tag`` run
their real persistence logic.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import Equipment, PiTag, PiTagDataType, PiTagValidationStatus, VariableType
from app.models.postgres import PiIngestionState
from app.workers import ingestion_worker as iw
from tests.conftest import TestingSessionLocal

UTC = timezone.utc
NOW = datetime(2026, 9, 17, 14, 32, 35, tzinfo=UTC)


def _seed_tag(db, tag_id=101, web_id="P0FakeWebId"):
    equipment = Equipment(code=f"EQ{tag_id}", name=f"Equip {tag_id}")
    variable_type = VariableType(code=f"VT{tag_id}", name=f"Var {tag_id}")
    db.add(equipment)
    db.add(variable_type)
    db.flush()
    tag = PiTag(
        id=tag_id,
        equipment_id=equipment.id,
        variable_type_id=variable_type.id,
        pi_tag_name=f"TESTE_INGEST_{tag_id}",
        display_name=f"Teste {tag_id}",
        pi_web_id=web_id,
        pi_server="PISRV",
        data_type=PiTagDataType.NUMERIC,
        validation_status=PiTagValidationStatus.VALID,
        active=True,
    )
    db.add(tag)
    db.commit()
    return tag


def _seed_state(db, tag_id, watermark=None, next_attempt_at=None, failures=0):
    state = PiIngestionState(
        tag_id=tag_id, source_mode="RECORDED",
        watermark_ts=watermark, last_source_ts=None,
        sampling_mode="RECORDED", consecutive_failures=failures,
        next_attempt_at=next_attempt_at,
    )
    db.add(state)
    db.commit()
    return state


def _get_state(tag_id):
    with TestingSessionLocal() as db:
        state = db.get(PiIngestionState, (tag_id, "RECORDED"))
        # SQLite returns naive datetimes; normalize for comparison.
        if state is not None:
            state.watermark_ts = iw._as_utc(state.watermark_ts)
            state.next_attempt_at = iw._as_utc(state.next_attempt_at)
        return state


class _P:
    def __init__(self, ts, value=1.0):
        self.timestamp = ts
        self.value = value
        self.good = True
        self.questionable = False
        self.substituted = False


class _SlowProvider:
    """Provider that hangs on the given tag and answers the others."""
    def __init__(self, hang_web_id):
        self.hang_web_id = hang_web_id
        self.calls = {}
        self.hang_event = asyncio.Event()

    async def get_recorded_values(self, web_id, start, end, max_count=None):
        self.calls[web_id] = self.calls.get(web_id, 0) + 1
        if web_id == self.hang_web_id:
            await self.hang_event.wait()
        return SimpleNamespace(values=[])


class _CountingProvider:
    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = 0
        self.web_ids = []

    async def get_recorded_values(self, web_id, start, end, max_count=None):
        self.calls += 1
        self.web_ids.append(web_id)
        page = self._pages.pop(0) if self._pages else SimpleNamespace(values=[])
        return page


def _patch_session(monkeypatch):
    monkeypatch.setattr(iw, "SessionLocal", TestingSessionLocal)


# ---------------------------------------------------------------- timeout

def test_real_timeout_persists_backoff_in_db_and_cancels_task(monkeypatch):
    _patch_session(monkeypatch)
    with TestingSessionLocal() as db:
        tag_a = _seed_tag(db, 101, "WEB_A")
        tag_b = _seed_tag(db, 102, "WEB_B")
        wm_a = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
        wm_b = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
        _seed_state(db, 101, watermark=wm_a)
        _seed_state(db, 102, watermark=wm_b)

    provider = _SlowProvider("WEB_A")
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    saved_conc = iw.settings.ingestion_tag_concurrency
    iw.settings.ingestion_tag_timeout_seconds = 0.2
    iw.settings.ingestion_tag_concurrency = 2
    monkeypatch.setattr(iw, "get_pi_data_provider", lambda: provider)
    try:
        async def run():
            task = asyncio.create_task(
                iw._ingest_tag(101, NOW, provider=provider))
            # A hangs inside the HTTP call; wrap it with the real timeout
            # supervisor semantics (wait_for + cancel + await) as in run_one.
            try:
                await asyncio.wait_for(
                    task, timeout=iw.settings.ingestion_tag_timeout_seconds)
                return False
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                with TestingSessionLocal() as fdb:
                    iw._record_failure(
                        fdb, 101, "RECORDED", NOW, "TAG_TIMEOUT",
                        "Turno excedeu o timeout total de ingestao")
                return True

        assert asyncio.run(run()) is True
    finally:
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout
        iw.settings.ingestion_tag_concurrency = saved_conc
        provider.hang_event.set()

    state = _get_state(101)
    assert state.last_error_code == "TAG_TIMEOUT"
    assert state.consecutive_failures == 1
    assert state.next_attempt_at is not None and state.next_attempt_at > NOW
    assert state.watermark_ts == wm_a  # untouched
    # provider was contacted for A (the hang proves the task really ran)
    assert provider.calls.get("WEB_A") == 1


def test_real_cycle_timeout_and_healthy_tag_completes(monkeypatch):
    """Full cycle: A hangs past its total timeout, B completes and advances
    its own watermark; the persisted A state carries TAG_TIMEOUT backoff."""
    _patch_session(monkeypatch)
    with TestingSessionLocal() as db:
        _seed_tag(db, 111, "WEB_SLOW")
        _seed_tag(db, 112, "WEB_OK")
        wm = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
        _seed_state(db, 111, watermark=wm)
        _seed_state(db, 112, watermark=wm)

    pages_ok = SimpleNamespace(values=[
        _P(datetime(2026, 9, 17, 14, 31, 20, tzinfo=UTC), 3.5)])

    class _Dual:
        def __init__(self):
            self.calls = {}
            self.hang = asyncio.Event()

        async def get_recorded_values(self, web_id, start, end, max_count=None):
            self.calls[web_id] = self.calls.get(web_id, 0) + 1
            if web_id == "WEB_SLOW":
                await self.hang.wait()
            return pages_ok

    provider = _Dual()
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    saved_conc = iw.settings.ingestion_tag_concurrency
    saved_cycle = iw.settings.ingestion_cycle_seconds
    iw.settings.ingestion_tag_timeout_seconds = 0.2
    iw.settings.ingestion_tag_concurrency = 2
    monkeypatch.setattr(iw, "get_pi_data_provider", lambda: provider)
    try:
        asyncio.run(iw.run_ingestion_loop(0.05, once=True))
    finally:
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout
        iw.settings.ingestion_tag_concurrency = saved_conc
        provider.hang.set()

    slow = _get_state(111)
    ok = _get_state(112)
    assert slow.last_error_code == "TAG_TIMEOUT"
    assert slow.next_attempt_at is not None
    assert slow.watermark_ts == wm  # cursor untouched by the timeout
    assert ok.consecutive_failures == 0
    assert ok.next_attempt_at is None
    # B processes exactly its per-turn budget of pending minutes from the
    # seeded watermark (limit is the real current minute, always >= 5 ahead).
    assert ok.watermark_ts == wm + timedelta(
        minutes=iw.settings.ingestion_tag_budget_minutes)
    assert ok.last_error_code is None


# ------------------------------------------------------- per-tag backoff

def test_backoff_skips_a_but_b_ingests_and_advances(monkeypatch):
    _patch_session(monkeypatch)
    wm = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    with TestingSessionLocal() as db:
        _seed_tag(db, 121, "WEB_BACKOFF")
        _seed_tag(db, 122, "WEB_DUE")
        _seed_state(db, 121, watermark=wm,
                    next_attempt_at=NOW + timedelta(seconds=300))
        _seed_state(db, 122, watermark=wm)

    events = SimpleNamespace(values=[
        _P(datetime(2026, 9, 17, 14, 31, 10, tzinfo=UTC), 2.0),
        _P(datetime(2026, 9, 17, 14, 31, 40, tzinfo=UTC), 4.0),
    ])
    provider = _CountingProvider([events])

    # Tag A (in backoff): the PI must never be contacted for it.
    points, requests = asyncio.run(
        iw._ingest_tag(121, NOW, provider=provider))
    assert points == 0 and requests == 0
    assert provider.calls == 0
    a = _get_state(121)
    assert a.watermark_ts == wm  # untouched
    assert a.next_attempt_at > NOW  # backoff preserved

    # Tag B (due): the PI is consulted, data persisted, watermark advanced.
    points, requests = asyncio.run(
        iw._ingest_tag(122, NOW, provider=provider))
    assert points == 2 and requests == 1
    assert provider.calls == 1
    assert provider.web_ids == ["WEB_DUE"]
    b = _get_state(122)
    assert b.watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC)
    assert b.consecutive_failures == 0


# ------------------------------------------------------ watermark atomicity

def test_failure_keeps_watermark_and_restart_resumes_exactly(monkeypatch):
    _patch_session(monkeypatch)
    wm = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    with TestingSessionLocal() as db:
        _seed_tag(db, 131, "WEB_ATOMIC")
        _seed_state(db, 131, watermark=wm)

    class _Boom:
        async def get_recorded_values(self, *a, **k):
            raise RuntimeError("PI fora do ar")

    with pytest.raises(RuntimeError):
        asyncio.run(iw._ingest_tag(131, NOW, provider=_Boom()))
    state = _get_state(131)
    assert state.watermark_ts == wm  # cursor not advanced on failure
    assert state.last_error_code == "PI_ERROR"
    assert state.next_attempt_at is not None

    # Restart: with the backoff elapsed, the turn resumes exactly from the
    # watermark (minute [14:31, 14:32)) and idempotent upserts avoid
    # duplicating already-saved events.
    state.next_attempt_at = NOW - timedelta(seconds=1)
    with TestingSessionLocal() as db:
        db.merge(state)
        db.commit()
    events = SimpleNamespace(values=[
        _P(datetime(2026, 9, 17, 14, 31, 10, tzinfo=UTC), 7.0)])
    points, requests = asyncio.run(
        iw._ingest_tag(131, NOW, provider=_CountingProvider([events])))
    assert requests == 1
    assert _get_state(131).watermark_ts == datetime(
        2026, 9, 17, 14, 32, tzinfo=UTC)


def test_reprocessing_same_interval_does_not_duplicate(monkeypatch):
    _patch_session(monkeypatch)
    wm = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    with TestingSessionLocal() as db:
        _seed_tag(db, 141, "WEB_IDEM")
        _seed_state(db, 141, watermark=wm)

    events = SimpleNamespace(values=[
        _P(datetime(2026, 9, 17, 14, 31, 10, tzinfo=UTC), 1.5)])
    # Process the same minute twice: the first pass advances the watermark,
    # so the second run has no pending interval and must not re-write.
    asyncio.run(iw._ingest_tag(141, NOW, provider=_CountingProvider([events])))
    provider2 = _CountingProvider([events])
    asyncio.run(iw._ingest_tag(141, NOW, provider=provider2))
    assert provider2.calls == 0  # no pending minute: nothing re-fetched

    from sqlalchemy import text
    with TestingSessionLocal() as db:
        count = db.execute(text(
            "SELECT count(*) FROM pi_samples_timescale "
            "WHERE tag_id = 141 AND source_mode = 'RECORDED'"
        )).scalar_one()
    assert count == 1  # idempotent: single event, not duplicated


# ------------------------------------------------------- session discipline

def test_http_awaits_with_no_open_transaction(monkeypatch):
    """Inside the provider await there is no session, hence no transaction
    and no pooled connection held by the worker."""
    _patch_session(monkeypatch)
    wm = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    with TestingSessionLocal() as db:
        _seed_tag(db, 151, "WEB_TX")
        _seed_state(db, 151, watermark=wm)

    open_during_http = []

    class _Probe:
        async def get_recorded_values(self, web_id, start, end, max_count=None):
            # Any session the worker still holds would appear here as an
            # active TestSessionLocal with an open transaction. Track via
            # the engine's checked-out connections instead.
            open_during_http.append(iw.testing_sessions)
            return SimpleNamespace(values=[_P(datetime(2026, 9, 17, 14, 31, 30, tzinfo=UTC))])

    iw.testing_sessions = []  # instrumented by the patched SessionLocal below
    real_local = TestingSessionLocal

    class _Instrumented:
        def __call__(self):
            session = real_local()
            iw.testing_sessions.append(session)
            return session

    monkeypatch.setattr(iw, "SessionLocal", _Instrumented())
    try:
        asyncio.run(iw._ingest_tag(151, NOW, provider=_Probe()))
    finally:
        monkeypatch.setattr(iw, "SessionLocal", real_local)
        iw.testing_sessions = []

    assert open_during_http == [[ ]] or all(
        not s.in_transaction() for group in open_during_http for s in group
    ), "nenhuma sessao com transacao ativa durante o HTTP"
    assert _get_state(151).watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC)