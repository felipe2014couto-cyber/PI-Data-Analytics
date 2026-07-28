"""Pure functions for planning temporal queries against the PI Web API.

This module is stateless so it can be unit-tested without fixtures, database,
or HTTP mocks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import TimeRangeInvalidError

SUPPORTED_INTERVALS: List[str] = [
    "1s",
    "5s",
    "10s",
    "30s",
    "1m",
    "5m",
    "10m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "8h",
    "12h",
    "1d",
]

_INTERVAL_SECONDS: List[int] = [
    1,
    5,
    10,
    30,
    60,
    300,
    600,
    900,
    1800,
    3600,
    7200,
    14400,
    28800,
    43200,
    86400,
]

_INTERVAL_MAP = dict(zip(SUPPORTED_INTERVALS, _INTERVAL_SECONDS))


def interval_to_seconds(interval: str) -> int:
    return _INTERVAL_MAP.get(interval, 60)


def seconds_to_interval(total_seconds: int) -> str:
    for idx, secs in enumerate(_INTERVAL_SECONDS):
        if secs >= total_seconds:
            return SUPPORTED_INTERVALS[idx]
    return SUPPORTED_INTERVALS[-1]


@dataclass(frozen=True)
class TimeChunk:
    start_time: datetime
    end_time: datetime
    index: int
    depth: int = 0


@dataclass
class QueryPlan:
    chunks: List[TimeChunk] = field(default_factory=list)
    effective_interval: Optional[str] = None
    estimated_points_per_chunk: int = 0
    total_estimated_points: int = 0
    total_chunks: int = 0
    resolution_mode: str = "automatic"


def validate_period(start_time: datetime, end_time: datetime) -> None:
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    if start_time >= end_time:
        raise TimeRangeInvalidError(
            "A data inicial deve ser menor que a data final.",
            details={
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
    max_days = settings.pi_query_max_period_days
    if (end_time - start_time).total_seconds() > max_days * 86400:
        raise TimeRangeInvalidError(
            f"Periodo excede o maximo de {max_days} dias."
        )


def split_period_into_chunks(
    start_time: datetime,
    end_time: datetime,
    chunk_days: int,
    max_chunks: Optional[int] = None,
    max_depth: int = 0,
) -> List[TimeChunk]:
    if max_chunks is None:
        max_chunks = settings.pi_query_max_chunks
    chunks: List[TimeChunk] = []
    current = start_time
    chunk_delta = timedelta(days=chunk_days)
    index = 0
    while current < end_time:
        chunk_end = min(current + chunk_delta, end_time)
        chunks.append(TimeChunk(
            start_time=current,
            end_time=chunk_end,
            index=index,
            depth=max_depth,
        ))
        current = chunk_end
        index += 1
        if index > max_chunks:
            raise ValueError(
                f"Query would require more than {max_chunks} chunks. "
                "Reduce the period or increase chunk size."
            )
    return chunks


def compute_automatic_interval(
    start_time: datetime,
    end_time: datetime,
    target_points: int,
) -> str:
    duration_seconds = (end_time - start_time).total_seconds()
    if target_points <= 0:
        return SUPPORTED_INTERVALS[-1]
    ideal_interval_seconds = duration_seconds / target_points
    clamped = max(1.0, min(ideal_interval_seconds, 86400.0))
    return seconds_to_interval(int(math.ceil(clamped)))


def compute_interpolated_chunks(
    start_time: datetime,
    end_time: datetime,
    interval: str,
    chunk_days: Optional[int] = None,
) -> List[TimeChunk]:
    if chunk_days is None:
        chunk_days = settings.pi_query_initial_chunk_days
    interval_secs = interval_to_seconds(interval)
    chunk_max_points = settings.pi_query_chunk_max_points

    max_duration_per_chunk = chunk_max_points * interval_secs
    max_chunk_days_duration = timedelta(days=chunk_days)
    chunk_duration = timedelta(seconds=min(
        max_duration_per_chunk,
        int(max_chunk_days_duration.total_seconds()),
    ))

    chunks: List[TimeChunk] = []
    current = start_time
    index = 0
    while current < end_time:
        chunk_end = min(current + chunk_duration, end_time)
        chunks.append(TimeChunk(
            start_time=current,
            end_time=chunk_end,
            index=index,
        ))
        current = chunk_end
        index += 1
        if index > settings.pi_query_max_chunks:
            raise ValueError("Too many interpolated chunks")
    return chunks


def estimate_interpolated_points(
    start_time: datetime,
    end_time: datetime,
    interval: str,
) -> int:
    interval_secs = interval_to_seconds(interval)
    if interval_secs <= 0:
        return 0
    duration_secs = (end_time - start_time).total_seconds()
    return int(duration_secs / interval_secs) + 1


def estimate_recorded_points(
    chunks: List[TimeChunk],
    points_per_chunk: int,
) -> int:
    return len(chunks) * points_per_chunk


def split_chunk(chunk: TimeChunk) -> Tuple[TimeChunk, TimeChunk]:
    midpoint = chunk.start_time + (chunk.end_time - chunk.start_time) / 2
    left = TimeChunk(
        start_time=chunk.start_time,
        end_time=midpoint,
        index=chunk.index,
        depth=chunk.depth + 1,
    )
    right = TimeChunk(
        start_time=midpoint,
        end_time=chunk.end_time,
        index=chunk.index,
        depth=chunk.depth + 1,
    )
    return left, right


def validate_visual_budget(
    tag_count: int,
    target_points_per_tag: int,
) -> Tuple[int, int]:
    max_total = settings.pi_query_visual_max_total_points
    max_per_tag = settings.pi_query_visual_max_points_per_tag
    effective_per_tag = min(target_points_per_tag, max_per_tag)
    total_needed = tag_count * effective_per_tag
    if total_needed > max_total:
        effective_per_tag = max(1000, max_total // tag_count)
        effective_per_tag = min(effective_per_tag, max_per_tag)
    return effective_per_tag, effective_per_tag * tag_count


def build_plan_for_visual(
    tag_count: int,
    start_time: datetime,
    end_time: datetime,
    mode: str,
    resolution_mode: str,
    interval: Optional[str],
    target_points_per_tag: Optional[int],
) -> QueryPlan:
    if target_points_per_tag is None:
        target_points_per_tag = settings.pi_query_visual_default_points_per_tag
    target_points_per_tag = max(
        1000,
        min(target_points_per_tag, settings.pi_query_visual_max_points_per_tag),
    )
    effective_per_tag, _ = validate_visual_budget(tag_count, target_points_per_tag)

    plan = QueryPlan()
    plan.resolution_mode = resolution_mode

    if mode == "interpolated":
        if resolution_mode == "automatic":
            eff_interval = compute_automatic_interval(
                start_time, end_time, effective_per_tag
            )
        else:
            eff_interval = interval or "1m"

        plan.effective_interval = eff_interval
        plan.chunks = compute_interpolated_chunks(
            start_time, end_time, eff_interval
        )
        plan.estimated_points_per_chunk = estimate_interpolated_points(
            start_time, end_time, eff_interval
        )
    else:
        plan.effective_interval = None
        plan.chunks = split_period_into_chunks(
            start_time,
            end_time,
            settings.pi_query_initial_chunk_days,
        )
        plan.estimated_points_per_chunk = settings.pi_query_chunk_max_points

    plan.total_chunks = len(plan.chunks)
    plan.total_estimated_points = plan.total_chunks * plan.estimated_points_per_chunk
    return plan
