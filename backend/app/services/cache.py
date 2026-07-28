"""In-memory caches for WebId resolution and visual query results.

WebId cache
-----------
TTL: 24 hours, limit: 10 000 entries, LRU eviction. Handles concurrent
lookups for the same key with single-flight (only one resolution in-flight).

Visual cache
------------
Short-lived cache for fully-processed visual results (merged, sorted,
deduplicated, sampled, with metadata). TTL depends on recency.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar

from app.integrations.pi.errors import (
    PiAuthError,
    PiInvalidResponseError,
    PiRateLimitedError,
    PiTagNotFoundError,
    PiTimeoutError,
    PiUnavailableError,
)
from app.schemas.pi import TimeSeries

logger = logging.getLogger("pi_analytics_data.service.cache")

K = TypeVar("K")
V = TypeVar("V")

_RECENT_WINDOW_SECONDS = 300  # 5 minutes


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    inserted_at: float = field(default_factory=time.monotonic)


class LruCache(Generic[K, V]):
    """Thread-safe LRU cache with TTL.

    Not safe for concurrent mutation across coroutines on its own — use
    ``SingleFlightCache`` for single-key concurrency or wrap in a lock.
    """

    def __init__(self, max_size: int = 10_000, default_ttl_seconds: float = 86400.0):
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._data: OrderedDict[K, CacheEntry] = OrderedDict()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._data.items() if v.expires_at <= now]
        for k in expired:
            del self._data[k]

    def _enforce_max_size(self) -> None:
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def get(self, key: K) -> Optional[V]:
        self._evict_expired()
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return copy.deepcopy(entry.value)

    def set(self, key: K, value: V, ttl_seconds: Optional[float] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = time.monotonic() + ttl
        self._data[key] = CacheEntry(value=value, expires_at=expires_at)
        self._data.move_to_end(key)
        self._evict_expired()
        self._enforce_max_size()

    def remove(self, key: K) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    @property
    def size(self) -> int:
        self._evict_expired()
        return len(self._data)


class SingleFlightCache(Generic[K, V]):
    """Cache with single-flight (request coalescing) for async lookups.

    When multiple coroutines request the same key simultaneously, only one
    ``fetcher`` call runs; the others await the same result.

    ``fetcher`` receives the key and must return ``(value, ttl_seconds)``.
    To signal a miss/error, set ttl to 0 (value won't be cached) or raise.
    """

    def __init__(self, max_size: int = 10_000, default_ttl_seconds: float = 86400.0):
        self._cache = LruCache[K, V](max_size=max_size, default_ttl_seconds=default_ttl_seconds)
        self._in_flight: Dict[K, asyncio.Task] = {}
        self._consumer_counts: Dict[K, int] = {}
        self._lock = asyncio.Lock()

    async def get_or_fetch(
        self,
        key: K,
        fetcher,
        ttl_seconds: Optional[float] = None,
    ) -> V:
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        async with self._lock:
            if key in self._in_flight:
                self._consumer_counts[key] = self._consumer_counts.get(key, 0) + 1
                fetcher_task = self._in_flight[key]
            else:
                loop = asyncio.get_running_loop()
                fetcher_task = loop.create_task(self._run_fetcher(key, fetcher, ttl_seconds))
                self._in_flight[key] = fetcher_task
                self._consumer_counts[key] = 1

        try:
            return await asyncio.shield(fetcher_task)
        except asyncio.CancelledError:
            async with self._lock:
                count = self._consumer_counts.get(key, 0) - 1
                if count <= 0:
                    self._consumer_counts.pop(key, None)
                    if self._in_flight.get(key) is fetcher_task and not fetcher_task.done():
                        fetcher_task.cancel()
                    self._in_flight.pop(key, None)
                else:
                    self._consumer_counts[key] = count
            raise

    async def _run_fetcher(
        self, key: K, fetcher, ttl_seconds: Optional[float] = None
    ) -> V:
        try:
            value = await fetcher(key)
            ttl = ttl_seconds if ttl_seconds is not None else self._cache._default_ttl
            self._cache.set(key, value, ttl_seconds=ttl)
            return value
        except Exception:
            raise
        finally:
            async with self._lock:
                if self._in_flight.get(key) is asyncio.current_task():
                    self._in_flight.pop(key, None)

    def peek(self, key: K) -> Optional[V]:
        return self._cache.get(key)

    def invalidate(self, key: K) -> None:
        self._cache.remove(key)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return self._cache.size


# ---------------------------------------------------------------------------
# WebId cache
# ---------------------------------------------------------------------------

_NEVER_CACHE_ERRORS = (
    PiAuthError,
    PiRateLimitedError,
    PiTimeoutError,
    PiUnavailableError,
    PiInvalidResponseError,
)


def _webid_cache_key(data_server: str, tag_path: str) -> Tuple[str, str]:
    return (data_server, tag_path.replace("/", "\\"))


class WebIdCache:
    """Thread-safe WebId resolution cache with single-flight and invalidation.

    TTL: 24 hours. Limit: 10 000 entries. LRU eviction.
    Never caches auth failures, timeouts, 429s, or unavailable errors.
    """

    def __init__(
        self,
        max_size: int = 10_000,
        default_ttl_seconds: float = 86400.0,
    ):
        self._cache = SingleFlightCache[Tuple[str, str], str](
            max_size=max_size, default_ttl_seconds=default_ttl_seconds
        )

    async def resolve(
        self,
        data_server: str,
        tag_path: str,
        fetcher,
        ttl_seconds: Optional[float] = None,
    ) -> Optional[str]:
        key = _webid_cache_key(data_server, tag_path)
        try:
            return await self._cache.get_or_fetch(key, fetcher, ttl_seconds=ttl_seconds)
        except PiTagNotFoundError:
            self._cache.invalidate(key)
            return None
        except _NEVER_CACHE_ERRORS:
            self._cache.invalidate(key)
            raise

    def peek(self, data_server: str, tag_path: str) -> Optional[str]:
        return self._cache.peek(_webid_cache_key(data_server, tag_path))

    def invalidate(self, data_server: str, tag_path: str) -> None:
        self._cache.invalidate(_webid_cache_key(data_server, tag_path))

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return self._cache.size


# ---------------------------------------------------------------------------
# Visual cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisualCacheKey:
    data_server: str
    tag_ids: Tuple[int, ...]
    web_ids_version: str  # concatenation of web_ids to detect re-resolutions
    start_time: datetime
    end_time: datetime
    mode: str
    interval: Optional[str]
    resolution_mode: str
    target_points_per_tag: int
    max_visual_points_total: int
    sampling_policy_version: str = "streamset-recorded-batch-v1"
    recorded_boundary_type: str = "Inside"
    recorded_window_max_points: int = 10000
    recorded_group_size: int = 10


class VisualCache:
    """Short-lived cache for fully-processed visual query results.

    TTL: 15 seconds for recent results (end_time within 5 minutes of now),
    5 minutes for historical results.

    Max 32 entries, max 500k total stored points, no single entry > 100k points.
    Does not cache errors, partial results, truncated results, or cancelled queries.
    """

    def __init__(
        self,
        max_entries: int = 32,
        max_total_points: int = 500_000,
        max_points_per_entry: int = 100_000,
        recent_ttl_seconds: float = 15.0,
        historical_ttl_seconds: float = 300.0,
        recent_window_seconds: float = 300.0,
    ):
        self._max_entries = max_entries
        self._max_total_points = max_total_points
        self._max_points_per_entry = max_points_per_entry
        self._recent_ttl = recent_ttl_seconds
        self._historical_ttl = historical_ttl_seconds
        self._recent_window = recent_window_seconds
        self._cache = LruCache[VisualCacheKey, TimeSeries](
            max_size=max_entries,
            default_ttl_seconds=historical_ttl_seconds,
        )
        self._total_stored_points = 0
        self._in_flight: Dict[VisualCacheKey, asyncio.Task] = {}
        self._consumer_counts: Dict[VisualCacheKey, int] = {}
        self._lock = asyncio.Lock()

    def _is_recent(self, end_time: datetime) -> bool:
        now = datetime.now(timezone.utc)
        return (now - end_time).total_seconds() < self._recent_window

    def _key_has_recent_window(self, key: VisualCacheKey) -> bool:
        return self._is_recent(key.end_time)

    def _choose_ttl(self, key: VisualCacheKey) -> float:
        return self._recent_ttl if self._is_recent(key.end_time) else self._historical_ttl

    def peek(self, key: VisualCacheKey) -> Optional[TimeSeries]:
        return self._cache.get(key)

    def _count_points(self, result: TimeSeries) -> int:
        return sum(len(s.points) for s in result.series)

    def _evict_for_points(self, needed: int) -> None:
        while self._total_stored_points + needed > self._max_total_points and self._cache.size > 0:
            oldest_key, oldest_entry = next(iter(self._cache._data.items()))
            if oldest_entry is None:
                break
            old_val = oldest_entry.value
            if isinstance(old_val, TimeSeries):
                pts = self._count_points(old_val)
                self._total_stored_points -= pts
            self._cache._data.popitem(last=False)

    def store(self, key: VisualCacheKey, result: TimeSeries) -> None:
        total_points = self._count_points(result)
        if total_points > self._max_points_per_entry:
            logger.info("Visual result too large for cache (%d points)", total_points)
            return
        partial = any(s.truncated for s in result.series)
        has_errors = bool(result.errors)
        is_partial = bool(result.query_execution and result.query_execution.partial)
        if partial or has_errors or is_partial:
            return
        ttl = self._choose_ttl(key)
        self._evict_for_points(total_points)
        self._cache.set(key, result, ttl_seconds=ttl)
        self._total_stored_points += total_points

    async def get_or_fetch(
        self, key: VisualCacheKey, fetcher
    ) -> Tuple[Optional[TimeSeries], bool]:
        cached = self._cache.get(key)
        if cached is not None:
            return cached, True

        async with self._lock:
            if key in self._in_flight:
                self._consumer_counts[key] = self._consumer_counts.get(key, 0) + 1
                fetcher_task = self._in_flight[key]
            else:
                loop = asyncio.get_running_loop()
                fetcher_task = loop.create_task(self._run_fetcher(key, fetcher))
                self._in_flight[key] = fetcher_task
                self._consumer_counts[key] = 1

        try:
            result = await asyncio.shield(fetcher_task)
            return result, False
        except asyncio.CancelledError:
            async with self._lock:
                count = self._consumer_counts.get(key, 0) - 1
                if count <= 0:
                    self._consumer_counts.pop(key, None)
                    if self._in_flight.get(key) is fetcher_task and not fetcher_task.done():
                        fetcher_task.cancel()
                    self._in_flight.pop(key, None)
                else:
                    self._consumer_counts[key] = count
            raise

    async def _run_fetcher(
        self, key: VisualCacheKey, fetcher
    ) -> Optional[TimeSeries]:
        try:
            result = await fetcher(key)
            self.store(key, result)
            return result
        except Exception:
            raise
        finally:
            async with self._lock:
                if self._in_flight.get(key) is asyncio.current_task():
                    self._in_flight.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()
        self._total_stored_points = 0

    @property
    def size(self) -> int:
        return self._cache.size

    @property
    def total_stored_points(self) -> int:
        return self._total_stored_points
