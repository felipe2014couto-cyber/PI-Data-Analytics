"""Tests validating the fixes for database health check:
1. Worker leader lock keys configuration.
2. Long transactions filtering for worker leader locks and detection of real user transactions.
3. check_alive() transaction commit and error handling.
4. job_stats SQL syntax and metrics collection.
5. Overall consolidated health status evaluation.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch
import pytest

from app.schemas.database_health import (
    ConnectionsInfo,
    DatabaseConnectionInfo,
    DatabaseHealthStatus,
    FreshnessInfo,
    LocksInfo,
    StorageInfo,
    TimescaleInfo,
)
from app.services.database_health_service import (
    DatabaseHealthCollector,
    _WORKER_LEADER_LOCK_KEYS,
)
from app.workers.supervisor import _AdvisoryLock


# ---------------------------------------------------------------------------
# 1. WORKER LOCK KEYS
# ---------------------------------------------------------------------------
def test_worker_leader_lock_keys_exact_set():
    """Verify that _WORKER_LEADER_LOCK_KEYS contains the 4 expected worker keys

    and does not contain the old typo key 2147483003.
    """
    expected_keys = {2147483601, 2147483602, 2147483603, 2147483604}
    current_keys = set(_WORKER_LEADER_LOCK_KEYS)

    assert current_keys == expected_keys, f"Expected {expected_keys}, got {current_keys}"
    assert 2147483003 not in _WORKER_LEADER_LOCK_KEYS, "Typo key 2147483003 must be removed"


# ---------------------------------------------------------------------------
# 2. TRANSACOES_LONGAS: Worker exclusions and real transaction detection
# ---------------------------------------------------------------------------
def test_collect_connections_ignores_all_four_worker_locks():
    """Simulate connections for the four worker leader locks.

    None of them should increment long_transactions_count even if active/idle in transaction
    with long duration.
    """
    mock_db = MagicMock()
    mock_db.execute.side_effect = [
        # SHOW max_connections
        MagicMock(scalar=lambda: 100),
        # SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' AND objid IN (...)
        MagicMock(scalars=lambda: [101, 102, 103, 104]),
        # SELECT pid, state, wait_event, xact_start, query_start, xact_duration, query_duration FROM pg_stat_activity
        [
            {"pid": 101, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
            {"pid": 102, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
            {"pid": 103, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
            {"pid": 104, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
        ],
        # SELECT ... FROM pg_stat_database
        MagicMock(mappings=lambda: MagicMock(first=lambda: {
            "xact_commit": 100, "xact_rollback": 0, "deadlocks": 0, "temp_files": 0, "temp_bytes": 0, "stats_reset": None
        })),
    ]

    collector = DatabaseHealthCollector(mock_db)
    collector.dialect = "postgresql"

    # Make the 3rd execute return an iterable with .mappings()
    activity_mock = MagicMock()
    activity_mock.mappings.return_value = [
        {"pid": 101, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
        {"pid": 102, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
        {"pid": 103, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
        {"pid": 104, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
    ]
    mock_db.execute.side_effect = [
        MagicMock(scalar=lambda: 100),
        MagicMock(scalars=lambda: [101, 102, 103, 104]),
        activity_mock,
        MagicMock(mappings=lambda: MagicMock(first=lambda: {
            "xact_commit": 100, "xact_rollback": 0, "deadlocks": 0, "temp_files": 0, "temp_bytes": 0, "stats_reset": None
        })),
    ]

    conn_info = collector._collect_connections()
    assert conn_info.long_transactions_count == 0, "Worker connections must NOT increment long_transactions_count"
    assert conn_info.worker_leader_connections == 4


def test_collect_connections_detects_real_long_transaction():
    """Verify that a genuine long transaction from a regular user/app connection is still detected."""
    mock_db = MagicMock()
    activity_mock = MagicMock()
    activity_mock.mappings.return_value = [
        # Worker connection (lock 2147483601) -> ignored
        {"pid": 101, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 4000.0, "query_duration": 1.0},
        # Real user connection -> MUST be detected as long transaction
        {"pid": 999, "state": "idle in transaction", "wait_event": None, "xact_start": datetime.now(timezone.utc), "query_start": datetime.now(timezone.utc), "xact_duration": 45.0, "query_duration": 1.0},
    ]
    mock_db.execute.side_effect = [
        MagicMock(scalar=lambda: 100),
        MagicMock(scalars=lambda: [101]),
        activity_mock,
        MagicMock(mappings=lambda: MagicMock(first=lambda: {
            "xact_commit": 100, "xact_rollback": 0, "deadlocks": 0, "temp_files": 0, "temp_bytes": 0, "stats_reset": None
        })),
    ]

    collector = DatabaseHealthCollector(mock_db)
    collector.dialect = "postgresql"

    conn_info = collector._collect_connections()
    assert conn_info.long_transactions_count == 1, "Real long transaction must be detected"
    assert conn_info.oldest_transaction_seconds == 45.0


# ---------------------------------------------------------------------------
# 3. check_alive() transaction closure & error handling
# ---------------------------------------------------------------------------
def test_advisory_lock_check_alive_commits_transaction():
    """check_alive() must commit the transaction after SELECT to prevent idle in transaction."""
    lock = _AdvisoryLock(2147483601, "test_ingestion")
    lock._acquired = True

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (1,)  # Lock is held
    mock_conn.cursor.return_value = mock_cursor
    lock._conn = mock_conn

    alive = lock.check_alive()

    assert alive is True
    mock_cursor.execute.assert_called_once()
    # Confirm commit was called
    mock_conn.commit.assert_called_once()
    mock_conn.rollback.assert_not_called()


def test_advisory_lock_check_alive_rollbacks_on_exception():
    """If SELECT or check fails, check_alive() should rollback to clear any aborted transaction."""
    lock = _AdvisoryLock(2147483601, "test_ingestion")
    lock._acquired = True

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("DB error")
    mock_conn.cursor.return_value = mock_cursor
    lock._conn = mock_conn

    alive = lock.check_alive()

    assert alive is False
    mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# 4. job_stats SQL syntax and metric collection
# ---------------------------------------------------------------------------
def test_job_stats_query_has_where_clause_and_parses():
    """Verify that the job_stats query text includes FILTER (WHERE ...) for operational_failed_jobs."""
    import inspect
    from app.services import database_health_service

    source = inspect.getsource(database_health_service.DatabaseHealthCollector._collect_timescale)
    # The operational_failed_jobs FILTER block must have WHERE
    assert "count(*) FILTER (" in source
    assert "WHERE" in source
    # Check specifically that the filter for operational_failed_jobs has WHERE
    assert "count(*) FILTER (\n                    WHERE" in source or "FILTER (WHERE" in source


def test_collect_timescale_successful_job_stats():
    """When job_stats view executes successfully with corrected query, job_stats is not unavailable."""
    mock_db = MagicMock()
    # Mock extension check
    mock_db.execute.side_effect = [
        # extversion
        MagicMock(scalar=lambda: "2.27.1"),
        # chunks count
        MagicMock(scalar=lambda: 449),
        # hypertable stats
        MagicMock(mappings=lambda: MagicMock(all=lambda: [])),
        # cagg stats
        MagicMock(mappings=lambda: MagicMock(all=lambda: [])),
        # jobs stats (q_jobs)
        MagicMock(mappings=lambda: MagicMock(first=lambda: {
            "total_jobs": 9,
            "failed_jobs": 1,
            "operational_failed_jobs": 0,
            "telemetry_failed": True,
            "last_success": datetime.now(timezone.utc),
        })),
        # compression_settings count
        MagicMock(scalar=lambda: 1),
    ]

    collector = DatabaseHealthCollector(mock_db)
    collector.dialect = "postgresql"

    ts_info = collector._collect_timescale()
    assert ts_info.available is True
    assert ts_info.failed_jobs == 1
    assert ts_info.operational_failed_jobs == 0
    assert ts_info.telemetry_failed is True
    assert "timescaledb_information.job_stats" not in collector.unavailable_metrics


# ---------------------------------------------------------------------------
# 5. Consolidated health status evaluation
# ---------------------------------------------------------------------------
def test_overall_status_healthy_when_no_real_long_tx():
    """When long_transactions_count is 0, transacoes_longas check is not triggered and status is HEALTHY."""
    collector = DatabaseHealthCollector(None)

    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=0.5, name="pi_analytics")
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(
        current=11, maximum=100, usage_percent=11.0, active=0, idle=7,
        long_transactions_count=0,
    )
    locks_info = LocksInfo(total=10, granted=10, waiting=0, blocked_sessions=0, advisory_locks=4)
    timescale_info = TimescaleInfo(
        available=True, version="2.27.1", chunks=449,
        failed_jobs=1, operational_failed_jobs=0, telemetry_failed=True,
    )
    freshness_info = FreshnessInfo(lag_seconds=10.0, tags_in_backoff=0, expired_backfill_leases=0)

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )

    assert status == DatabaseHealthStatus.HEALTHY
    check_names = [c.name for c in collector.checks]
    assert "transacoes_longas" not in check_names  # only created when long_transactions_count > 0
    assert any(c.name == "conectividade" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)
    assert any(c.name == "latencia" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)
    assert any(c.name == "conexoes" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)
    assert any(c.name == "bloqueios" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)
    assert any(c.name == "timescaledb" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)
    assert any(c.name == "telemetria" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)
    assert any(c.name == "frescor_dados" and c.status == DatabaseHealthStatus.HEALTHY for c in collector.checks)


def test_overall_status_preserves_real_warning():
    """If another condition has a genuine warning (e.g., data lag), overall status remains WARNING."""
    collector = DatabaseHealthCollector(None)

    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=0.5, name="pi_analytics")
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(
        current=11, maximum=100, usage_percent=11.0,
        long_transactions_count=0,
    )
    locks_info = LocksInfo(blocked_sessions=0)
    timescale_info = TimescaleInfo(available=True, operational_failed_jobs=0)
    freshness_info = FreshnessInfo(lag_seconds=600.0)  # > tolerance 300s

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )

    assert status == DatabaseHealthStatus.WARNING
    assert any(c.name == "frescor_dados" and c.status == DatabaseHealthStatus.WARNING for c in collector.checks)
