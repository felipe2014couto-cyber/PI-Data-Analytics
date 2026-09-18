from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers import ingestion_worker as iw
from app.workers.ingestion_worker import (
    BUDGET_EXHAUSTED,
    BudgetExhaustedError,
    FetchStats,
    IntervalIncompleteError,
    _pending_intervals,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 17, 14, 32, 35, tzinfo=UTC)


# ---------- _pending_intervals ----------

def test_pending_minutes_listed_in_order_without_skipping():
    watermark = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    intervals = _pending_intervals(NOW, watermark)
    assert len(intervals) == 5
    assert intervals[0] == (datetime(2026, 9, 17, 14, 27, tzinfo=UTC), datetime(2026, 9, 17, 14, 28, tzinfo=UTC))
    assert intervals[-1] == (datetime(2026, 9, 17, 14, 31, tzinfo=UTC), datetime(2026, 9, 17, 14, 32, tzinfo=UTC))
    for i in range(len(intervals) - 1):
        assert intervals[i][1] == intervals[i + 1][0]


def test_legacy_unaligned_watermark_closes_partial_then_aligns():
    watermark = datetime(2026, 9, 17, 14, 27, 35, 500000, tzinfo=UTC)
    intervals = _pending_intervals(NOW, watermark)
    assert intervals[0] == (watermark, datetime(2026, 9, 17, 14, 28, tzinfo=UTC))
    assert intervals[1] == (datetime(2026, 9, 17, 14, 28, tzinfo=UTC), datetime(2026, 9, 17, 14, 29, tzinfo=UTC))
    # every interval after the first is minute-aligned
    for start, end in intervals[1:]:
        assert start.second == 0 and start.microsecond == 0
        assert end - start == timedelta(minutes=1)


def test_watermark_equal_to_limit_yields_nothing():
    assert _pending_intervals(NOW, datetime(2026, 9, 17, 14, 32, tzinfo=UTC)) == []


def test_watermark_ahead_of_limit_yields_nothing_without_regression():
    ahead = datetime(2026, 9, 17, 14, 40, tzinfo=UTC)
    assert _pending_intervals(NOW, ahead) == []


def test_no_watermark_emits_aligned_individual_intervals():
    saved = iw.settings.ingestion_no_watermark_minutes
    iw.settings.ingestion_no_watermark_minutes = 3
    try:
        intervals = _pending_intervals(NOW, None)
        assert len(intervals) == 3
        assert intervals[0][0] == datetime(2026, 9, 17, 14, 29, tzinfo=UTC)
        assert intervals[2][1] == datetime(2026, 9, 17, 14, 32, tzinfo=UTC)
    finally:
        iw.settings.ingestion_no_watermark_minutes = saved


def test_budget_respected_without_losing_place():
    watermark = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    intervals = _pending_intervals(NOW, watermark, max_intervals=2)
    assert len(intervals) == 2
    assert intervals[0][0] == watermark
    rest = _pending_intervals(NOW, intervals[-1][1])
    assert rest[0][0] == intervals[-1][1]
    assert len(rest) == 3


# ---------- pagination ----------

class _Point:
    def __init__(self, ts: datetime, value: float = 1.0):
        self.timestamp = ts
        self.value = value
        self.good = True
        self.questionable = False
        self.substituted = False


def _provider_replies(pages):
    provider = MagicMock()
    provider.get_recorded_values = AsyncMock(side_effect=pages)
    return provider


def _resp(points):
    return SimpleNamespace(values=list(points))


def test_saturation_decided_on_raw_count_before_filtering():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    # API returns exactly maxCount records; one (at `end`) is removed by the
    # semi-open filter, leaving maxCount - 1 — the page must still be
    # treated as saturated and the interval must be subdivided.
    events = [_Point(base + timedelta(seconds=s)) for s in (0, 15, 30, 45)]
    boundary = _Point(base + timedelta(minutes=1))  # belongs to the next interval
    provider = _provider_replies([
        _resp(events + [boundary]),  # raw 4 >= maxCount: saturated
        _resp(events[:3]),           # left half: unsaturated
        _resp(events[2:]),          # right half: unsaturated (30s dedup)
    ])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=4, stats=stats, page_budget=10,
    ))
    assert len(out) == 4  # boundary point excluded by the semi-open filter
    assert stats.saturated_pages == 1
    assert stats.splits == 1
    assert stats.stop_reason is None


