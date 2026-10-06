import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.postgres import PiBackfillJob
from app.workers import backfill_worker
from tests.conftest import TestingSessionLocal


def _job(db_session, **overrides) -> PiBackfillJob:
    now = datetime.now(UTC)
    values = {
        "tag_id": 1,
        "mode": "RECORDED",
        "target_start": now - timedelta(days=2),
        "target_end": now - timedelta(days=1),
        "next_start": now - timedelta(days=2),
        "checkpoint_start": now - timedelta(days=2) + timedelta(hours=3),
        "t0": now,
        "round_name": "R1",
        "stage": "RUNNING",
        "status": "RUNNING",
        "attempts": 1,
    }
    values.update(overrides)
    item = PiBackfillJob(**values)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def test_job_cursor_prefers_committed_checkpoint(db_session) -> None:
    item = _job(db_session)
    assert backfill_worker._job_cursor(item) == item.checkpoint_start.replace(tzinfo=UTC)
    db_session.delete(item)
    db_session.commit()


def test_expired_lease_recovery_ignores_legacy_running_rows(db_session, monkeypatch) -> None:
    monkeypatch.setattr(backfill_worker, "SessionLocal", TestingSessionLocal)
    expired = _job(
        db_session,
        lease_owner="dead-worker",
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    legacy = _job(db_session, lease_owner=None, lease_expires_at=None)

    recovered = backfill_worker._recover_expired_leases()

    db_session.expire_all()
    assert expired.id in recovered
    assert db_session.get(PiBackfillJob, expired.id).status == "PENDING"
    assert db_session.get(PiBackfillJob, expired.id).stage == "RETRY_WAIT"
    assert db_session.get(PiBackfillJob, legacy.id).status == "RUNNING"
    db_session.delete(db_session.get(PiBackfillJob, expired.id))
    db_session.delete(db_session.get(PiBackfillJob, legacy.id))
    db_session.commit()


def test_explicit_claim_can_adopt_reviewed_legacy_job(db_session, monkeypatch) -> None:
    monkeypatch.setattr(backfill_worker, "SessionLocal", TestingSessionLocal)
    legacy = _job(db_session, lease_owner=None, lease_expires_at=None)

    assert backfill_worker._claim_job(legacy.id) is False
    assert backfill_worker._claim_job(legacy.id, allow_legacy_running=True) is True

    db_session.expire_all()
    claimed = db_session.get(PiBackfillJob, legacy.id)
    assert claimed.status == "RUNNING"
    assert claimed.lease_owner == backfill_worker.LEASE_OWNER
    assert claimed.heartbeat_at is not None
    assert claimed.lease_expires_at is not None
    db_session.delete(claimed)
    db_session.commit()


def test_legacy_interpolated_backfill_job_is_ignored_without_mutation(db_session, monkeypatch) -> None:
    monkeypatch.setattr(backfill_worker, "SessionLocal", TestingSessionLocal)
    legacy = _job(
        db_session,
        mode="INTERPOLATED_10S",
        interval_seconds=10,
        status="PENDING",
        stage="PENDING",
        round_name=None,
        checkpoint_start=datetime.now(UTC) - timedelta(days=1),
    )

    assert legacy.id not in backfill_worker._active_job_ids(rounds=False)
    assert asyncio.run(backfill_worker._resume_job_by_id(
        legacy.id, asyncio.Semaphore(1), explicit=True,
    )) is False

    db_session.expire_all()
    unchanged = db_session.get(PiBackfillJob, legacy.id)
    assert unchanged is not None
    assert unchanged.mode == "INTERPOLATED_10S"
    assert unchanged.status == "PENDING"
    assert unchanged.attempts == 1
    db_session.delete(unchanged)
    db_session.commit()


def test_backfill_recorded_record_preserves_quality_and_legacy_mode_cannot_be_stamped() -> None:
    point = SimpleNamespace(
        timestamp=datetime(2026, 9, 21, tzinfo=UTC), value=-3.5,
        good=False, questionable=True, substituted=True,
    )
    row = backfill_worker._record(20, point, "RECORDED")
    assert row["source_mode"] == "RECORDED"
    assert row["value_double"] == -3.5
    assert (row["good"], row["questionable"], row["substituted"]) == (False, True, True)
    with pytest.raises(ValueError, match="somente RECORDED"):
        backfill_worker._record(20, point, "INTERPOLATED_300S")
