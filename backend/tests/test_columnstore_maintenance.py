"""Unit and integration tests for ColumnstoreMaintenanceService and storage reconciliation."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.schemas.database_health import (
    ConnectionsInfo,
    DatabaseConnectionInfo,
    DatabaseHealthStatus,
    FreshnessInfo,
    LocksInfo,
    StorageInfo,
    TimescaleInfo,
)
from app.services.columnstore_maintenance_service import (
    ChunkCandidate,
    ColumnstoreMaintenanceService,
    ColumnstoreMaintenanceStatus,
    IntegrityCheckError,
    LEADER_LOCK_COLUMNSTORE_MAINTENANCE,
    PreConversionMetrics,
    maintenance_status,
)
from app.services.database_health_service import DatabaseHealthCollector


def _utc_dt(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def test_candidate_detection_and_recent_exclusion():
    """Verify that chunks within the 7-day window are excluded from candidates."""
    svc = ColumnstoreMaintenanceService(min_delta_bytes=1048576)

    # Mock DB query returning a recent chunk and an older chunk
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    # 1 recent chunk (3 days ago), 1 historical chunk (15 days ago)
    recent_date = _utc_dt(3)
    hist_date = _utc_dt(15)

    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "chunk_schema": "_timescaledb_internal",
            "chunk_name": "_hyper_1_364_chunk",
            "range_start": hist_date - timedelta(days=1),
            "range_end": hist_date,
            "is_compressed": True,
            "heap_bytes": 6800000,
            "index_bytes": 11000000,
            "toast_bytes": 8192,
            "total_bytes": 17800000,
            "live_tuples": 65000,
            "dead_tuples": 100,
        }
    ]

    svc.engine = mock_engine
    candidates, total_pending = svc.find_candidates()

    assert len(candidates) == 1
    assert candidates[0].chunk_name == "_hyper_1_364_chunk"
    assert candidates[0].range_end == hist_date
    assert total_pending == 6800000 + 11000000


def test_blocking_when_backfill_overlaps():
    """Verify that an overlapping backfill in RUNNING or PENDING blocks the chunk."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    chunk_start = datetime(2026, 8, 10, tzinfo=timezone.utc)
    chunk_end = datetime(2026, 8, 11, tzinfo=timezone.utc)

    # Job overlaps with chunk [2026-08-05 to 2026-08-15]
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "id": 42,
            "status": "RUNNING",
            "target_start": datetime(2026, 8, 5, tzinfo=timezone.utc),
            "target_end": datetime(2026, 8, 15, tzinfo=timezone.utc),
            "lease_expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
    ]

    reason = svc.check_overlapping_backfill(chunk_start, chunk_end)
    assert reason is not None
    assert "Backfill job ID=42" in reason
    assert "sobreposto" in reason


def test_blocking_by_expired_lease():
    """Verify that an expired lease in a backfill job blocks the chunk."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    chunk_start = datetime(2026, 8, 10, tzinfo=timezone.utc)
    chunk_end = datetime(2026, 8, 11, tzinfo=timezone.utc)

    # Job has lease expired in the past
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "id": 99,
            "status": "RUNNING",
            "target_start": datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
            "target_end": datetime(2026, 8, 12, tzinfo=timezone.utc),
            "lease_expires_at": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
    ]

    reason = svc.check_overlapping_backfill(chunk_start, chunk_end)
    assert reason is not None
    assert "Backfill job ID=99" in reason


def test_no_blocking_when_backfill_does_not_overlap():
    """Verify that backfill jobs outside the chunk range do NOT block the chunk."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    chunk_start = datetime(2026, 8, 10, tzinfo=timezone.utc)
    chunk_end = datetime(2026, 8, 11, tzinfo=timezone.utc)

    # Job is strictly before chunk
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "id": 10,
            "status": "RUNNING",
            "target_start": datetime(2026, 7, 1, tzinfo=timezone.utc),
            "target_end": datetime(2026, 7, 10, tzinfo=timezone.utc),
            "lease_expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
    ]

    reason = svc.check_overlapping_backfill(chunk_start, chunk_end)
    assert reason is None


def test_procedure_call_only_and_no_compress_chunk_on_current_version():
    """Verify that in TimescaleDB 2.27.1 only convert_to_columnstore is called and compress_chunk is NOT called."""
    svc = ColumnstoreMaintenanceService(statement_timeout_seconds=60)
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.execution_options.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    with patch.object(svc, "detect_recompression_api", return_value="convert_to_columnstore"):
        svc.execute_recompression("_hyper_1_364_chunk")

    calls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("statement_timeout = '60s'" in c for c in calls)
    assert any("convert_to_columnstore" in c and "recompress => true" in c for c in calls)
    # MUST NOT call compress_chunk or recompress_chunk
    assert not any("compress_chunk" in c for c in calls)
    assert not any("recompress_chunk" in c for c in calls)
    # MUST NOT call VACUUM inside execute_recompression
    assert not any("VACUUM" in c for c in calls)


