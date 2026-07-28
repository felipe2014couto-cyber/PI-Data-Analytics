"""Performance instrumentation utilities.

Uses ``time.perf_counter()`` for monotonic timing. All measurements are
returned as milliseconds. No credentials, headers, or payload values are
logged.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class QueryTimings:
    resolve_ms: float = 0.0
    queue_wait_ms: float = 0.0
    fetch_ms: float = 0.0
    processing_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class CallTiming:
    elapsed_ms: float = 0.0
    retry_count: int = 0


@contextmanager
def measure() -> Generator[CallTiming, None, None]:
    timing = CallTiming()
    start = time.perf_counter()
    try:
        yield timing
    finally:
        timing.elapsed_ms = (time.perf_counter() - start) * 1000


async def measure_async(coro, retries: int = 0):
    timing = CallTiming()
    start = time.perf_counter()
    try:
        result = await coro
        return result, timing
    finally:
        timing.elapsed_ms = (time.perf_counter() - start) * 1000
        timing.retry_count = retries
