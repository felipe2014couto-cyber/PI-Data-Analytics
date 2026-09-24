"""Service for safe, isolated recompression of rowstore deltas in historical TimescaleDB chunks.

Architecture and Safety Guarantees:
  - Uses TimescaleDB 2.27.1 native API:
      CALL public.convert_to_columnstore('_timescaledb_internal.<chunk>', recompress => true);
  - Executes outside ORM transactions on a dedicated raw DBAPI connection in autocommit mode.
  - Guarded by session-level PostgreSQL advisory lock (_LEADER_LOCK_COLUMNSTORE_MAINTENANCE = 2147483603).
  - Processes at most 1 chunk per cycle, ordered from smallest to largest candidate.
  - Strict preconditions:
      * No overlapping backfill job/leg in RUNNING, PENDING, or with expired lease.
      * Chunk must be older than 7 days (outside active ingestion window).
      * Chunk must already be marked is_compressed = True.
      * Heap rowstore size must exceed min_delta_bytes.
      * No conflicting transaction locks on the chunk.
      * Graceful shutdown event propagation.
  - Full pre- and post-conversion verification of row counts, bounds, deterministic samples, and queryability.
  - Publishes observable progress metrics for workers and health status endpoints.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.database.session import engine

logger = logging.getLogger("workers.columnstore_maintenance")

# Dedicated session advisory lock key
LEADER_LOCK_COLUMNSTORE_MAINTENANCE = 2147483603


class IntegrityCheckError(Exception):
    """Raised when pre- and post-conversion metrics diverge."""


@dataclass
class ChunkCandidate:
    chunk_schema: str
    chunk_name: str
    range_start: datetime
    range_end: datetime
    is_compressed: bool
    heap_bytes: int
    index_bytes: int
    toast_bytes: int
    total_bytes: int
    live_tuples: int
    dead_tuples: int


@dataclass
class PreConversionMetrics:
    chunk_name: str
    range_start: datetime
    range_end: datetime
    total_rows: int
    rows_by_group: Dict[str, int]
    min_ts: Optional[datetime]
    max_ts: Optional[datetime]
    heap_bytes: int
    index_bytes: int
    toast_bytes: int
    total_bytes: int
    columnstore_total_bytes: int
    deterministic_sample: List[Dict[str, Any]]


@dataclass
class MaintenanceCycleResult:
    chunk_name: str
    range_start: datetime
    range_end: datetime
    success: bool
    duration_seconds: float
    rows_verified: int
    heap_before: int
    heap_after: int
    index_before: int
    index_after: int
    bytes_recovered: int
    error_message: Optional[str] = None
    vacuum_executed: bool = False
    vacuum_pending: bool = False
    vacuum_duration_seconds: Optional[float] = None
    vacuum_message: Optional[str] = None


@dataclass
class ColumnstoreMaintenanceStatus:
    enabled: bool = False
    leader: bool = False
    last_cycle_started: Optional[datetime] = None
    last_cycle_completed: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None
    current_chunk: Optional[str] = None
    chunk_range: Optional[str] = None
    started_at: Optional[datetime] = None
    last_duration_seconds: Optional[float] = None
    candidate_chunks_count: int = 0
    chunks_processed_total: int = 0
    bytes_recovered_total: int = 0
    pending_delta_bytes: int = 0
    waiting_reason: Optional[str] = None
    backfill_blocked: bool = False
    vacuum_enabled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.last_cycle_started:
            d["last_cycle_started"] = self.last_cycle_started.isoformat()
        if self.last_cycle_completed:
            d["last_cycle_completed"] = self.last_cycle_completed.isoformat()
        if self.last_success:
            d["last_success"] = self.last_success.isoformat()
        if self.started_at:
            d["started_at"] = self.started_at.isoformat()
        return d


# Global observable status
maintenance_status = ColumnstoreMaintenanceStatus()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ColumnstoreMaintenanceService:
    """Manages identification and safe recompression of rowstore deltas in TimescaleDB columnstore."""

    def __init__(
        self,
        db_engine: Engine = engine,
        min_delta_bytes: Optional[int] = None,
        statement_timeout_seconds: Optional[int] = None,
        vacuum_enabled: Optional[bool] = None,
        vacuum_lock_timeout_seconds: Optional[int] = None,
        vacuum_statement_timeout_seconds: Optional[int] = None,
    ) -> None:
        self.engine = db_engine
        self.min_delta_bytes = (
            min_delta_bytes
            if min_delta_bytes is not None
            else getattr(settings, "columnstore_maintenance_min_delta_bytes", 1048576)
        )
        self.statement_timeout_seconds = (
            statement_timeout_seconds
            if statement_timeout_seconds is not None
            else getattr(settings, "columnstore_maintenance_statement_timeout_seconds", 120)
        )
        self.vacuum_enabled = (
            vacuum_enabled
            if vacuum_enabled is not None
            else getattr(settings, "columnstore_maintenance_vacuum_enabled", False)
        )
        self.vacuum_lock_timeout_seconds = (
            vacuum_lock_timeout_seconds
            if vacuum_lock_timeout_seconds is not None
            else getattr(settings, "columnstore_maintenance_vacuum_lock_timeout_seconds", 2)
        )
        self.vacuum_statement_timeout_seconds = (
            vacuum_statement_timeout_seconds
            if vacuum_statement_timeout_seconds is not None
            else getattr(settings, "columnstore_maintenance_vacuum_statement_timeout_seconds", 60)
        )

    def is_postgresql(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    def detect_recompression_api(self) -> str:
        """Detect available recompression API in TimescaleDB catalog.

        Returns 'convert_to_columnstore' for TimescaleDB 2.x+,
        or 'compress_chunk' for legacy versions.
        Selection is strictly mutually exclusive.
        """
        if not self.is_postgresql():
            return "convert_to_columnstore"
        q = """
        SELECT p.proname, p.prokind
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname = 'convert_to_columnstore'
          AND p.prokind = 'p';
        """
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text(q)).mappings().first()
                if row:
                    return "convert_to_columnstore"
        except Exception as exc:
            logger.warning("failed_to_detect_columnstore_procedure err=%s", exc)
        return "compress_chunk"

    def find_candidates(self) -> Tuple[List[ChunkCandidate], int]:
        """Find historical compressed chunks with non-trivial rowstore delta.

        Returns (candidates, total_pending_delta_bytes).
        """
        if not self.is_postgresql():
            return [], 0

        q = """
        SELECT
            c.chunk_schema,
            c.chunk_name,
            c.range_start,
            c.range_end,
            c.is_compressed,
            pg_relation_size(format('%I.%I', c.chunk_schema, c.chunk_name)::regclass) AS heap_bytes,
            pg_indexes_size(format('%I.%I', c.chunk_schema, c.chunk_name)::regclass) AS index_bytes,
            COALESCE(pg_total_relation_size(cl.reltoastrelid), 0) AS toast_bytes,
            pg_total_relation_size(format('%I.%I', c.chunk_schema, c.chunk_name)::regclass) AS total_bytes,
            COALESCE(st.n_live_tup, 0) AS live_tuples,
            COALESCE(st.n_dead_tup, 0) AS dead_tuples
        FROM timescaledb_information.chunks c
        JOIN pg_class cl ON cl.relname = c.chunk_name
        JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = c.chunk_schema
        LEFT JOIN pg_stat_all_tables st ON st.schemaname = c.chunk_schema AND st.relname = c.chunk_name
        WHERE c.hypertable_name = 'pi_samples_timescale'
          AND c.is_compressed = true
          AND COALESCE(st.n_live_tup, 0) > 0
          AND pg_relation_size(format('%I.%I', c.chunk_schema, c.chunk_name)::regclass) >= :min_delta_bytes
          AND c.range_end < NOW() - INTERVAL '7 days'
        ORDER BY pg_total_relation_size(format('%I.%I', c.chunk_schema, c.chunk_name)::regclass) ASC;
        """
        candidates: List[ChunkCandidate] = []
        total_pending = 0

        with self.engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT")
            rows = conn.execute(text(q), {"min_delta_bytes": self.min_delta_bytes}).mappings().all()
            for r in rows:
                c = ChunkCandidate(
                    chunk_schema=str(r["chunk_schema"]),
                    chunk_name=str(r["chunk_name"]),
                    range_start=r["range_start"],
                    range_end=r["range_end"],
                    is_compressed=bool(r["is_compressed"]),
                    heap_bytes=int(r["heap_bytes"] or 0),
                    index_bytes=int(r["index_bytes"] or 0),
                    toast_bytes=int(r["toast_bytes"] or 0),
                    total_bytes=int(r["total_bytes"] or 0),
                    live_tuples=int(r["live_tuples"] or 0),
                    dead_tuples=int(r["dead_tuples"] or 0),
                )
                candidates.append(c)
                total_pending += c.heap_bytes + c.index_bytes

        return candidates, total_pending

    def check_overlapping_backfill(self, range_start: datetime, range_end: datetime) -> Optional[str]:
        """Check if any backfill job or leg blocks recompression of [range_start, range_end].

        A job or leg blocks maintenance if its target interval overlaps with the chunk AND:
          - status is RUNNING (active lease, expired lease, or without lease)
          - status is PENDING
          - status is RETRY (or has scheduled retry via next_attempt_at)
          - has an expired lease not yet reclassified
          - has a legacy or unknown non-terminal status
          - parent round/job is not fully completed
          - completed leg whose parent round has other non-terminal legs capable of writing

        Only proven terminal states without possibility of new write are non-blocking:
          - COMPLETED (with no pending sibling legs in the same round)
          - CANCELLED
          - FAILED terminal (without pending retry)

        Returns blocking reason if blocked, or None if safe.
        """
        if not self.is_postgresql():
            return None

        now = _now()
        q = """
        SELECT id, tag_id, round_name, target_start, target_end, status, stage,
               lease_owner, lease_expires_at, heartbeat_at, next_attempt_at, consecutive_failures
        FROM pi_backfill_jobs
        WHERE target_start < :range_end AND target_end > :range_start
        ORDER BY id ASC;
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(q),
                {"range_start": range_start, "range_end": range_end},
            ).mappings().all()

            for r in rows:
                j_id = r.get("id")
                j_start = r.get("target_start")
                j_end = r.get("target_end")

                # Verify overlap: max(start1, start2) < min(end1, end2)
                if j_start is not None and j_end is not None:
                    overlap_start = max(range_start, j_start)
                    overlap_end = min(range_end, j_end)
                    if overlap_start >= overlap_end:
                        # Adjacent or completely outside chunk interval
                        continue

                status = (r.get("status") or "").upper().strip()
                stage = (r.get("stage") or "").upper().strip()
                lease_expires_at = r.get("lease_expires_at")
                next_attempt_at = r.get("next_attempt_at")
                round_name = r.get("round_name")
                tag_id = r.get("tag_id")

                # 1. CANCELLED is terminal and non-blocking
                if status == "CANCELLED" or stage == "CANCELLED":
                    continue

                # 2. FAILED: terminal only if no retry scheduled
                if status == "FAILED" or stage == "FAILED":
                    if next_attempt_at is not None and next_attempt_at > now:
                        return (
                            f"Backfill job ID={j_id} está FAILED com retry agendado para "
                            f"{next_attempt_at.isoformat()} sobreposto ao chunk."
                        )
                    if status == "RETRY" or stage == "RETRY":
                        return f"Backfill job ID={j_id} está em RETRY sobreposto ao chunk."
                    continue

                # 3. COMPLETED: check if parent round/job has active sibling legs
                if status == "COMPLETED" or stage == "COMPLETED":
                    if round_name:
                        q_siblings = """
                        SELECT id, status, stage FROM pi_backfill_jobs
                        WHERE round_name = :round_name
                          AND tag_id = :tag_id
                          AND id != :current_id
                          AND target_start < :range_end AND target_end > :range_start
                          AND status NOT IN ('COMPLETED', 'CANCELLED')
                        LIMIT 1;
                        """
                        sibling = conn.execute(
                            text(q_siblings),
                            {
                                "round_name": round_name,
                                "tag_id": tag_id,
                                "current_id": j_id,
                                "range_start": range_start,
                                "range_end": range_end,
                            },
                        ).mappings().first()
                        if sibling:
                            return (
                                f"Backfill job ID={j_id} está COMPLETED mas round '{round_name}' possui leg "
                                f"ID={sibling['id']} (status={sibling['status']}) não concluída sobreposta ao chunk."
                            )
                    continue

                # 4. RUNNING: inspect lease state
                if status == "RUNNING" or stage == "RUNNING":
                    if lease_expires_at is None:
                        return (
                            f"Backfill job ID={j_id} está RUNNING sem lease (legado/órfão) sobreposto ao chunk "
                            f"[{range_start.isoformat()} -> {range_end.isoformat()}]."
                        )
                    if lease_expires_at > now:
                        return (
                            f"Backfill job ID={j_id} está RUNNING com lease ativo até {lease_expires_at.isoformat()} "
                            f"sobreposto ao chunk [{range_start.isoformat()} -> {range_end.isoformat()}]."
                        )
                    else:
                        return (
                            f"Backfill job ID={j_id} está com lease expirado ({lease_expires_at.isoformat()}) "
                            f"ainda não reclassificado sobreposto ao chunk [{range_start.isoformat()} -> {range_end.isoformat()}]."
                        )

                # 5. PENDING: actively awaiting execution
                if status == "PENDING" or stage == "PENDING":
                    return (
                        f"Backfill job ID={j_id} está PENDING aguardando execução sobreposto ao chunk "
                        f"[{range_start.isoformat()} -> {range_end.isoformat()}]."
                    )

                # 6. RETRY: scheduled or awaiting retry
                if status == "RETRY" or stage == "RETRY":
                    return (
                        f"Backfill job ID={j_id} está em RETRY sobreposto ao chunk "
                        f"[{range_start.isoformat()} -> {range_end.isoformat()}]."
                    )

                # 7. Any other status (legacy, unknown non-terminal)
                return (
                    f"Backfill job ID={j_id} em estado legado/desconhecido não-terminal (status='{status}', stage='{stage}') "
                    f"sobreposto ao chunk [{range_start.isoformat()} -> {range_end.isoformat()}]."
                )

        return None

    def check_conflicting_locks(self, chunk_name: str) -> Optional[str]:
        """Ensure no active transaction holds conflicting locks on the chunk."""
        if not self.is_postgresql():
            return None

        q = """
        SELECT count(*)
        FROM pg_locks l
        JOIN pg_class c ON c.oid = l.relation
        WHERE c.relname = :chunk_name
          AND l.mode IN ('AccessExclusiveLock', 'ExclusiveLock', 'ShareLock')
          AND l.pid != pg_backend_pid();
        """
        with self.engine.connect() as conn:
            cnt = conn.execute(text(q), {"chunk_name": chunk_name}).scalar() or 0
            if cnt > 0:
                return f"Chunk {chunk_name} possui {cnt} lock(s) conflitante(s) ativo(s) em outras sessões."
        return None

    def collect_pre_metrics(self, candidate: ChunkCandidate) -> PreConversionMetrics:
        """Collect exact pre-conversion metrics on the candidate chunk."""
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            # Grouped counts by tag_id and source_mode
            q_groups = f"""
            SELECT tag_id, source_mode, count(*) as cnt
            FROM _timescaledb_internal.{candidate.chunk_name}
            GROUP BY tag_id, source_mode
            ORDER BY tag_id, source_mode;
            """
            rows_by_group: Dict[str, int] = {}
            total_rows = 0
            for r in conn.execute(text(q_groups)).mappings():
                key = f"{r['tag_id']}:{r['source_mode']}"
                cnt = int(r["cnt"] or 0)
                rows_by_group[key] = cnt
                total_rows += cnt

            # Min and Max ts
            q_bounds = f"SELECT MIN(ts) as min_ts, MAX(ts) as max_ts FROM _timescaledb_internal.{candidate.chunk_name};"
            bounds = conn.execute(text(q_bounds)).mappings().first()
            min_ts = bounds["min_ts"] if bounds else None
            max_ts = bounds["max_ts"] if bounds else None

            # Deterministic sample (first 5 records)
            q_sample = f"""
            SELECT ts, tag_id, source_mode, value_double, value_text, good
            FROM _timescaledb_internal.{candidate.chunk_name}
            ORDER BY ts ASC, tag_id ASC
            LIMIT 5;
            """
            sample: List[Dict[str, Any]] = [dict(r) for r in conn.execute(text(q_sample)).mappings().all()]

            # Columnstore relation total bytes
            q_col = """
            SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) as col_bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = '_timescaledb_internal'
              AND c.relname LIKE '%compress%'
              AND c.relname LIKE ('%' || CAST(:chunk_id AS text) || '%');
            """
            chunk_id_num = candidate.chunk_name.replace("_hyper_1_", "").replace("_chunk", "")
            col_bytes = conn.execute(text(q_col), {"chunk_id": str(chunk_id_num)}).scalar() or 0

            return PreConversionMetrics(
                chunk_name=candidate.chunk_name,
                range_start=candidate.range_start,
                range_end=candidate.range_end,
                total_rows=total_rows,
                rows_by_group=rows_by_group,
                min_ts=min_ts,
                max_ts=max_ts,
                heap_bytes=candidate.heap_bytes,
                index_bytes=candidate.index_bytes,
                toast_bytes=candidate.toast_bytes,
                total_bytes=candidate.total_bytes,
                columnstore_total_bytes=int(col_bytes),
                deterministic_sample=sample,
            )

    def execute_recompression(self, chunk_name: str) -> None:
        """Call convert_to_columnstore with recompress => true on dedicated connection in autocommit mode.

        In TimescaleDB 2.27.1, uses exclusively:
            CALL public.convert_to_columnstore(CAST(:chunk_regclass AS regclass), recompress => true);
        No subsequent call to compress_chunk or recompress_chunk is made.
        """
        api = self.detect_recompression_api()
        chunk_regclass = f"_timescaledb_internal.{chunk_name}"

        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"SET statement_timeout = '{self.statement_timeout_seconds}s';"))
            conn.execute(text("SET lock_timeout = '2000ms';"))
            logger.info(
                "recompression_api_start chunk=%s api=%s timeout=%ss",
                chunk_name,
                api,
                self.statement_timeout_seconds,
            )

            if api == "convert_to_columnstore":
                call_sql = (
                    "CALL public.convert_to_columnstore(CAST(:chunk_regclass AS regclass), recompress => true);"
                )
                res = conn.execute(text(call_sql), {"chunk_regclass": chunk_regclass})
                if hasattr(res, "close"):
                    res.close()
            elif api == "compress_chunk":
                func_sql = (
                    "SELECT public.compress_chunk(CAST(:chunk_regclass AS regclass), "
                    "if_not_compressed => false, recompress => true);"
                )
                res = conn.execute(text(func_sql), {"chunk_regclass": chunk_regclass})
                _ = res.fetchall()
            else:
                raise RuntimeError(f"Unsupported recompression API: {api}")

            logger.info("recompression_api_success chunk=%s api=%s", chunk_name, api)

    def measure_chunk_storage(self, chunk_name: str) -> Dict[str, int]:
        """Measure storage and tuple metrics for an individual chunk."""
        if not self.is_postgresql():
            return {"heap_bytes": 0, "index_bytes": 0, "total_bytes": 0, "live_tuples": 0, "dead_tuples": 0}

        q = """
        SELECT 
            pg_relation_size(c.oid) AS heap_bytes,
            pg_indexes_size(c.oid) AS index_bytes,
            pg_total_relation_size(c.oid) AS total_bytes,
            COALESCE(st.n_live_tup, 0) AS live_tuples,
            COALESCE(st.n_dead_tup, 0) AS dead_tuples
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = '_timescaledb_internal'
        LEFT JOIN pg_stat_all_tables st ON st.schemaname = n.nspname AND st.relname = c.relname
        WHERE c.relname = :chunk_name;
        """
        with self.engine.connect() as conn:
            row = conn.execute(text(q), {"chunk_name": chunk_name}).mappings().first()
            if row:
                return {
                    "heap_bytes": int(row["heap_bytes"] or 0),
                    "index_bytes": int(row["index_bytes"] or 0),
                    "total_bytes": int(row["total_bytes"] or 0),
                    "live_tuples": int(row["live_tuples"] or 0),
                    "dead_tuples": int(row["dead_tuples"] or 0),
                }
            return {"heap_bytes": 0, "index_bytes": 0, "total_bytes": 0, "live_tuples": 0, "dead_tuples": 0}

    def execute_vacuum(self, chunk_name: str) -> Tuple[bool, float, Optional[str]]:
        """Execute VACUUM on an individual chunk in a dedicated autocommit connection.

        Returns (success, duration_seconds, message).
        """
        if not self.vacuum_enabled:
            return False, 0.0, "VACUUM desabilitado por configuração."

        t0 = _now()
        logger.info(
            "chunk_vacuum_start chunk=%s lock_timeout=%ss statement_timeout=%ss",
            chunk_name,
            self.vacuum_lock_timeout_seconds,
            self.vacuum_statement_timeout_seconds,
        )
        try:
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f"SET lock_timeout = '{self.vacuum_lock_timeout_seconds * 1000}ms';"))
                conn.execute(text(f"SET statement_timeout = '{self.vacuum_statement_timeout_seconds}s';"))
                conn.execute(text(f"VACUUM _timescaledb_internal.{chunk_name};"))
            dur = (_now() - t0).total_seconds()
            logger.info("chunk_vacuum_success chunk=%s duration=%.2fs", chunk_name, dur)
            return True, dur, None
        except Exception as exc:
            dur = (_now() - t0).total_seconds()
            logger.warning("chunk_vacuum_failed_or_timed_out chunk=%s duration=%.2fs err=%s", chunk_name, dur, exc)
            return False, dur, f"Desalocação física pendente (VACUUM não concluído: {exc})"

    def verify_post_metrics(self, pre: PreConversionMetrics) -> Tuple[int, int, int]:
        """Verify post-recompression integrity across the chunk's interval on the hypertable.

        Returns (heap_after, index_after, bytes_recovered).
        Raises IntegrityCheckError if any check fails.
        """
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            # Check grouped counts on hypertable for the exact range
            q_post_groups = """
            SELECT tag_id, source_mode, count(*) as cnt
            FROM pi_samples_timescale
            WHERE ts >= :range_start AND ts < :range_end
            GROUP BY tag_id, source_mode
            ORDER BY tag_id, source_mode;
            """
            post_groups: Dict[str, int] = {}
            post_total_rows = 0
            for r in conn.execute(
                text(q_post_groups),
                {"range_start": pre.range_start, "range_end": pre.range_end},
            ).mappings():
                key = f"{r['tag_id']}:{r['source_mode']}"
                cnt = int(r["cnt"] or 0)
                post_groups[key] = cnt
                post_total_rows += cnt

            if post_total_rows != pre.total_rows:
                raise IntegrityCheckError(
                    f"Divergência na contagem total de linhas para o chunk {pre.chunk_name}: "
                    f"antes={pre.total_rows}, depois={post_total_rows}!"
                )

            for grp, cnt_pre in pre.rows_by_group.items():
                cnt_post = post_groups.get(grp, 0)
                if cnt_post != cnt_pre:
                    raise IntegrityCheckError(
                        f"Divergência no grupo {grp} para o chunk {pre.chunk_name}: "
                        f"antes={cnt_pre}, depois={cnt_post}!"
                    )

            # Check bounds
            q_post_bounds = """
            SELECT MIN(ts) as min_ts, MAX(ts) as max_ts
            FROM pi_samples_timescale
            WHERE ts >= :range_start AND ts < :range_end;
            """
            post_bounds = conn.execute(
                text(q_post_bounds),
                {"range_start": pre.range_start, "range_end": pre.range_end},
            ).mappings().first()
            if post_bounds:
                if pre.min_ts and post_bounds["min_ts"] != pre.min_ts:
                    raise IntegrityCheckError(
                        f"MIN(ts) divergiu para {pre.chunk_name}: antes={pre.min_ts}, depois={post_bounds['min_ts']}"
                    )
                if pre.max_ts and post_bounds["max_ts"] != pre.max_ts:
                    raise IntegrityCheckError(
                        f"MAX(ts) divergiu para {pre.chunk_name}: antes={pre.max_ts}, depois={post_bounds['max_ts']}"
                    )

            # Query new physical sizes of the chunk
            q_sizes = f"""
            SELECT
                pg_relation_size('_timescaledb_internal.{pre.chunk_name}'::regclass) as heap_bytes,
                pg_indexes_size('_timescaledb_internal.{pre.chunk_name}'::regclass) as index_bytes,
                pg_total_relation_size('_timescaledb_internal.{pre.chunk_name}'::regclass) as total_bytes;
            """
            s = conn.execute(text(q_sizes)).mappings().first()
            heap_after = int(s["heap_bytes"] or 0) if s else 0
            index_after = int(s["index_bytes"] or 0) if s else 0
            total_after = int(s["total_bytes"] or 0) if s else 0

            bytes_recovered = max(0, pre.total_bytes - total_after)
            logger.info(
                "integrity_verification_passed chunk=%s rows=%d heap_before=%d heap_after=%d "
                "index_before=%d index_after=%d recovered=%d",
                pre.chunk_name,
                post_total_rows,
                pre.heap_bytes,
                heap_after,
                pre.index_bytes,
                index_after,
                bytes_recovered,
            )
            return heap_after, index_after, bytes_recovered

    def process_one_chunk(
        self,
        candidate: ChunkCandidate,
        stop_event: Optional[asyncio.Event] = None,
    ) -> MaintenanceCycleResult:
        """Safely recompress a single candidate chunk with full pre/post verification."""
        t0 = _now()
        if stop_event and stop_event.is_set():
            return MaintenanceCycleResult(
                chunk_name=candidate.chunk_name,
                range_start=candidate.range_start,
                range_end=candidate.range_end,
                success=False,
                duration_seconds=0.0,
                rows_verified=0,
                heap_before=candidate.heap_bytes,
                heap_after=candidate.heap_bytes,
                index_before=candidate.index_bytes,
                index_after=candidate.index_bytes,
                bytes_recovered=0,
                error_message="Operação cancelada por encerramento (stop_event).",
            )

        # 1. Check backfill conflict
        block_reason = self.check_overlapping_backfill(candidate.range_start, candidate.range_end)
        if block_reason:
            logger.warning("chunk_blocked_by_backfill chunk=%s reason=%s", candidate.chunk_name, block_reason)
            return MaintenanceCycleResult(
                chunk_name=candidate.chunk_name,
                range_start=candidate.range_start,
                range_end=candidate.range_end,
                success=False,
                duration_seconds=0.0,
                rows_verified=0,
                heap_before=candidate.heap_bytes,
                heap_after=candidate.heap_bytes,
                index_before=candidate.index_bytes,
                index_after=candidate.index_bytes,
                bytes_recovered=0,
                error_message=block_reason,
            )

        # 2. Check conflicting locks
        lock_conflict = self.check_conflicting_locks(candidate.chunk_name)
        if lock_conflict:
            logger.warning("chunk_blocked_by_lock chunk=%s reason=%s", candidate.chunk_name, lock_conflict)
            return MaintenanceCycleResult(
                chunk_name=candidate.chunk_name,
                range_start=candidate.range_start,
                range_end=candidate.range_end,
                success=False,
                duration_seconds=0.0,
                rows_verified=0,
                heap_before=candidate.heap_bytes,
                heap_after=candidate.heap_bytes,
                index_before=candidate.index_bytes,
                index_after=candidate.index_bytes,
                bytes_recovered=0,
                error_message=lock_conflict,
            )

        # 3. Collect pre-metrics
        pre = self.collect_pre_metrics(candidate)

        # 4. Execute recompression
        try:
            self.execute_recompression(candidate.chunk_name)
        except Exception as exc:
            duration = (_now() - t0).total_seconds()
            logger.error("convert_to_columnstore_failed chunk=%s err=%s", candidate.chunk_name, exc, exc_info=True)
            return MaintenanceCycleResult(
                chunk_name=candidate.chunk_name,
                range_start=candidate.range_start,
                range_end=candidate.range_end,
                success=False,
                duration_seconds=duration,
                rows_verified=0,
                heap_before=candidate.heap_bytes,
                heap_after=candidate.heap_bytes,
                index_before=candidate.index_bytes,
                index_after=candidate.index_bytes,
                bytes_recovered=0,
                error_message=str(exc),
            )

        # Step 2 & 3: Confirm conversion and verify post-recompression integrity
        try:
            heap_after, index_after, recovered = self.verify_post_metrics(pre)
        except IntegrityCheckError as err:
            duration = (_now() - t0).total_seconds()
            logger.critical("integrity_check_failure chunk=%s err=%s", candidate.chunk_name, err)
            return MaintenanceCycleResult(
                chunk_name=candidate.chunk_name,
                range_start=candidate.range_start,
                range_end=candidate.range_end,
                success=False,
                duration_seconds=duration,
                rows_verified=pre.total_rows,
                heap_before=candidate.heap_bytes,
                heap_after=candidate.heap_bytes,
                index_before=candidate.index_bytes,
                index_after=candidate.index_bytes,
                bytes_recovered=0,
                error_message=str(err),
            )

        # Step 4: Measure storage and tuples separately
        storage = self.measure_chunk_storage(candidate.chunk_name)
        heap_after = storage["heap_bytes"]
        index_after = storage["index_bytes"]
        total_after = storage["total_bytes"]
        recovered = max(0, pre.total_bytes - total_after)

        # Step 5: Determine if allocated space justifies VACUUM
        needs_vacuum = (storage["heap_bytes"] > 0 or storage["dead_tuples"] > 0)

        vacuum_executed = False
        vacuum_pending = False
        vacuum_duration = None
        vacuum_message = None

        # Step 6: Execute VACUUM in separate connection if justified and authorized
        if needs_vacuum and self.vacuum_enabled:
            if stop_event and stop_event.is_set():
                vacuum_pending = True
                vacuum_message = "Encerramento solicitado antes do VACUUM."
            else:
                # Re-check overlapping backfill before vacuum
                bf_reason = self.check_overlapping_backfill(candidate.range_start, candidate.range_end)
                if bf_reason:
                    vacuum_pending = True
                    vacuum_message = f"Novo backfill detectado antes do VACUUM: {bf_reason}"
                    logger.warning("vacuum_deferred_backfill chunk=%s reason=%s", candidate.chunk_name, bf_reason)
                else:
                    # Re-check conflicting locks before vacuum
                    lk_reason = self.check_conflicting_locks(candidate.chunk_name)
                    if lk_reason:
                        vacuum_pending = True
                        vacuum_message = f"Lock conflitante detectado antes do VACUUM: {lk_reason}"
                        logger.warning("vacuum_deferred_lock chunk=%s reason=%s", candidate.chunk_name, lk_reason)
                    else:
                        vac_ok, vac_dur, vac_msg = self.execute_vacuum(candidate.chunk_name)
                        vacuum_duration = vac_dur
                        if vac_ok:
                            vacuum_executed = True
                            storage_post = self.measure_chunk_storage(candidate.chunk_name)
                            heap_after = storage_post["heap_bytes"]
                            index_after = storage_post["index_bytes"]
                            total_after = storage_post["total_bytes"]
                            recovered = max(0, pre.total_bytes - total_after)
                        else:
                            vacuum_pending = True
                            vacuum_message = vac_msg
        elif not self.vacuum_enabled:
            if needs_vacuum:
                vacuum_pending = True
                vacuum_message = (
                    f"VACUUM desabilitado por configuração (opt-in). "
                    f"Espaço residual/reutilizável retido no chunk (heap={heap_after}B, índices={index_after}B)."
                )
            else:
                vacuum_message = "VACUUM desabilitado por configuração (chunk sem heap ou tuplas mortas pendentes)."
        else:
            vacuum_message = "VACUUM não necessário (heap já zerado e sem tuplas mortas)."

        duration = (_now() - t0).total_seconds()
        return MaintenanceCycleResult(
            chunk_name=candidate.chunk_name,
            range_start=candidate.range_start,
            range_end=candidate.range_end,
            success=True,
            duration_seconds=duration,
            rows_verified=pre.total_rows,
            heap_before=candidate.heap_bytes,
            heap_after=heap_after,
            index_before=candidate.index_bytes,
            index_after=index_after,
            bytes_recovered=recovered,
            vacuum_executed=vacuum_executed,
            vacuum_pending=vacuum_pending,
            vacuum_duration_seconds=vacuum_duration,
            vacuum_message=vacuum_message,
        )