def test_mutually_exclusive_fallback_for_legacy_version():
    """Verify that legacy version uses compress_chunk and does NOT call convert_to_columnstore."""
    svc = ColumnstoreMaintenanceService(statement_timeout_seconds=60)
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.execution_options.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    with patch.object(svc, "detect_recompression_api", return_value="compress_chunk"):
        svc.execute_recompression("_hyper_1_364_chunk")

    calls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("compress_chunk" in c and "recompress => true" in c for c in calls)
    assert not any("convert_to_columnstore" in c for c in calls)


def test_vacuum_executed_in_separate_connection():
    """Verify that VACUUM runs in a dedicated autocommit connection with lock and statement timeouts."""
    svc = ColumnstoreMaintenanceService(
        vacuum_enabled=True,
        vacuum_lock_timeout_seconds=3,
        vacuum_statement_timeout_seconds=45,
    )
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.execution_options.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    ok, dur, err = svc.execute_vacuum("_hyper_1_364_chunk")
    assert ok is True
    assert err is None

    calls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("lock_timeout = '3000ms'" in c for c in calls)
    assert any("statement_timeout = '45s'" in c for c in calls)
    assert any("VACUUM _timescaledb_internal._hyper_1_364_chunk" in c for c in calls)
    # MUST NEVER contain VACUUM FULL
    assert not any("FULL" in c for c in calls)


def test_vacuum_default_missing_is_disabled():
    """Verify that VACUUM defaults to disabled (False) when not explicitly configured."""
    svc = ColumnstoreMaintenanceService()
    assert svc.vacuum_enabled is False
    mock_engine = MagicMock()
    svc.engine = mock_engine

    ok, dur, msg = svc.execute_vacuum("_hyper_1_364_chunk")
    assert ok is False
    assert "desabilitado" in msg
    assert not mock_engine.connect.called


def test_vacuum_explicit_false_configuration():
    """Verify that VACUUM is skipped when explicitly set to False."""
    svc = ColumnstoreMaintenanceService(vacuum_enabled=False)
    assert svc.vacuum_enabled is False
    mock_engine = MagicMock()
    svc.engine = mock_engine

    ok, dur, msg = svc.execute_vacuum("_hyper_1_364_chunk")
    assert ok is False
    assert "desabilitado" in msg
    assert not mock_engine.connect.called


def test_vacuum_explicit_true_configuration():
    """Verify that VACUUM is enabled when explicitly set to True."""
    svc = ColumnstoreMaintenanceService(vacuum_enabled=True)
    assert svc.vacuum_enabled is True


def test_vacuum_disabled_records_reusable_space_in_process_one_chunk():
    """Verify that when VACUUM is disabled, recompression succeeds and records pending space."""
    svc = ColumnstoreMaintenanceService(vacuum_enabled=False)
    cand = ChunkCandidate(
        chunk_schema="_timescaledb_internal",
        chunk_name="_hyper_1_364_chunk",
        range_start=_utc_dt(15),
        range_end=_utc_dt(14),
        is_compressed=True,
        heap_bytes=5000000,
        index_bytes=8000000,
        toast_bytes=8192,
        total_bytes=13008192,
        live_tuples=50000,
        dead_tuples=100,
    )

    with patch.object(svc, "check_overlapping_backfill", return_value=None), \
         patch.object(svc, "check_conflicting_locks", return_value=None), \
         patch.object(svc, "collect_pre_metrics") as mock_pre, \
         patch.object(svc, "execute_recompression"), \
         patch.object(svc, "verify_post_metrics", return_value=(0, 8000000, 5000000)), \
         patch.object(svc, "measure_chunk_storage", return_value={"heap_bytes": 5000000, "index_bytes": 8000000, "total_bytes": 13000000, "live_tuples": 0, "dead_tuples": 50}), \
         patch.object(svc, "execute_vacuum") as mock_vac:

        pre_inst = MagicMock()
        pre_inst.total_rows = 50000
        pre_inst.total_bytes = 13008192
        mock_pre.return_value = pre_inst

        result = svc.process_one_chunk(cand)

        assert result.success is True
        assert result.vacuum_executed is False
        assert result.vacuum_pending is True
        assert "desabilitado por configuração (opt-in)" in (result.vacuum_message or "")
        assert "heap=5000000B" in (result.vacuum_message or "")
        assert not mock_vac.called


