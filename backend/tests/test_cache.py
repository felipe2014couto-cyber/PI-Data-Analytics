"""Tests for WebId cache and Visual cache."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.pi import (
    QueryExecutionMetadata,
    TimeSeries,
    TimeSeriesPoint,
    TimeSeriesSeries,
)
from app.services.cache import (
    LruCache,
    SingleFlightCache,
    VisualCache,
    VisualCacheKey,
    WebIdCache,
)


def _utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


class TestLruCache:
    def test_set_and_get(self):
        c = LruCache[str, str](max_size=10, default_ttl_seconds=3600)
        c.set("a", "1")
        assert c.get("a") == "1"

    def test_miss_returns_none(self):
        c = LruCache[str, str](max_size=10, default_ttl_seconds=3600)
        assert c.get("missing") is None

    def test_ttl_expiry(self):
        c = LruCache[str, str](max_size=10, default_ttl_seconds=0)
        c.set("a", "1")
        import time
        time.sleep(0.001)
        assert c.get("a") is None

    def test_lru_eviction(self):
        c = LruCache[str, str](max_size=2, default_ttl_seconds=3600)
        c.set("a", "1")
        c.set("b", "2")
        c.set("c", "3")
        assert c.get("a") is None
        assert c.get("b") == "2"
        assert c.get("c") == "3"

    def test_remove(self):
        c = LruCache[str, str](max_size=10, default_ttl_seconds=3600)
        c.set("a", "1")
        c.remove("a")
        assert c.get("a") is None

    def test_size_limit(self):
        c = LruCache[str, str](max_size=5, default_ttl_seconds=3600)
        for i in range(10):
            c.set(str(i), str(i))
        assert c.size <= 5

    def test_clear(self):
        c = LruCache[str, str](max_size=10, default_ttl_seconds=3600)
        c.set("a", "1")
        c.clear()
        assert c.get("a") is None


class TestSingleFlightCache:
    def test_hit_and_miss(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)
        fetch_count = 0

        async def fetcher(key):
            nonlocal fetch_count
            fetch_count += 1
            return "fetched_" + key

        async def run():
            r1 = await c.get_or_fetch("a", fetcher)
            r2 = await c.get_or_fetch("a", fetcher)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 == "fetched_a"
        assert r2 == "fetched_a"
        assert fetch_count == 1

    def test_concurrent_same_key(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)
        results = []
        fetch_count = 0

        async def fetcher(key):
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.01)
            return "val"

        async def getter():
            r = await c.get_or_fetch("k", fetcher)
            results.append(r)

        async def run():
            await asyncio.gather(getter(), getter(), getter())

        asyncio.run(run())
        assert fetch_count == 1
        assert len(results) == 3

    def test_error_not_cached(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)
        call_count = 0

        async def fetcher(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        async def run():
            with pytest.raises(ValueError):
                await c.get_or_fetch("a", fetcher)
            r = await c.get_or_fetch("a", fetcher)
            return r

        r = asyncio.run(run())
        assert r == "ok"
        assert call_count == 2

    def test_peek(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)

        async def fetcher(key):
            return "val"

        asyncio.run(c.get_or_fetch("a", fetcher))
        assert c.peek("a") == "val"
        assert c.peek("missing") is None

    def test_invalidate(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)

        async def fetcher(key):
            return "val"

        asyncio.run(c.get_or_fetch("a", fetcher))
        c.invalidate("a")
        assert c.peek("a") is None

    def test_different_keys_independent(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)

        async def fetcher(key):
            return "v_" + key

        async def run():
            r1 = await c.get_or_fetch("a", fetcher)
            r2 = await c.get_or_fetch("b", fetcher)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 == "v_a"
        assert r2 == "v_b"


class TestWebIdCache:
    def test_hit_and_miss(self):
        c = WebIdCache(max_size=10, default_ttl_seconds=3600)

        async def fetcher(_key):
            return "W-123"

        async def run():
            r1 = await c.resolve("SRV", "\\TAG1", fetcher)
            r2 = await c.resolve("SRV", "\\TAG1", fetcher)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 == "W-123"
        assert r2 == "W-123"

    def test_not_found_not_cached(self):
        c = WebIdCache(max_size=10, default_ttl_seconds=3600)
        call_count = 0

        from app.integrations.pi.errors import PiTagNotFoundError

        async def fetcher(_key):
            nonlocal call_count
            call_count += 1
            raise PiTagNotFoundError()

        async def run():
            r1 = await c.resolve("SRV", "\\TAG", fetcher)
            r2 = await c.resolve("SRV", "\\TAG", fetcher)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 is None
        assert r2 is None
        assert call_count == 2

    def test_auth_error_not_cached(self):
        c = WebIdCache(max_size=10, default_ttl_seconds=3600)
        call_count = 0

        from app.integrations.pi.errors import PiAuthError

        async def fetcher(_key):
            nonlocal call_count
            call_count += 1
            raise PiAuthError()

        async def run():
            with pytest.raises(PiAuthError):
                await c.resolve("SRV", "\\TAG", fetcher)
            with pytest.raises(PiAuthError):
                await c.resolve("SRV", "\\TAG", fetcher)

        asyncio.run(run())
        assert call_count == 2

    def test_invalidate(self):
        c = WebIdCache(max_size=10, default_ttl_seconds=3600)

        async def fetcher(_key):
            return "W-123"

        async def run():
            r = await c.resolve("SRV", "\\TAG", fetcher)
            assert r == "W-123"
            c.invalidate("SRV", "\\TAG")
            r2 = await c.resolve("SRV", "\\TAG", fetcher)
            assert r2 == "W-123"

        asyncio.run(run())

    def test_different_servers_independent(self):
        c = WebIdCache(max_size=10, default_ttl_seconds=3600)

        async def fetcher(key):
            return "W-" + str(hash(key))

        async def run():
            r1 = await c.resolve("SRV1", "\\TAG1", fetcher)
            r2 = await c.resolve("SRV2", "\\TAG1", fetcher)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 != r2


class TestVisualCache:
    def _make_result(self, tag_id=1, num_points=10) -> TimeSeries:
        points = [
            TimeSeriesPoint(
                timestamp=_utc(2026, 7, 1, 0, m, 0), value=float(m)
            )
            for m in range(num_points)
        ]
        series = TimeSeriesSeries(
            tag_id=tag_id,
            tag_name="TAG",
            display_name="TAG",
            points=points,
        )
        return TimeSeries(
            start_time=_utc(2026, 7, 1),
            end_time=_utc(2026, 7, 2),
            mode="interpolated",
            series=[series],
            errors=[],
            query_execution=QueryExecutionMetadata(),
        )

    def _key(self, end_time=None) -> VisualCacheKey:
        if end_time is None:
            end_time = _utc(2026, 7, 1)
        return VisualCacheKey(
            data_server="PIMS",
            tag_ids=(1,),
            web_ids_version="W1",
            start_time=_utc(2026, 7, 1),
            end_time=end_time,
            mode="interpolated",
            interval="1m",
            resolution_mode="manual",
            target_points_per_tag=10000,
            max_visual_points_total=200000,
        )

    def test_hit_no_pi_call(self):
        c = VisualCache(max_entries=10)
        key = self._key()
        result = self._make_result()
        c.store(key, result)
        cached, is_hit = c.peek(key), True
        assert cached is not None
        assert cached.series[0].points[0].value == 0.0

    def test_miss(self):
        c = VisualCache(max_entries=10)
        key = self._key()
        assert c.peek(key) is None

    def test_different_keys_dont_collide(self):
        c = VisualCache(max_entries=10)
        k1 = self._key(end_time=_utc(2026, 7, 1))
        k2 = self._key(end_time=_utc(2026, 7, 2))
        c.store(k1, self._make_result())
        assert c.peek(k2) is None

    def test_large_result_not_stored(self):
        c = VisualCache(max_entries=10, max_points_per_entry=5)
        result = self._make_result(num_points=10)
        c.store(self._key(), result)
        assert c.peek(self._key()) is None

    def test_partial_result_not_stored(self):
        c = VisualCache(max_entries=10)
        result = self._make_result()
        result.series[0].truncated = True
        c.store(self._key(), result)
        assert c.peek(self._key()) is None

    def test_error_not_stored(self):
        c = VisualCache(max_entries=10)
        result = self._make_result()
        result.errors.append({"tag_id": 1, "code": "ERR", "message": "err"})
        c.store(self._key(), result)
        assert c.peek(self._key()) is None

    def test_max_entries_enforced(self):
        c = VisualCache(max_entries=2)
        for i in range(5):
            k = VisualCacheKey(
                data_server="PIMS",
                tag_ids=(i,),
                web_ids_version=f"W{i}",
                start_time=_utc(2026, 7, 1),
                end_time=_utc(2026, 7, 2),
                mode="interpolated",
                interval="1m",
                resolution_mode="manual",
                target_points_per_tag=10000,
                max_visual_points_total=200000,
            )
            c.store(k, self._make_result(tag_id=i))
        assert c.size <= 2

    def test_total_points_limit(self):
        c = VisualCache(max_total_points=15, max_points_per_entry=100)
        for i in range(3):
            k = VisualCacheKey(
                data_server="PIMS",
                tag_ids=(i,),
                web_ids_version=f"W{i}",
                start_time=_utc(2026, 7, 1),
                end_time=_utc(2026, 7, 2),
                mode="interpolated",
                interval="1m",
                resolution_mode="manual",
                target_points_per_tag=10000,
                max_visual_points_total=200000,
            )
            c.store(k, self._make_result(tag_id=i, num_points=10))
        assert c.total_stored_points <= 15

    def test_immutability_deep_copy(self):
        c = LruCache[str, list](max_size=10, default_ttl_seconds=3600)
        original = [1, 2, 3]
        c.set("a", original)
        retrieved = c.get("a")
        retrieved.append(4)
        assert c.get("a") == [1, 2, 3]

    def test_partial_via_query_execution_not_stored(self):
        c = VisualCache(max_entries=10)
        result = self._make_result()
        result.query_execution.partial = True
        c.store(self._key(), result)
        assert c.peek(self._key()) is None

    def test_single_flight_cancelled_leader_recovers(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)
        started = asyncio.Event()
        proceed = asyncio.Event()

        async def slow_fetcher(key):
            started.set()
            await proceed.wait()
            return "done"

        async def leader():
            with pytest.raises(asyncio.CancelledError):
                await c.get_or_fetch("k", slow_fetcher)

        async def follower():
            await started.wait()
            result = await c.get_or_fetch("k", slow_fetcher)
            return result

        async def run():
            task_leader = asyncio.create_task(leader())
            task_follower = asyncio.create_task(follower())
            await asyncio.sleep(0.05)
            task_leader.cancel()
            await asyncio.sleep(0.05)
            proceed.set()
            result = await task_follower
            await task_leader
            return result

        result = asyncio.run(run())
        assert result == "done"

    def test_single_flight_cancelled_follower_ok(self):
        c = SingleFlightCache[str, str](max_size=10, default_ttl_seconds=3600)
        started = asyncio.Event()

        async def slow_fetcher(key):
            started.set()
            await asyncio.sleep(0.3)
            return "done"

        async def run():
            t1 = asyncio.create_task(c.get_or_fetch("k", slow_fetcher))
            await started.wait()
            t2 = asyncio.create_task(c.get_or_fetch("k", slow_fetcher))
            await asyncio.sleep(0.05)
            t2.cancel()
            r1 = await t1
            with pytest.raises(asyncio.CancelledError):
                await t2
            return r1

        result = asyncio.run(run())
        assert result == "done"

    def test_visual_cache_cancelled_leader_recovers(self):
        c = VisualCache(max_entries=10)
        key = self._key()
        started = asyncio.Event()
        proceed = asyncio.Event()

        async def slow_fetcher(k):
            started.set()
            await proceed.wait()
            return self._make_result()

        async def leader():
            with pytest.raises(asyncio.CancelledError):
                await c.get_or_fetch(key, slow_fetcher)

        async def follower():
            await started.wait()
            result, is_hit = await c.get_or_fetch(key, slow_fetcher)
            return result

        async def run():
            t_leader = asyncio.create_task(leader())
            t_follower = asyncio.create_task(follower())
            await asyncio.sleep(0.05)
            t_leader.cancel()
            await asyncio.sleep(0.05)
            proceed.set()
            result = await t_follower
            await t_leader
            return result

        result = asyncio.run(run())
        assert result is not None
        assert result.series[0].points[0].value == 0.0

    def test_streamset_state_concurrent_safety(self):
        from app.services.streamset_client import StreamSetState

        state = StreamSetState()
        results = []

        async def checker():
            for _ in range(50):
                supported = await state.is_supported("recorded")
                if supported:
                    await state.mark_unsupported("recorded")
                else:
                    await state.mark_supported("recorded")
                results.append(supported)

        async def run():
            await asyncio.gather(checker(), checker(), checker())

        asyncio.run(run())
        assert len(results) == 150