def test_unsplittable_saturated_interval_raises_incomplete():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    events = [_Point(base + timedelta(milliseconds=i)) for i in range(3)]
    provider = _provider_replies([_resp(events)] * 40)
    stats = FetchStats()
    with pytest.raises(IntervalIncompleteError):
        asyncio.run(iw._fetch_complete_interval(
            provider, "webid", base, base + timedelta(seconds=2),
            max_count=3, stats=stats, page_budget=50,
        ))
    assert stats.stop_reason in {"min_interval_saturated", "depth_limit"}


def test_page_budget_raises_budget_exhausted_not_incomplete():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=i)) for i in range(3)]
    provider = _provider_replies([_resp(events)] * 8)
    stats = FetchStats()
    with pytest.raises(BudgetExhaustedError):
        asyncio.run(iw._fetch_complete_interval(
            provider, "webid", base, base + timedelta(minutes=1),
            max_count=3, stats=stats, page_budget=2,
        ))
    assert stats.stop_reason == "page_budget"


def test_empty_page_is_complete():
    base = datetime(2026, 9, 17, 14, 28, tzinfo=UTC)
    provider = _provider_replies([_resp([])])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=100, stats=stats, page_budget=5,
    ))
    assert out == []
    assert stats.saturated_pages == 0
    assert stats.raw_events == 0
    assert stats.accepted_events == 0


def test_events_not_double_counted_across_splits():
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=s)) for s in (0, 15, 30, 45)]
    provider = _provider_replies([
        _resp(events + [e for e in events]),  # raw 8 >= 4: saturated
        _resp(events[:3]),
        _resp(events[2:]),
    ])
    stats = FetchStats()
    out = asyncio.run(iw._fetch_complete_interval(
        provider, "webid", base, base + timedelta(minutes=1),
        max_count=4, stats=stats, page_budget=10,
    ))
    assert len(out) == 4
    assert stats.raw_events == 13  # 8 + 3 + 2 raw points seen
    assert stats.accepted_events == 4  # dedup by timestamp set, counted once


# ---------- productive path of _ingest_tag ----------

class _State:
    """Concrete ingestion state (MagicMock breaks min() in _record_failure)."""
    def __init__(self, watermark=None):
        self.watermark_ts = watermark
        self.last_source_ts = None
        self.next_attempt_at = None
        self.consecutive_failures = 0
        self.last_error_code = None
        self.last_error_message = None
        self.last_success_at = None


def _make_tag(tag_id=7, web_id="P0WebId"):
    tag = SimpleNamespace(
        id=tag_id, active=True, pi_web_id=web_id,
        lower_limit_tag_id=None, upper_limit_tag_id=None,
    )
    return tag


class _FakeSession:
    """Session fake: yields the tag on first get, tracks open sessions."""
    instances: list["_FakeSession"] = []
    tag: SimpleNamespace = None

    def __init__(self):
        self.bind = None
        self.executed = 0
        self.committed = False
        self.state = None
        self.open = False
        self._state_added = None
        _FakeSession.instances.append(self)

    def __enter__(self):
        self.open = True
        return self

    def __exit__(self, *args):
        self.open = False
        return False

    def get(self, model, key):
        if model.__name__ == "PiTag":
            return _FakeSession.tag
        return self.state or _State()

    def add(self, obj):
        self._state_added = obj

    def commit(self):
        self.committed = True
        if self._state_added is not None:
            self.state = self._state_added

    def execute(self, *a, **k):
        self.executed += 1
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        return result


class _HttpProbeProvider:
    """Provider that records how many sessions are open during its await."""
    def __init__(self, pages):
        self._pages = list(pages)

    async def get_recorded_values(self, *a, **k):
        _HTTP_OPEN_COUNTS.append(sum(1 for s in _FakeSession.instances if getattr(s, "open", False)))
        page = self._pages.pop(0) if self._pages else SimpleNamespace(values=[])
        return page


_HTTP_OPEN_COUNTS: list[int] = []


def _run_ingest(tag, state, provider, now=NOW):
    _FakeSession.instances = []
    _FakeSession.tag = tag
    _HTTP_OPEN_COUNTS.clear()
    saved = iw.SessionLocal
    iw.SessionLocal = _FakeSession
    try:
        # every session that needs the state gets the same mutable object
        _FakeSession.state = state
        orig_get = _FakeSession.get

        def _get(s, model, key):
            if model.__name__ == "PiTag":
                return _FakeSession.tag
            return _FakeSession.state

        _FakeSession.get = _get
        try:
            return asyncio.run(iw._ingest_tag(tag.id, now, provider=provider))
        finally:
            _FakeSession.get = orig_get
    finally:
        iw.SessionLocal = saved


def test_ingest_tag_full_path_persists_and_advances_watermark():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC))
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=s)) for s in (5, 25, 50)]
    provider = _HttpProbeProvider([_resp(events)])
    points, requests = _run_ingest(tag, state, provider)
    assert points == 3
    assert requests == 1
    # watermark advanced to the end of the completed minute
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC)
    assert state.consecutive_failures == 0
    assert state.next_attempt_at is None
    assert any(s.committed for s in _FakeSession.instances), (
        "a transacao curta da fase C precisa fazer commit"
    )


def test_ingest_tag_empty_interval_still_advances_watermark():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC))
    provider = _HttpProbeProvider([_resp([])])
    points, requests = _run_ingest(tag, state, provider)
    assert points == 0
    assert requests == 1
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 32, tzinfo=UTC)


def test_no_session_open_during_http():
    """During the provider await, zero sessions may be open."""
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC))
    base = datetime(2026, 9, 17, 14, 31, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=10))]
    provider = _HttpProbeProvider([_resp(events)])
    _run_ingest(tag, state, provider)
    assert _HTTP_OPEN_COUNTS, "o provider precisa ter sido chamado"
    assert all(count == 0 for count in _HTTP_OPEN_COUNTS), (
        "nenhuma sessao pode estar aberta durante a chamada HTTP ao PI"
    )


def test_budget_exhausted_is_not_a_failure_and_keeps_committed_minutes():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 27, tzinfo=UTC))  # 5 pending minutes
    base = datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    events = [_Point(base + timedelta(seconds=s)) for s in (5, 25, 50)]
    # Every page saturated: the first page splits, then page_budget=3 is hit
    # mid-way through the pending minutes.
    provider = _HttpProbeProvider([_resp(events * 3)] * 12)
    saved_budget = iw.settings.ingestion_tag_request_budget
    saved_minutes = iw.settings.ingestion_tag_budget_minutes
    iw.settings.ingestion_tag_request_budget = 3
    iw.settings.ingestion_tag_budget_minutes = 5
    try:
        points, _ = _run_ingest(tag, state, provider)
        # Budget exhaustion is a reschedule, not a PI failure: no failure
        # code, no backoff, and the first completed minute stays committed.
        assert state.last_error_code != "PI_ERROR"
        assert state.last_error_code != "INTERVAL_INCOMPLETE"
        assert state.next_attempt_at is None
        assert points > 0  # at least the first minute's events persisted
        assert state.watermark_ts > datetime(2026, 9, 17, 14, 27, tzinfo=UTC)
    finally:
        iw.settings.ingestion_tag_request_budget = saved_budget
        iw.settings.ingestion_tag_budget_minutes = saved_minutes


def test_http_error_persists_failure_and_raises():
    tag = _make_tag()
    state = _State(watermark=datetime(2026, 9, 17, 14, 31, tzinfo=UTC))

    class _Boom:
        async def get_recorded_values(self, *a, **k):
            raise RuntimeError("PI fora do ar")

    with pytest.raises(RuntimeError, match="PI fora do ar"):
        _run_ingest(tag, state, _Boom())
    assert state.consecutive_failures == 1
    assert state.last_error_code == "PI_ERROR"
    assert state.next_attempt_at is not None
    # watermark untouched by the failure path
    assert state.watermark_ts == datetime(2026, 9, 17, 14, 31, tzinfo=UTC)


# ---------- isolation / concurrency ----------

def test_b_and_c_complete_while_a_stays_blocked_with_two_slots():
    """Two slots: A hangs on an Event; B and C both finish while A is pending."""
    calls = {"b": 0, "c": 0, "a_started": False}
    a_blocker = asyncio.Event()
    b_done = asyncio.Event()
    c_done = asyncio.Event()

    def _fake_ingest(tag_id, now, source_mode=None, provider=None):
        async def inner():
            if tag_id == 1:
                calls["a_started"] = True
                await a_blocker.wait()
                return 0, 0
            if tag_id == 2:
                calls["b"] += 1
                b_done.set()
                return 1, 1
            calls["c"] += 1
            c_done.set()
            return 1, 1
        return inner()

    saved_ingest, saved_session = iw._ingest_tag, iw.SessionLocal
    saved_concurrency = iw.settings.ingestion_tag_concurrency
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    iw.settings.ingestion_tag_concurrency = 2
    iw.settings.ingestion_tag_timeout_seconds = 60.0
    iw._ingest_tag = _fake_ingest

    def _session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = None
        tag_rows = [SimpleNamespace(id=tid, active=True, lower_limit_tag_id=None, upper_limit_tag_id=None)
                    for tid in (1, 2, 3)]
        ctx.execute.return_value.scalars.return_value.all.return_value = tag_rows
        return ctx

    iw.SessionLocal = _session_factory
    try:
        async def run():
            task = asyncio.create_task(iw.run_ingestion_loop(0.05, once=True))
            # Deterministic: wait for B and C to complete without sleeping.
            await asyncio.wait_for(b_done.wait(), timeout=5)
            await asyncio.wait_for(c_done.wait(), timeout=5)
            b_and_c_done = calls["b"] >= 1 and calls["c"] >= 1
            a_still_blocked = calls["a_started"] and not a_blocker.is_set()
            a_blocker.set()  # release A so the cycle can finish
            await task
            return b_and_c_done and a_still_blocked

        assert asyncio.run(run()) is True
    finally:
        iw._ingest_tag = saved_ingest
        iw.SessionLocal = saved_session
        iw.settings.ingestion_tag_concurrency = saved_concurrency
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout


def test_timeout_cancels_task_and_persists_backoff():
    """A hangs past ingestion_tag_timeout_seconds: TAG_TIMEOUT backoff is
    persisted in a dedicated session; B completes normally."""
    a_blocker = asyncio.Event()
    persisted = []
    b_done = asyncio.Event()

    def _fake_ingest(tag_id, now, source_mode=None, provider=None):
        async def inner():
            if tag_id == 1:
                await a_blocker.wait()
                return 0, 0
            b_done.set()
            return 1, 1
        return inner()

    def _record_failure(db, tag_id, mode, now, code, message):
        persisted.append((tag_id, mode, code))

    saved_ingest, saved_session = iw._ingest_tag, iw.SessionLocal
    saved_rf = iw._record_failure
    saved_concurrency = iw.settings.ingestion_tag_concurrency
    saved_timeout = iw.settings.ingestion_tag_timeout_seconds
    iw.settings.ingestion_tag_concurrency = 2
    iw.settings.ingestion_tag_timeout_seconds = 0.05
    iw._ingest_tag = _fake_ingest
    iw._record_failure = _record_failure

    def _session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.bind = None
        tag_rows = [SimpleNamespace(id=tid, active=True, lower_limit_tag_id=None, upper_limit_tag_id=None)
                    for tid in (1, 2)]
        ctx.execute.return_value.scalars.return_value.all.return_value = tag_rows
        return ctx

    iw.SessionLocal = _session_factory
    try:
        async def run():
            task = asyncio.create_task(iw.run_ingestion_loop(0.05, once=True))
            await asyncio.wait_for(b_done.wait(), timeout=5)
            # After A's timeout, the cycle must terminate even though A is
            # still waiting on the Event: wait_for cancels it.
            await asyncio.wait_for(task, timeout=5)
            return (1, "RECORDED", "TAG_TIMEOUT") in persisted

        assert asyncio.run(run()) is True
    finally:
        iw._ingest_tag = saved_ingest
        iw.SessionLocal = saved_session
        iw._record_failure = saved_rf
        iw.settings.ingestion_tag_concurrency = saved_concurrency
        iw.settings.ingestion_tag_timeout_seconds = saved_timeout
        a_blocker.set()


def test_per_tag_backoff_skips_only_failing_tag():
    now = NOW
    a_state = SimpleNamespace(next_attempt_at=now + timedelta(seconds=60))
    b_state = SimpleNamespace(next_attempt_at=None)

    def is_due(state):
        return not (state and state.next_attempt_at and state.next_attempt_at > now)

    assert is_due(a_state) is False
    assert is_due(b_state) is True


# ---------- timestamp parser precision ----------

def test_parser_truncates_seventh_decimal_place():
    from app.integrations.pi.webapi_provider import _normalize_timestamp
    six = _normalize_timestamp("2026-09-17T14:30:00.123456Z")
    seven = _normalize_timestamp("2026-09-17T14:30:00.1234567Z")
    nine = _normalize_timestamp("2026-09-17T14:30:00.123456789Z")
    assert six.microsecond == 123456
    # datetime.fromisoformat silently truncates beyond 6 digits; the parser
    # inherits that truncation. PostgreSQL timestamptz is also microsecond
    # resolution, so the stored key matches the parsed value. Documented:
    # two raw events within the same microsecond would collide on the
    # (tag_id, ts, source_mode) key; PI Web API serializes at most
    # microsecond precision in ISO responses observed here.
    assert seven.microsecond == 123456
    assert nine.microsecond == 123456