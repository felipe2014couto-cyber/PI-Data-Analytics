"""Run the durable PI workers as separate processes or one supervised group."""
from __future__ import annotations

import argparse
import asyncio

from app.core.logging import configure_logging
from app.workers.backfill_worker import run_backfill_loop
from app.workers.deletion_worker import run_deletion_loop
from app.workers.ingestion_worker import run_ingestion_loop
from app.integrations.pi.manager import shutdown_pi_provider, startup_pi_provider


async def main(
    worker: str,
    interval: float | None,
    once: bool = False,
    admin_only: bool = False,
    job_ids: list[int] | None = None,
) -> None:
    await startup_pi_provider()
    try:
        tasks = []
        if worker in {"all", "ingestion"}:
            tasks.append(run_ingestion_loop(interval or 10, once=once))
        if worker in {"all", "backfill"}:
            backfill_options = {"once": once}
            if admin_only:
                backfill_options["admin_only"] = True
            if job_ids:
                backfill_options["job_ids"] = job_ids
            tasks.append(run_backfill_loop(**backfill_options))
        if worker in {"all", "deletion"}:
            tasks.append(run_deletion_loop(once=once))
        await asyncio.gather(*tasks)
    finally:
        await shutdown_pi_provider()


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["all", "ingestion", "backfill", "deletion"], default="all")
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit; backfill includes all four rounds.")
    parser.add_argument("--admin-only", action="store_true", help="Backfill only queued administrative jobs; never start legacy rounds.")
    parser.add_argument(
        "--job-id",
        action="append",
        type=int,
        dest="job_ids",
        help="Resume a specific persisted backfill job by ID (repeatable).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.worker, args.interval, args.once, args.admin_only, args.job_ids))
