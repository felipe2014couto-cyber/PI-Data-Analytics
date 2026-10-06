"""Hourly scheduler for visual norm-limit RECORDED materialization."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services.norm_limit_reload_service import reload_norm_limits

logger = logging.getLogger("workers.norm_limits")


def seconds_until_next_hour(now: datetime | None = None) -> float:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(0.0, (next_hour - now).total_seconds())


async def run_norm_limit_reload_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds_until_next_hour())
            return
        except asyncio.TimeoutError:
            pass
        try:
            results = await reload_norm_limits()
            logger.info("norm_limit_reload_cycle_complete tags=%d failed=%d samples=%d",
                        len(results), sum(item.status != "COMPLETE" for item in results),
                        sum(item.samples for item in results))
        except Exception:
            logger.exception("norm_limit_reload_cycle_failed")
