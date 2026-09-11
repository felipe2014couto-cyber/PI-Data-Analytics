"""Single-cycle execution must terminate without contacting PI or a real DB."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import run_workers
from app.workers import backfill_worker, deletion_worker, ingestion_worker


@pytest.mark.parametrize("selection", ["all", "ingestion", "backfill", "deletion"])
def test_dispatch_once(monkeypatch, selection):
    mocks = {}
    for name in ("ingestion", "backfill", "deletion"):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(run_workers, f"run_{name}_loop", mocks[name])
    asyncio.run(run_workers.main(selection, 7, once=True))
    for name, mock in mocks.items():
        if selection in ("all", name):
            mock.assert_awaited_once_with(*([7] if name == "ingestion" else []), once=True)
        else:
            mock.assert_not_awaited()


def test_worker_runner_manages_pi_provider_lifecycle(monkeypatch):
    startup = AsyncMock()
    shutdown = AsyncMock()
    ingestion = AsyncMock()
    monkeypatch.setattr(run_workers, "startup_pi_provider", startup)
    monkeypatch.setattr(run_workers, "shutdown_pi_provider", shutdown)
    monkeypatch.setattr(run_workers, "run_ingestion_loop", ingestion)

    asyncio.run(run_workers.main("ingestion", 7, once=True))

    startup.assert_awaited_once()
    shutdown.assert_awaited_once()
    ingestion.assert_awaited_once_with(7, once=True)


@pytest.mark.parametrize("module", [ingestion_worker, backfill_worker, deletion_worker])
def test_once_exits_without_sleep(monkeypatch, module):
    factory = MagicMock()
    db = factory.return_value.__enter__.return_value
    db.bind = None
    db.execute.return_value.scalars.return_value.all.return_value = []
    sleep = AsyncMock(side_effect=AssertionError("once must not sleep"))
    monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    name = module.__name__.rsplit(".", 1)[1].replace("_worker", "")
    asyncio.run(getattr(module, f"run_{name}_loop")(once=True))
    assert factory.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize("module", [ingestion_worker, backfill_worker, deletion_worker])
def test_once_propagates_cycle_failure(monkeypatch, module):
    monkeypatch.setattr(module, "SessionLocal", MagicMock(side_effect=RuntimeError("DB unavailable")))
    name = module.__name__.rsplit(".", 1)[1].replace("_worker", "")
    with pytest.raises(RuntimeError, match="DB unavailable"):
        asyncio.run(getattr(module, f"run_{name}_loop")(once=True))
