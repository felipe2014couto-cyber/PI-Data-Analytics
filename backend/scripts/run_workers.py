"""Run the durable PI workers as separate processes or one supervised group."""
from __future__ import annotations

import argparse
import asyncio

from app.workers.backfill_worker import run_backfill_loop
from app.workers.deletion_worker import run_deletion_loop
from app.workers.ingestion_worker import run_ingestion_loop


async def main(worker: str, interval: float | None) -> None:
    tasks = []
    if worker in {"all", "ingestion"}:
        tasks.append(run_ingestion_loop(interval or 10))
    if worker in {"all", "backfill"}:
        tasks.append(run_backfill_loop())
    if worker in {"all", "deletion"}:
        tasks.append(run_deletion_loop())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["all", "ingestion", "backfill", "deletion"], default="all")
    parser.add_argument("--interval", type=float, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.worker, args.interval))
