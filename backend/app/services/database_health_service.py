"""Read-only Database Health service for PostgreSQL and TimescaleDB."""
import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.database.session import SessionLocal, engine
from app.schemas.database_health import (
    ConnectionsInfo,
    DatabaseConnectionInfo,
    DatabaseHealthResponse,
    DatabaseHealthStatus,
    FreshnessInfo,
    HealthCheckItem,
    LocksInfo,
    StorageInfo,
    StorageRelationInfo,
    TimescaleInfo,
)

_cache_lock = asyncio.Lock()
_cached_response: Optional[DatabaseHealthResponse] = None
_cached_at: float = 0.0

# Known worker leader lock keys (advisory locks held by design)
_WORKER_LEADER_LOCK_KEYS = (2147483601, 2147483602, 2147483003)


def format_bytes(b: Optional[int]) -> str:
    """Format bytes count into human-readable string (B, KB, MB, GB, TB)."""
    if b is None or b < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    val = float(b)
    unit_idx = 0
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} B"
    return f"{val:.2f} {units[unit_idx]}"


class DatabaseHealthCollector:
    """Collects comprehensive, read-only diagnostic metrics from the database."""

    def __init__(self, db: Session):
        self.db = db
        self.dialect = engine.dialect.name
        self.checks: List[HealthCheckItem] = []
        self.unavailable_metrics: List[str] = []

    def collect(self) -> DatabaseHealthResponse:
        t0 = time.perf_counter()
        now_utc = datetime.now(timezone.utc)

        # 1. Connectivity & latency
        conn_info, reachable = self._collect_connectivity()
        if not reachable:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.checks.append(
                HealthCheckItem(
                    name="connectivity",
                    status=DatabaseHealthStatus.UNAVAILABLE,
                    message="Falha de conexão com o banco de dados.",
                )
            )
            return DatabaseHealthResponse(
                status=DatabaseHealthStatus.UNAVAILABLE,
                checked_at=now_utc,
                duration_ms=duration_ms,
                cached=False,
                database=conn_info,
                storage=StorageInfo(),
                connections=ConnectionsInfo(),
                locks=LocksInfo(),
                timescale=TimescaleInfo(),
                freshness=FreshnessInfo(),
                checks=self.checks,
                unavailable_metrics=self.unavailable_metrics,
            )

        # 2. Storage
        storage_info = self._collect_storage()

        # 3. Connections & Activity
        conn_stats = self._collect_connections()

        # 4. Locks
        locks_info = self._collect_locks()

        # 5. TimescaleDB
        timescale_info = self._collect_timescale()

        # 6. Data freshness & Workers
        freshness_info = self._collect_freshness(now_utc)

        # 7. Evaluate consolidated health status
        overall_status = self._evaluate_checks(
            conn_info, storage_info, conn_stats, locks_info, timescale_info, freshness_info
        )

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        return DatabaseHealthResponse(
            status=overall_status,
            checked_at=now_utc,
            duration_ms=duration_ms,
            cached=False,
            database=conn_info,
            storage=storage_info,
            connections=conn_stats,
            locks=locks_info,
            timescale=timescale_info,
            freshness=freshness_info,
            checks=self.checks,
            unavailable_metrics=self.unavailable_metrics,
        )

    def _collect_connectivity(self) -> Tuple[DatabaseConnectionInfo, bool]:
        t_start = time.perf_counter()
        try:
            val = self.db.execute(text("SELECT 1")).scalar()
            latency_ms = round((time.perf_counter() - t_start) * 1000, 2)
            if val != 1:
                return DatabaseConnectionInfo(reachable=False, latency_ms=latency_ms), False
        except Exception as exc:
            logger.warning("db_health_ping_failed err=%s", exc)
            return DatabaseConnectionInfo(reachable=False), False

        db_name = None
        pg_version = None
        ts_version = None
        uptime_seconds = None
        alembic_rev = None

        if self.dialect == "sqlite":
            try:
                pg_version = f"SQLite {self.db.execute(text('SELECT sqlite_version()')).scalar()}"
                db_name = "sqlite_main"
            except Exception:
                pass
        else:
            try:
                db_name = self.db.execute(text("SELECT current_database()")).scalar()
            except Exception:
                pass
            try:
                pg_version = self.db.execute(text("SELECT version()")).scalar()
            except Exception:
                pass
            try:
                ts_version = self.db.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
                ).scalar()
            except Exception:
                pass
            try:
                uptime_val = self.db.execute(
                    text("SELECT EXTRACT(EPOCH FROM (NOW() - pg_postmaster_start_time()))")
                ).scalar()
                if uptime_val is not None:
                    uptime_seconds = round(float(uptime_val), 1)
            except Exception:
                pass

        try:
            alembic_rev = self.db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        except Exception:
            pass

        return (
            DatabaseConnectionInfo(
                reachable=True,
                latency_ms=latency_ms,
                name=db_name,
                postgresql_version=pg_version,
                timescaledb_version=ts_version,
                uptime_seconds=uptime_seconds,
                alembic_revision=alembic_rev,
            ),
            True,
        )

    def _collect_storage(self) -> StorageInfo:
        if self.dialect == "sqlite":
            self.unavailable_metrics.append("pg_database_size")
            self.unavailable_metrics.append("pg_relation_size")
            try:
                pages = self.db.execute(text("PRAGMA page_count")).scalar() or 0
                page_size = self.db.execute(text("PRAGMA page_size")).scalar() or 4096
                db_bytes = int(pages) * int(page_size)
                return StorageInfo(
                    database_bytes=db_bytes,
                    database_human=format_bytes(db_bytes),
                    tables_bytes=db_bytes,
                    tables_human=format_bytes(db_bytes),
                    filesystem_available=False,
                    filesystem_reason="Métrica do sistema operacional não disponível para o usuário da aplicação",
                )
            except Exception:
                return StorageInfo()

        db_bytes = 0
        total_tables = 0
        total_indexes = 0
        total_toast = 0

        # Database size
        try:
            res = self.db.execute(text("SELECT pg_database_size(current_database())")).scalar()
            db_bytes = int(res or 0)
        except Exception as exc:
            logger.debug("db_health_storage_db_size_failed err=%s", exc)
            self.unavailable_metrics.append("pg_database_size")

        # Table, index and toast sizes
        q_sizes = """
        SELECT
            COALESCE(SUM(pg_table_size(c.oid)), 0) AS total_table_bytes,
            COALESCE(SUM(pg_indexes_size(c.oid)), 0) AS total_index_bytes,
            COALESCE(SUM(pg_total_relation_size(c.reltoastrelid)), 0) AS total_toast_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'm')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema');
        """
        try:
            row = self.db.execute(text(q_sizes)).mappings().first()
            if row:
                total_tables = int(row["total_table_bytes"] or 0)
                total_indexes = int(row["total_index_bytes"] or 0)
                total_toast = int(row["total_toast_bytes"] or 0)
        except Exception as exc:
            logger.debug("db_health_storage_sizes_failed err=%s", exc)
            self.unavailable_metrics.append("table_index_toast_breakdown")

        # Specific relation sizes
        pi_samples_bytes = None
        try:
            # Check hypertable_detailed_size if hypertable
            res = self.db.execute(text("SELECT total_bytes FROM hypertable_detailed_size('pi_samples_timescale')")).scalar()
            pi_samples_bytes = int(res or 0)
        except Exception:
            try:
                res = self.db.execute(text("SELECT pg_total_relation_size('pi_samples_timescale'::regclass)")).scalar()
                pi_samples_bytes = int(res or 0)
            except Exception:
                pass

        pi_backfill_bytes = None
        try:
            res = self.db.execute(text("SELECT pg_total_relation_size('pi_backfill_jobs'::regclass)")).scalar()
            pi_backfill_bytes = int(res or 0)
        except Exception:
            pass

        pi_ingestion_bytes = None
        try:
            res = self.db.execute(text("SELECT pg_total_relation_size('pi_ingestion_state'::regclass)")).scalar()
            pi_ingestion_bytes = int(res or 0)
        except Exception:
            pass

        # Top 10 largest relations
        largest_relations: List[StorageRelationInfo] = []
        q_top = """
        SELECT
            n.nspname AS schema_name,
            c.relname AS relation_name,
            CASE c.relkind
                WHEN 'r' THEN 'table'
                WHEN 'v' THEN 'view'
                WHEN 'm' THEN 'materialized_view'
                WHEN 'i' THEN 'index'
                WHEN 'S' THEN 'sequence'
                WHEN 't' THEN 'toast_table'
                WHEN 'p' THEN 'partitioned_table'
                ELSE c.relkind::text
            END AS relation_type,
            COALESCE(pg_relation_size(c.oid), 0) AS data_bytes,
            COALESCE(pg_indexes_size(c.oid), 0) AS index_bytes,
            COALESCE(pg_total_relation_size(c.oid), 0) AS total_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND c.relkind IN ('r', 'p', 'm', 't')
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT 10;
        """
        try:
            for r in self.db.execute(text(q_top)).mappings():
                d_bytes = int(r["data_bytes"] or 0)
                i_bytes = int(r["index_bytes"] or 0)
                t_bytes = int(r["total_bytes"] or 0)
                largest_relations.append(
                    StorageRelationInfo(
                        schema_name=str(r["schema_name"]),
                        relation_name=str(r["relation_name"]),
                        relation_type=str(r["relation_type"]),
                        data_bytes=d_bytes,
                        index_bytes=i_bytes,
                        total_bytes=t_bytes,
                        data_human=format_bytes(d_bytes),
                        index_human=format_bytes(i_bytes),
                        total_human=format_bytes(t_bytes),
                    )
                )
        except Exception as exc:
            logger.debug("db_health_largest_relations_failed err=%s", exc)
            self.unavailable_metrics.append("largest_relations")

        return StorageInfo(
            database_bytes=db_bytes,
            database_human=format_bytes(db_bytes),
            tables_bytes=total_tables,
            tables_human=format_bytes(total_tables),
            indexes_bytes=total_indexes,
            indexes_human=format_bytes(total_indexes),
            toast_bytes=total_toast,
            toast_human=format_bytes(total_toast),
            pi_samples_bytes=pi_samples_bytes,
            pi_samples_human=format_bytes(pi_samples_bytes) if pi_samples_bytes is not None else None,
            pi_backfill_bytes=pi_backfill_bytes,
            pi_backfill_human=format_bytes(pi_backfill_bytes) if pi_backfill_bytes is not None else None,
            pi_ingestion_bytes=pi_ingestion_bytes,
            pi_ingestion_human=format_bytes(pi_ingestion_bytes) if pi_ingestion_bytes is not None else None,
            filesystem_available=False,
            filesystem_reason="Métrica do sistema operacional não disponível para o usuário da aplicação",
            largest_relations=largest_relations,
        )

    def _collect_connections(self) -> ConnectionsInfo:
        if self.dialect == "sqlite":
            self.unavailable_metrics.append("pg_stat_activity")
            self.unavailable_metrics.append("pg_stat_database")
            return ConnectionsInfo(current=1, maximum=1, usage_percent=100.0, active=1)

        maximum = 100
        try:
            m = self.db.execute(text("SHOW max_connections")).scalar()
            if m:
                maximum = int(m)
        except Exception:
            pass

        # Identify PIDs holding worker leader advisory locks
        worker_pids = set()
        try:
            q_worker_pids = f"""
            SELECT DISTINCT pid
            FROM pg_locks
            WHERE locktype = 'advisory'
              AND objid IN ({','.join(str(k) for k in _WORKER_LEADER_LOCK_KEYS)})
            """
            for row in self.db.execute(text(q_worker_pids)).scalars():
                if row:
                    worker_pids.add(int(row))
        except Exception:
            pass

        current = 0
        active = 0
        idle = 0
        idle_in_tx = 0
        waiting = 0
        long_tx_count = 0
        oldest_tx_sec = None
        long_queries_count = 0
        oldest_query_sec = None

        tx_threshold = settings.db_health_long_transaction_seconds
        query_threshold = settings.db_health_long_query_seconds

        q_activity = """
        SELECT
            pid,
            state,
            wait_event,
            xact_start,
            query_start,
            EXTRACT(EPOCH FROM (NOW() - xact_start)) AS xact_duration,
            EXTRACT(EPOCH FROM (NOW() - query_start)) AS query_duration
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid != pg_backend_pid();
        """
        try:
            for r in self.db.execute(text(q_activity)).mappings():
                pid = int(r["pid"])
                st = str(r["state"] or "")
                current += 1

                if pid in worker_pids:
                    # Session belongs to background worker holding leader lock
                    if st == "active":
                        active += 1
                    continue

                if st == "active":
                    active += 1
                    if r["wait_event"] is not None:
                        waiting += 1
                    q_dur = max(0.0, float(r["query_duration"] or 0))
                    if q_dur >= query_threshold:
                        long_queries_count += 1
                        if oldest_query_sec is None or q_dur > oldest_query_sec:
                            oldest_query_sec = q_dur
                elif st == "idle":
                    idle += 1
                elif st == "idle in transaction":
                    idle_in_tx += 1

                if st != "idle" and r["xact_start"] is not None:
                    x_dur = max(0.0, float(r["xact_duration"] or 0))
                    if x_dur >= tx_threshold:
                        long_tx_count += 1
                    if oldest_tx_sec is None or x_dur > oldest_tx_sec:
                        oldest_tx_sec = x_dur
        except Exception as exc:
            logger.debug("db_health_activity_failed err=%s", exc)
            self.unavailable_metrics.append("pg_stat_activity")

        commits = None
        rollbacks = None
        deadlocks = None
        temp_files = None
        temp_bytes = None
        stats_reset = None

        q_dbstat = """
        SELECT
            xact_commit,
            xact_rollback,
            deadlocks,
            temp_files,
            temp_bytes,
            stats_reset
        FROM pg_stat_database
        WHERE datname = current_database();
        """
        try:
            row = self.db.execute(text(q_dbstat)).mappings().first()
            if row:
                commits = int(row["xact_commit"] or 0)
                rollbacks = int(row["xact_rollback"] or 0)
                deadlocks = int(row["deadlocks"] or 0)
                temp_files = int(row["temp_files"] or 0)
                temp_bytes = int(row["temp_bytes"] or 0)
                stats_reset = row["stats_reset"]
        except Exception as exc:
            logger.debug("db_health_dbstat_failed err=%s", exc)
            self.unavailable_metrics.append("pg_stat_database")

        usage_pct = round((current / maximum) * 100, 1) if maximum > 0 else 0.0

        return ConnectionsInfo(
            current=current,
            maximum=maximum,
            usage_percent=usage_pct,
            active=active,
            idle=idle,
            idle_in_transaction=idle_in_tx,
            waiting=waiting,
            worker_leader_connections=len(worker_pids),
            long_transactions_count=long_tx_count,
            oldest_transaction_seconds=round(oldest_tx_sec, 1) if oldest_tx_sec is not None else None,
            long_queries_count=long_queries_count,
            oldest_query_seconds=round(oldest_query_sec, 1) if oldest_query_sec is not None else None,
            commits=commits,
            rollbacks=rollbacks,
            deadlocks=deadlocks,
            temp_files=temp_files,
            temp_bytes=temp_bytes,
            temp_human=format_bytes(temp_bytes) if temp_bytes is not None else None,
            stats_reset=stats_reset,
        )

    def _collect_locks(self) -> LocksInfo:
        if self.dialect == "sqlite":
            self.unavailable_metrics.append("pg_locks")
            return LocksInfo()

        q_locks = """
        SELECT
            count(*) AS total_locks,
            count(*) FILTER (WHERE granted = true) AS granted_locks,
            count(*) FILTER (WHERE granted = false) AS waiting_locks,
            count(*) FILTER (WHERE locktype = 'advisory') AS advisory_locks
        FROM pg_locks l
        JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE a.datname = current_database();
        """
        total = 0
        granted = 0
        waiting = 0
        advisory = 0
        try:
            r = self.db.execute(text(q_locks)).mappings().first()
            if r:
                total = int(r["total_locks"] or 0)
                granted = int(r["granted_locks"] or 0)
                waiting = int(r["waiting_locks"] or 0)
                advisory = int(r["advisory_locks"] or 0)
        except Exception as exc:
            logger.debug("db_health_locks_failed err=%s", exc)
            self.unavailable_metrics.append("pg_locks")

        blocked_count = 0
        oldest_blocked_sec = None
        q_blocked = """
        SELECT
            count(DISTINCT blocked.pid) AS blocked_sessions_count,
            EXTRACT(EPOCH FROM MAX(NOW() - blocked.state_change)) AS oldest_blocked_seconds
        FROM pg_locks l_blocked
        JOIN pg_stat_activity blocked ON blocked.pid = l_blocked.pid
        WHERE NOT l_blocked.granted
          AND blocked.datname = current_database();
        """
        try:
            r = self.db.execute(text(q_blocked)).mappings().first()
            if r:
                blocked_count = int(r["blocked_sessions_count"] or 0)
                if r["oldest_blocked_seconds"] is not None:
                    oldest_blocked_sec = round(float(r["oldest_blocked_seconds"]), 1)
        except Exception as exc:
            logger.debug("db_health_blocked_failed err=%s", exc)

        return LocksInfo(
            total=total,
            granted=granted,
            waiting=waiting,
            advisory_locks=advisory,
            blocked_sessions=blocked_count,
            oldest_wait_seconds=oldest_blocked_sec,
        )

    def _collect_timescale(self) -> TimescaleInfo:
        if self.dialect == "sqlite":
            self.unavailable_metrics.append("timescaledb")
            return TimescaleInfo(available=False)

        # Check extension
        ext_version = None
        try:
            ext_version = self.db.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            ).scalar()
        except Exception:
            pass

        if not ext_version:
            return TimescaleInfo(available=False)

        hypertables = 0
        chunks = 0
        cags = 0
        total_jobs = 0
        failed_jobs = 0
        last_status = None
        last_success = None
        compression_enabled = None
        retention_configured = None

        try:
            hypertables = int(
                self.db.execute(text("SELECT count(*) FROM timescaledb_information.hypertables")).scalar() or 0
            )
        except Exception:
            self.unavailable_metrics.append("timescaledb_information.hypertables")

        try:
            chunks = int(
                self.db.execute(text("SELECT count(*) FROM timescaledb_information.chunks")).scalar() or 0
            )
        except Exception:
            self.unavailable_metrics.append("timescaledb_information.chunks")

        try:
            cags = int(
                self.db.execute(
                    text("SELECT count(*) FROM timescaledb_information.continuous_aggregates")
                ).scalar()
                or 0
            )
        except Exception:
            self.unavailable_metrics.append("timescaledb_information.continuous_aggregates")

        try:
            q_jobs = """
            SELECT
                count(*) as total_jobs,
                count(*) FILTER (WHERE total_failures > 0 OR last_run_status = 'Failed') as failed_jobs,
                MAX(last_successful_finish) as last_success
            FROM timescaledb_information.job_stats;
            """
            r = self.db.execute(text(q_jobs)).mappings().first()
            if r:
                total_jobs = int(r["total_jobs"] or 0)
                failed_jobs = int(r["failed_jobs"] or 0)
                last_success = r["last_success"]
        except Exception:
            self.unavailable_metrics.append("timescaledb_information.job_stats")

        try:
            comp_count = int(
                self.db.execute(
                    text("SELECT count(*) FROM timescaledb_information.compression_settings")
                ).scalar()
                or 0
            )
            compression_enabled = comp_count > 0
        except Exception:
            pass

        return TimescaleInfo(
            available=True,
            version=str(ext_version),
            hypertables=hypertables,
            chunks=chunks,
            continuous_aggregates=cags,
            total_jobs=total_jobs,
            failed_jobs=failed_jobs,
            last_run_status=last_status,
            last_successful_finish=last_success,
            compression_enabled=compression_enabled,
            retention_configured=retention_configured,
        )

    def _collect_freshness(self, now_utc: datetime) -> FreshnessInfo:
        latest_ts = None
        latest_rec_ts = None
        lag_seconds = None

        # 1. Latest recorded sample (indexed query)
        try:
            q_rec = "SELECT ts FROM pi_samples_timescale WHERE source_mode = 'RECORDED' ORDER BY ts DESC LIMIT 1"
            latest_rec_ts = self.db.execute(text(q_rec)).scalar()
        except Exception:
            try:
                latest_rec_ts = self.db.execute(text("SELECT ts FROM pi_samples_timescale ORDER BY ts DESC LIMIT 1")).scalar()
            except Exception:
                pass

        try:
            q_any = "SELECT ts FROM pi_samples_timescale ORDER BY ts DESC LIMIT 1"
            latest_ts = self.db.execute(text(q_any)).scalar()
        except Exception:
            pass

        ref_ts = latest_rec_ts or latest_ts
        if ref_ts:
            if ref_ts.tzinfo is None:
                ref_ts = ref_ts.replace(tzinfo=timezone.utc)
            lag_seconds = max(0.0, round((now_utc - ref_ts).total_seconds(), 1))

        # 2. Ingestion state
        ingestion_count = 0
        oldest_wm = None
        newest_wm = None
        in_backoff = 0
        with_failures = 0
        last_success_at = None

        try:
            q_ing = """
            SELECT
                count(*) AS total_states,
                MIN(watermark_ts) AS oldest_watermark,
                MAX(watermark_ts) AS newest_watermark,
                MAX(last_success_at) AS last_success_at,
                count(*) FILTER (WHERE next_attempt_at IS NOT NULL AND next_attempt_at > NOW()) AS in_backoff,
                count(*) FILTER (WHERE consecutive_failures > 0) AS with_failures
            FROM pi_ingestion_state;
            """
            r = self.db.execute(text(q_ing)).mappings().first()
            if r:
                ingestion_count = int(r["total_states"] or 0)
                oldest_wm = r["oldest_watermark"]
                newest_wm = r["newest_watermark"]
                last_success_at = r["last_success_at"]
                in_backoff = int(r["in_backoff"] or 0)
                with_failures = int(r["with_failures"] or 0)
        except Exception as exc:
            logger.debug("db_health_ingestion_state_failed err=%s", exc)

        # 3. Backfill jobs
        bf_by_status: Dict[str, int] = {}
        expired_leases = 0
        consecutive_bf_failures = 0

        try:
            q_bf = "SELECT status, count(*) AS count FROM pi_backfill_jobs GROUP BY status"
            for r in self.db.execute(text(q_bf)).mappings():
                st_key = str(r["status"])
                bf_by_status[st_key] = int(r["count"] or 0)

            q_bf_stats = """
            SELECT
                count(*) FILTER (WHERE status = 'RUNNING' AND lease_expires_at IS NOT NULL AND lease_expires_at < NOW()) AS expired_leases,
                count(*) FILTER (WHERE consecutive_failures > 0) AS with_consecutive_failures
            FROM pi_backfill_jobs;
            """
            r_stats = self.db.execute(text(q_bf_stats)).mappings().first()
            if r_stats:
                expired_leases = int(r_stats["expired_leases"] or 0)
                consecutive_bf_failures = int(r_stats["with_consecutive_failures"] or 0)
        except Exception as exc:
            logger.debug("db_health_backfill_jobs_failed err=%s", exc)

        return FreshnessInfo(
            latest_sample_at=latest_ts,
            latest_recorded_sample_at=latest_rec_ts,
            lag_seconds=lag_seconds,
            oldest_watermark=oldest_wm,
            newest_watermark=newest_wm,
            ingestion_states=ingestion_count,
            tags_in_backoff=in_backoff,
            tags_with_failures=with_failures,
            backfill_jobs_by_status=bf_by_status,
            expired_backfill_leases=expired_leases,
            consecutive_backfill_failures=consecutive_bf_failures,
            last_success_at=last_success_at,
        )

    def _evaluate_checks(
        self,
        conn_info: DatabaseConnectionInfo,
        storage_info: StorageInfo,
        conn_stats: ConnectionsInfo,
        locks_info: LocksInfo,
        timescale_info: TimescaleInfo,
        freshness_info: FreshnessInfo,
    ) -> DatabaseHealthStatus:
        # Connectivity
        self.checks.append(
            HealthCheckItem(
                name="conectividade",
                status=DatabaseHealthStatus.HEALTHY,
                message=f"Banco acessível ({conn_info.name or 'default'}).",
            )
        )

        # Latency check
        lat = conn_info.latency_ms or 0.0
        if lat > 1000.0:
            self.checks.append(
                HealthCheckItem(
                    name="latencia",
                    status=DatabaseHealthStatus.CRITICAL,
                    message=f"Latência muito alta ({lat:.1f} ms).",
                )
            )
        elif lat > 200.0:
            self.checks.append(
                HealthCheckItem(
                    name="latencia",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"Latência elevada ({lat:.1f} ms).",
                )
            )
        else:
            self.checks.append(
                HealthCheckItem(
                    name="latencia",
                    status=DatabaseHealthStatus.HEALTHY,
                    message=f"Latência normal ({lat:.1f} ms).",
                )
            )

        # Connections check
        usage = conn_stats.usage_percent
        crit_pct = settings.db_health_critical_connection_percent
        warn_pct = settings.db_health_high_connection_percent

        if usage >= crit_pct:
            self.checks.append(
                HealthCheckItem(
                    name="conexoes",
                    status=DatabaseHealthStatus.CRITICAL,
                    message=f"Utilização crítica de conexões ({usage:.1f}% de {conn_stats.maximum}).",
                )
            )
        elif usage >= warn_pct:
            self.checks.append(
                HealthCheckItem(
                    name="conexoes",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"Utilização elevada de conexões ({usage:.1f}% de {conn_stats.maximum}).",
                )
            )
        else:
            self.checks.append(
                HealthCheckItem(
                    name="conexoes",
                    status=DatabaseHealthStatus.HEALTHY,
                    message=f"Conexões sob controle ({conn_stats.current}/{conn_stats.maximum} = {usage:.1f}%).",
                )
            )

        # Idle in transaction check
        if conn_stats.idle_in_transaction > settings.db_health_max_idle_in_transaction:
            self.checks.append(
                HealthCheckItem(
                    name="idle_in_transaction",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"Excesso de conexões ociosas em transação ({conn_stats.idle_in_transaction}).",
                )
            )

        # Long transactions & queries
        if conn_stats.long_transactions_count > 0:
            self.checks.append(
                HealthCheckItem(
                    name="transacoes_longas",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"{conn_stats.long_transactions_count} transação(ões) longa(s) detectada(s).",
                )
            )
        if conn_stats.long_queries_count > 0:
            self.checks.append(
                HealthCheckItem(
                    name="queries_longas",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"{conn_stats.long_queries_count} consulta(s) ativa(s) acima de {settings.db_health_long_query_seconds}s.",
                )
            )

        # Deadlocks
        if conn_stats.deadlocks and conn_stats.deadlocks > settings.db_health_max_deadlocks:
            self.checks.append(
                HealthCheckItem(
                    name="deadlocks",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"{conn_stats.deadlocks} deadlocks acumulados desde o reset das estatísticas.",
                )
            )

        # Locks & blocked sessions
        if locks_info.blocked_sessions > 0:
            wait_sec = locks_info.oldest_wait_seconds or 0.0
            if wait_sec > 15.0:
                self.checks.append(
                    HealthCheckItem(
                        name="bloqueios",
                        status=DatabaseHealthStatus.CRITICAL,
                        message=f"{locks_info.blocked_sessions} sessão(ões) bloqueada(s) há mais de {wait_sec:.1f}s.",
                    )
                )
            else:
                self.checks.append(
                    HealthCheckItem(
                        name="bloqueios",
                        status=DatabaseHealthStatus.WARNING,
                        message=f"{locks_info.blocked_sessions} sessão(ões) bloqueada(s) aguardando lock.",
                    )
                )
        else:
            self.checks.append(
                HealthCheckItem(
                    name="bloqueios",
                    status=DatabaseHealthStatus.HEALTHY,
                    message="Nenhuma sessão bloqueada.",
                )
            )

        # TimescaleDB jobs
        if timescale_info.available:
            if timescale_info.failed_jobs > 0:
                self.checks.append(
                    HealthCheckItem(
                        name="timescaledb_jobs",
                        status=DatabaseHealthStatus.WARNING,
                        message=f"{timescale_info.failed_jobs} job(s) interno(s) do TimescaleDB com falha recente.",
                    )
                )
            else:
                self.checks.append(
                    HealthCheckItem(
                        name="timescaledb",
                        status=DatabaseHealthStatus.HEALTHY,
                        message=f"TimescaleDB v{timescale_info.version} operacional ({timescale_info.chunks} chunks).",
                    )
                )

        # Data freshness
        lag = freshness_info.lag_seconds
        crit_lag = settings.db_health_freshness_critical_seconds
        warn_lag = settings.db_health_freshness_tolerance_seconds

        if lag is not None:
            if lag > crit_lag:
                self.checks.append(
                    HealthCheckItem(
                        name="frescor_dados",
                        status=DatabaseHealthStatus.CRITICAL,
                        message=f"Atraso crítico na chegada de dados ({int(lag)}s > {int(crit_lag)}s).",
                    )
                )
            elif lag > warn_lag:
                self.checks.append(
                    HealthCheckItem(
                        name="frescor_dados",
                        status=DatabaseHealthStatus.WARNING,
                        message=f"Dados recentes atrasados ({int(lag)}s > {int(warn_lag)}s).",
                    )
                )
            else:
                self.checks.append(
                    HealthCheckItem(
                        name="frescor_dados",
                        status=DatabaseHealthStatus.HEALTHY,
                        message=f"Dados recentes e atualizados (atraso de {int(lag)}s).",
                    )
                )

        # Ingestion & Backfill issues
        if freshness_info.tags_in_backoff > 0:
            self.checks.append(
                HealthCheckItem(
                    name="ingestao_backoff",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"{freshness_info.tags_in_backoff} tag(s) em backoff de ingestão.",
                )
            )
        if freshness_info.expired_backfill_leases > 0:
            self.checks.append(
                HealthCheckItem(
                    name="backfill_lease",
                    status=DatabaseHealthStatus.WARNING,
                    message=f"{freshness_info.expired_backfill_leases} recarga(s) com lease expirado detectada(s).",
                )
            )

        # Determine overall consolidated status
        has_unavailable = any(c.status == DatabaseHealthStatus.UNAVAILABLE for c in self.checks)
        has_critical = any(c.status == DatabaseHealthStatus.CRITICAL for c in self.checks)
        has_warning = any(c.status == DatabaseHealthStatus.WARNING for c in self.checks)

        if has_unavailable:
            return DatabaseHealthStatus.UNAVAILABLE
        if has_critical:
            return DatabaseHealthStatus.CRITICAL
        if has_warning:
            return DatabaseHealthStatus.WARNING
        return DatabaseHealthStatus.HEALTHY