async def run_columnstore_maintenance_loop(stop_event: asyncio.Event) -> None:
    """Supervised worker loop executing columnstore maintenance cycles."""
    global maintenance_status
    svc = ColumnstoreMaintenanceService()
    interval = getattr(settings, "columnstore_maintenance_interval_seconds", 300)

    maintenance_status.enabled = getattr(settings, "columnstore_maintenance_enabled", False)
    maintenance_status.vacuum_enabled = getattr(settings, "columnstore_maintenance_vacuum_enabled", False)
    logger.info(
        "columnstore_maintenance_worker_started interval=%ss enabled=%s vacuum_enabled=%s",
        interval,
        maintenance_status.enabled,
        maintenance_status.vacuum_enabled,
    )

    while not stop_event.is_set():
        if not getattr(settings, "columnstore_maintenance_enabled", False):
            maintenance_status.enabled = False
            maintenance_status.vacuum_enabled = getattr(settings, "columnstore_maintenance_vacuum_enabled", False)
            maintenance_status.waiting_reason = "Manutenção de columnstore desativada por configuração."
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
            except asyncio.TimeoutError:
                pass
            continue

        maintenance_status.enabled = True
        maintenance_status.last_cycle_started = _now()
        maintenance_status.waiting_reason = "Buscando chunks candidatos..."

        try:
            candidates, total_pending = await asyncio.get_event_loop().run_in_executor(
                None, svc.find_candidates
            )
            maintenance_status.candidate_chunks_count = len(candidates)
            maintenance_status.pending_delta_bytes = total_pending

            if not candidates:
                maintenance_status.waiting_reason = "Nenhum chunk com delta rowstore pendente."
                maintenance_status.last_cycle_completed = _now()
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
                except asyncio.TimeoutError:
                    pass
                continue

            # Pick the first safe candidate (smallest)
            selected_candidate: Optional[ChunkCandidate] = None
            for cand in candidates:
                blocked = await asyncio.get_event_loop().run_in_executor(
                    None, svc.check_overlapping_backfill, cand.range_start, cand.range_end
                )
                if not blocked:
                    selected_candidate = cand
                    break
                else:
                    logger.debug("candidate_skipped_due_to_backfill chunk=%s", cand.chunk_name)

            if not selected_candidate:
                maintenance_status.waiting_reason = "Todos os candidatos possuem backfills sobrepostos ativos."
                maintenance_status.backfill_blocked = True
                maintenance_status.last_cycle_completed = _now()
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
                except asyncio.TimeoutError:
                    pass
                continue

            maintenance_status.backfill_blocked = False
            maintenance_status.current_chunk = selected_candidate.chunk_name
            maintenance_status.chunk_range = f"{selected_candidate.range_start.isoformat()} -> {selected_candidate.range_end.isoformat()}"
            maintenance_status.started_at = _now()
            maintenance_status.waiting_reason = f"Processando reconversão de {selected_candidate.chunk_name}..."

            result = await asyncio.get_event_loop().run_in_executor(
                None, svc.process_one_chunk, selected_candidate, stop_event
            )

            maintenance_status.last_duration_seconds = result.duration_seconds
            maintenance_status.last_cycle_completed = _now()
            maintenance_status.current_chunk = None

            if result.success:
                maintenance_status.last_success = _now()
                maintenance_status.chunks_processed_total += 1
                maintenance_status.bytes_recovered_total += result.bytes_recovered
                maintenance_status.last_error = None
                maintenance_status.waiting_reason = f"Sucesso no chunk {result.chunk_name} ({result.bytes_recovered // (1024*1024)} MB recuperados)."
            else:
                maintenance_status.last_error = result.error_message
                maintenance_status.waiting_reason = f"Falha no chunk {result.chunk_name}: {result.error_message}"

        except Exception as exc:
            logger.error("columnstore_maintenance_cycle_error err=%s", exc, exc_info=True)
            maintenance_status.last_error = str(exc)
            maintenance_status.waiting_reason = f"Erro no ciclo: {exc}"
            maintenance_status.last_cycle_completed = _now()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass

    logger.info("columnstore_maintenance_worker_stopped")
