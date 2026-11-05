"""Minute-by-minute cursor recovery for norm-limit RECORDED data."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services.norm_limit_reload_service import reload_norm_limits_incremental

logger = logging.getLogger("workers.norm_limits")


def seconds_until_next_minute(now: datetime | None = None) -> float:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return max(0.0, (next_minute - now).total_seconds())


async def run_norm_limit_reload_cycle(now: datetime | None = None):
    """Run one bounded cursor-based RECORDED turn; history is manual-only."""
    return await reload_norm_limits_incremental(now=now)


async def run_norm_limit_reload_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds_until_next_minute())
            return
        except asyncio.TimeoutError:
            pass
        try:
            results = await run_norm_limit_reload_cycle()
            logger.info(
                "norm_limit_reload_worker_cycle tags=%d failed=%d skipped=%d samples=%d pi_calls=%d",
                len(results), sum(item.status == "FAILED" for item in results),
                sum(item.status == "SKIPPED" for item in results),
                sum(item.samples for item in results), sum(item.pi_calls for item in results),
            )
        except Exception:
            logger.exception("norm_limit_reload_cycle_failed")