async def get_database_health(session_factory=None, force_refresh: bool = False) -> DatabaseHealthResponse:
    """Retrieve database health metrics with in-memory caching and request coalescing."""
    global _cached_response, _cached_at

    ttl = settings.db_health_cache_ttl_seconds
    now = time.time()

    # Fast path: valid cache and no force_refresh
    if not force_refresh and _cached_response is not None and (now - _cached_at) < ttl:
        cached_copy = _cached_response.model_copy()
        cached_copy.cached = True
        return cached_copy

    async with _cache_lock:
        now = time.time()
        if not force_refresh and _cached_response is not None and (now - _cached_at) < ttl:
            cached_copy = _cached_response.model_copy()
            cached_copy.cached = True
            return cached_copy

        factory = session_factory or SessionLocal

        # Run collection in threadpool to avoid blocking event loop
        loop = asyncio.get_running_loop()

        def _run_collection() -> DatabaseHealthResponse:
            with factory() as session:
                collector = DatabaseHealthCollector(session)
                return collector.collect()

        # Wrap with timeout
        timeout = settings.db_health_timeout_seconds
        try:
            result = await asyncio.wait_for(loop.run_in_executor(None, _run_collection), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("db_health_collection_timeout timeout=%.1fs", timeout)
            now_utc = datetime.now(timezone.utc)
            return DatabaseHealthResponse(
                status=DatabaseHealthStatus.UNAVAILABLE,
                checked_at=now_utc,
                duration_ms=timeout * 1000,
                cached=False,
                database=DatabaseConnectionInfo(reachable=False),
                storage=StorageInfo(),
                connections=ConnectionsInfo(),
                locks=LocksInfo(),
                timescale=TimescaleInfo(),
                freshness=FreshnessInfo(),
                checks=[
                    HealthCheckItem(
                        name="timeout",
                        status=DatabaseHealthStatus.UNAVAILABLE,
                        message=f"Timeout na coleta de métricas ({timeout:.1f}s excedidos).",
                    )
                ],
                unavailable_metrics=["all_metrics_timed_out"],
            )

        _cached_response = result
        _cached_at = time.time()
        return result