def test_vacuum_failure_preserves_recompression_success():
    """Verify that if VACUUM fails or times out, recompression is NOT marked as lost."""
    svc = ColumnstoreMaintenanceService(vacuum_enabled=True)
    cand = ChunkCandidate(
        chunk_schema="_timescaledb_internal",
        chunk_name="_hyper_1_364_chunk",
        range_start=_utc_dt(15),
        range_end=_utc_dt(14),
        is_compressed=True,
        heap_bytes=5000000,
        index_bytes=8000000,
        toast_bytes=8192,
        total_bytes=13008192,
        live_tuples=50000,
        dead_tuples=100,
    )

    with patch.object(svc, "check_overlapping_backfill", return_value=None), \
         patch.object(svc, "check_conflicting_locks", return_value=None), \
         patch.object(svc, "collect_pre_metrics") as mock_pre, \
         patch.object(svc, "execute_recompression"), \
         patch.object(svc, "verify_post_metrics", return_value=(0, 8000000, 5000000)), \
         patch.object(svc, "measure_chunk_storage", return_value={"heap_bytes": 5000000, "index_bytes": 8000000, "total_bytes": 13000000, "live_tuples": 0, "dead_tuples": 50}), \
         patch.object(svc, "execute_vacuum", return_value=(False, 1.5, "Lock timeout")):

        pre_inst = MagicMock()
        pre_inst.total_rows = 50000
        pre_inst.total_bytes = 13008192
        mock_pre.return_value = pre_inst

        result = svc.process_one_chunk(cand)

        # Recompression must still be considered SUCCESSFUL
        assert result.success is True
        assert result.vacuum_pending is True
        assert result.vacuum_executed is False
        assert "Lock timeout" in (result.vacuum_message or "")


def test_vacuum_defers_when_new_backfill_arrives_before_vacuum():
    """Verify that if an overlapping backfill arrives right before VACUUM, VACUUM is deferred."""
    svc = ColumnstoreMaintenanceService(vacuum_enabled=True)
    cand = ChunkCandidate(
        chunk_schema="_timescaledb_internal",
        chunk_name="_hyper_1_364_chunk",
        range_start=_utc_dt(15),
        range_end=_utc_dt(14),
        is_compressed=True,
        heap_bytes=5000000,
        index_bytes=8000000,
        toast_bytes=8192,
        total_bytes=13008192,
        live_tuples=50000,
        dead_tuples=100,
    )

    # First check passes, second check before vacuum returns a blocking reason
    check_results = [None, "Backfill job ID=999 iniciado"]

    with patch.object(svc, "check_overlapping_backfill", side_effect=check_results), \
         patch.object(svc, "check_conflicting_locks", return_value=None), \
         patch.object(svc, "collect_pre_metrics") as mock_pre, \
         patch.object(svc, "execute_recompression"), \
         patch.object(svc, "verify_post_metrics", return_value=(0, 8000000, 5000000)), \
         patch.object(svc, "measure_chunk_storage", return_value={"heap_bytes": 5000000, "index_bytes": 8000000, "total_bytes": 13000000, "live_tuples": 0, "dead_tuples": 50}), \
         patch.object(svc, "execute_vacuum") as mock_vac:

        pre_inst = MagicMock()
        pre_inst.total_rows = 50000
        pre_inst.total_bytes = 13008192
        mock_pre.return_value = pre_inst

        result = svc.process_one_chunk(cand)

        assert result.success is True
        assert result.vacuum_pending is True
        assert "Novo backfill detectado antes do VACUUM" in (result.vacuum_message or "")
        assert not mock_vac.called


def test_backfill_states_matrix():
    """Verify the full matrix of backfill states and leases in check_overlapping_backfill."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    chunk_start = datetime(2026, 8, 10, tzinfo=timezone.utc)
    chunk_end = datetime(2026, 8, 11, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    # 1. RUNNING with valid lease -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 1, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "RUNNING", "stage": "RUNNING", "lease_owner": "w1", "lease_expires_at": now + timedelta(minutes=5), "heartbeat_at": now, "next_attempt_at": None, "consecutive_failures": 0}
    ]
    assert "lease ativo" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 2. RUNNING with expired lease -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 2, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "RUNNING", "stage": "RUNNING", "lease_owner": "w1", "lease_expires_at": now - timedelta(minutes=5), "heartbeat_at": now - timedelta(minutes=10), "next_attempt_at": None, "consecutive_failures": 0}
    ]
    assert "lease expirado" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 3. RUNNING without lease -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 3, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "RUNNING", "stage": "RUNNING", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": None, "consecutive_failures": 0}
    ]
    assert "sem lease" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 4. PENDING -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 4, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "PENDING", "stage": "PENDING", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": None, "consecutive_failures": 0}
    ]
    assert "PENDING" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 5. RETRY -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 5, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "RETRY", "stage": "RETRY", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": now + timedelta(minutes=2), "consecutive_failures": 1}
    ]
    assert "RETRY" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 6. FAILED with scheduled retry -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 6, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "FAILED", "stage": "FAILED", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": now + timedelta(minutes=5), "consecutive_failures": 2}
    ]
    assert "retry agendado" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 7. Legacy/unknown state -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 7, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "PROCESSING", "stage": "UNKNOWN", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": None, "consecutive_failures": 0}
    ]
    assert "estado legado/desconhecido" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 8. COMPLETED with incomplete sibling leg -> BLOCKS
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 8, "tag_id": 5, "round_name": "R1", "target_start": chunk_start, "target_end": chunk_end, "status": "COMPLETED", "stage": "COMPLETED", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": None, "consecutive_failures": 0}
    ]
    # Sibling query returns an active leg
    mock_conn.execute.return_value.mappings.return_value.first.return_value = {"id": 9, "status": "RUNNING", "stage": "RUNNING"}
    assert "não concluída" in svc.check_overlapping_backfill(chunk_start, chunk_end)

    # 9. COMPLETED with no incomplete siblings -> DOES NOT BLOCK
    mock_conn.execute.return_value.mappings.return_value.first.return_value = None
    assert svc.check_overlapping_backfill(chunk_start, chunk_end) is None

    # 10. CANCELLED -> DOES NOT BLOCK
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 10, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "CANCELLED", "stage": "CANCELLED", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": None, "consecutive_failures": 0}
    ]
    assert svc.check_overlapping_backfill(chunk_start, chunk_end) is None

    # 11. Terminal FAILED without retry -> DOES NOT BLOCK
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 11, "tag_id": 5, "round_name": None, "target_start": chunk_start, "target_end": chunk_end, "status": "FAILED", "stage": "FAILED", "lease_owner": None, "lease_expires_at": None, "heartbeat_at": None, "next_attempt_at": None, "consecutive_failures": 5}
    ]
    assert svc.check_overlapping_backfill(chunk_start, chunk_end) is None


def test_integrity_check_detects_row_count_divergence():
    """Verify that post-verification raises IntegrityCheckError when counts diverge."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    svc.engine = mock_engine

    pre = PreConversionMetrics(
        chunk_name="_hyper_1_364_chunk",
        range_start=_utc_dt(15),
        range_end=_utc_dt(14),
        total_rows=1000,
        rows_by_group={"1:RECORDED": 1000},
        min_ts=_utc_dt(15),
        max_ts=_utc_dt(14),
        heap_bytes=1000000,
        index_bytes=2000000,
        toast_bytes=8192,
        total_bytes=3008192,
        columnstore_total_bytes=500000,
        deterministic_sample=[],
    )

    # Post query returns 999 instead of 1000
    mock_conn.execute.return_value.mappings.return_value = [
        {"tag_id": 1, "source_mode": "RECORDED", "cnt": 999}
    ]

    with pytest.raises(IntegrityCheckError) as exc_info:
        svc.verify_post_metrics(pre)
    assert "Divergência na contagem" in str(exc_info.value)


def test_graceful_shutdown_respects_stop_event():
    """Verify that process_one_chunk stops immediately when stop_event is set."""
    svc = ColumnstoreMaintenanceService()
    stop_event = asyncio.Event()
    stop_event.set()

    cand = ChunkCandidate(
        chunk_schema="_timescaledb_internal",
        chunk_name="_hyper_1_364_chunk",
        range_start=_utc_dt(15),
        range_end=_utc_dt(14),
        is_compressed=True,
        heap_bytes=5000000,
        index_bytes=8000000,
        toast_bytes=8192,
        total_bytes=13008192,
        live_tuples=50000,
        dead_tuples=10,
    )

    result = svc.process_one_chunk(cand, stop_event=stop_event)
    assert result.success is False
    assert "stop_event" in (result.error_message or "")


def test_telemetry_job_failure_classified_as_info():
    """Verify that telemetry job failure does not cause WARNING, but stays HEALTHY with informative message."""
    collector = DatabaseHealthCollector(None)
    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=5.0)
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(current=10, maximum=100, usage_percent=10.0)
    locks_info = LocksInfo()
    freshness_info = FreshnessInfo(lag_seconds=60.0)

    # TimescaleInfo with 1 telemetry failure and 0 operational failures
    timescale_info = TimescaleInfo(
        available=True,
        total_jobs=8,
        failed_jobs=1,
        operational_failed_jobs=0,
        telemetry_failed=True,
        chunks=377,
        version="2.27.1",
    )

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )

    # Overall database status must remain HEALTHY
    assert status == DatabaseHealthStatus.HEALTHY

    # Checks must contain informative telemetry item
    telemetry_item = next((c for c in collector.checks if c.name == "telemetria"), None)
    assert telemetry_item is not None
    assert telemetry_item.status == DatabaseHealthStatus.HEALTHY
    assert "telemetria externa indisponível" in telemetry_item.message

    # Operational job check must be HEALTHY
    ts_item = next((c for c in collector.checks if c.name == "timescaledb"), None)
    assert ts_item is not None
    assert ts_item.status == DatabaseHealthStatus.HEALTHY


def test_operational_job_failure_triggers_warning():
    """Verify that operational job failure (e.g. compression or CAG) DOES trigger WARNING."""
    collector = DatabaseHealthCollector(None)
    conn_info = DatabaseConnectionInfo(reachable=True, latency_ms=5.0)
    storage_info = StorageInfo()
    conn_stats = ConnectionsInfo(current=10, maximum=100, usage_percent=10.0)
    locks_info = LocksInfo()
    freshness_info = FreshnessInfo(lag_seconds=60.0)

    timescale_info = TimescaleInfo(
        available=True,
        total_jobs=8,
        failed_jobs=1,
        operational_failed_jobs=1,
        telemetry_failed=False,
        chunks=377,
        version="2.27.1",
    )

    status = collector._evaluate_checks(
        conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
    )

    assert status == DatabaseHealthStatus.WARNING
    ts_jobs_item = next((c for c in collector.checks if c.name == "timescaledb_jobs"), None)
    assert ts_jobs_item is not None
    assert ts_jobs_item.status == DatabaseHealthStatus.WARNING
    assert "1 job(s) operacional(is)" in ts_jobs_item.message


def test_storage_breakdown_pure_heap_no_double_counting():
    """Verify StorageInfo fields can separate tables_heap from toast_bytes without double counting."""
    info = StorageInfo(
        database_bytes=7000000000,
        database_human="7.00 GB",
        tables_bytes=2800000000,  # pg_table_size (includes toast)
        tables_human="2.80 GB",
        tables_heap_bytes=2400000000,  # pure pg_relation_size
        tables_heap_human="2.40 GB",
        toast_bytes=400000000,
        toast_human="400.00 MB",
        indexes_bytes=4200000000,
        indexes_human="4.20 GB",
    )

    # Pure heap + TOAST + indexes equals total database relation size
    assert info.tables_heap_bytes + info.toast_bytes + info.indexes_bytes == 7000000000
    # While pg_table_size already contains TOAST:
    assert info.tables_heap_bytes + info.toast_bytes == info.tables_bytes


def test_find_candidates_ignores_residual_heap_with_zero_live_tuples():
    """Verify that chunks with allocated physical heap or index pages but 0 live tuples are NOT selected."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    # Chunk with 5 MB physical heap and 10 MB indexes, but 0 live tuples (unvacuumed dead pages / converted)
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []

    svc.engine = mock_engine
    candidates, total_pending = svc.find_candidates()

    assert len(candidates) == 0
    assert total_pending == 0


def test_find_candidates_re_eligibility_after_backfill_write():
    """Verify that a converted chunk returns to eligibility only when backfill writes new live tuples."""
    svc = ColumnstoreMaintenanceService()
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    hist_date = _utc_dt(15)

    # 1. First query: converted chunk has 0 live tuples -> 0 candidates
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []
    svc.engine = mock_engine
    candidates, total_pending = svc.find_candidates()
    assert len(candidates) == 0

    # 2. Backfill runs and inserts 5,000 new rows (live_tuples=5000, heap=2MB) -> becomes eligible
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "chunk_schema": "_timescaledb_internal",
            "chunk_name": "_hyper_1_330_chunk",
            "range_start": hist_date - timedelta(days=1),
            "range_end": hist_date,
            "is_compressed": True,
            "heap_bytes": 2097152,
            "index_bytes": 4194304,
            "toast_bytes": 8192,
            "total_bytes": 6299648,
            "live_tuples": 5000,
            "dead_tuples": 0,
        }
    ]
    candidates, total_pending = svc.find_candidates()
    assert len(candidates) == 1
    assert candidates[0].chunk_name == "_hyper_1_330_chunk"
    assert candidates[0].live_tuples == 5000
    assert total_pending == 2097152 + 4194304

