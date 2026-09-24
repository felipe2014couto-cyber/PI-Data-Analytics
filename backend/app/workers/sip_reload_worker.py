"""Run resumable SIP reload jobs in a dedicated supervised worker."""
import asyncio
from app.database.session import SessionLocal
from app.services.sip_reload_service import process_next


def cycle() -> bool:
    with SessionLocal() as db:
        return process_next(db)


async def run_sip_reload_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        worked = await asyncio.to_thread(cycle)
        if not worked:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass
