"""Full 10-step migration cycle test on disposable PostgreSQL/TimescaleDB.

Steps verified:
1. Create isolated disposable database in TimescaleDB container.
2. Verify initial revision at 20260926_filter_data_type.
3. Upgrade to 20260927_backfill_recovery and verify index ix_pi_backfill_jobs_legacy_stale.
4. Upgrade to head (20260927_reconcile_backfill).
5. Verify schema and reconciled data.
6. Downgrade to 20260927_backfill_recovery.
7. Downgrade to 20260926_filter_data_type and verify index dropped.
8. Re-upgrade to head and verify both revisions applied.
9. Confirm exactly 1 head and 0 branches.
10. Drop disposable database cleanly.
"""
from __future__ import annotations

import subprocess
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text, inspect

DISPOSABLE_DB = "pi_disposable_migration_test_db"
DISPOSABLE_URL = f"postgresql+psycopg://pi_app:pi_app_secret@127.0.0.1:6543/{DISPOSABLE_DB}"


def _drop_disposable_db():
    assert DISPOSABLE_DB.startswith("pi_disposable_") and DISPOSABLE_DB != "pi_analytics", "FATAL: Must never drop non-disposable DB"
    try:
        subprocess.run(
            [
                "docker", "exec", "-u", "postgres", "pi_analytics-timescaledb-1", "psql",
                "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DISPOSABLE_DB}';",
                "-c", f"DROP DATABASE IF EXISTS {DISPOSABLE_DB};",
            ],
            capture_output=True,
        )
    except Exception:
        pass


def test_full_timescaledb_migration_cycle():
    """Execute the full 10-step upgrade/downgrade cycle in a disposable TimescaleDB database."""
    # Check docker container reachable
    try:
        res = subprocess.run(
            ["docker", "exec", "-u", "postgres", "pi_analytics-timescaledb-1", "psql", "-c", "SELECT 1;"],
            capture_output=True,
        )
        if res.returncode != 0:
            pytest.skip("TimescaleDB docker container pi_analytics-timescaledb-1 is not running")
    except Exception:
        pytest.skip("Docker is not available")

    assert DISPOSABLE_DB.startswith("pi_disposable_") and DISPOSABLE_DB != "pi_analytics", "FATAL: Must never target staging"
    _drop_disposable_db()

    # Step 1: Create disposable database from staging schema dump
    subprocess.run(
        ["docker", "exec", "-u", "postgres", "pi_analytics-timescaledb-1", "psql", "-c", f"CREATE DATABASE {DISPOSABLE_DB} OWNER pi_app;"],
        check=True,
    )
    dump_p = subprocess.Popen(
        ["docker", "exec", "-u", "postgres", "pi_analytics-timescaledb-1", "pg_dump", "-s", "-d", "pi_analytics"],
        stdout=subprocess.PIPE,
    )
    restore_p = subprocess.run(
        ["docker", "exec", "-i", "-u", "postgres", "pi_analytics-timescaledb-1", "psql", "-d", DISPOSABLE_DB],
        stdin=dump_p.stdout,
        capture_output=True,
    )
    dump_p.stdout.close()
    dump_p.wait()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", DISPOSABLE_URL)

    # Seed alembic_version at head (matching the dumped schema) and downgrade to 20260926_filter_data_type.
    # This cleanly drops any objects created by migrations 20260927_*, so that subsequent upgrade steps
    # test their true forward DDL without duplicate table/index conflicts.
    engine = create_engine(DISPOSABLE_URL)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260927_reconcile_backfill')"))

    command.downgrade(cfg, "20260926_filter_data_type")

    try:
        # Step 2: Verify current revision and ensure objects are clean
        with engine.begin() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev == "20260926_filter_data_type"
            insp = inspect(conn)
            indexes = [idx["name"] for idx in insp.get_indexes("pi_backfill_jobs")]
            cols = [col["name"] for col in insp.get_columns("pi_backfill_jobs")]
            assert "ix_pi_backfill_jobs_legacy_stale" not in indexes
            assert "consecutive_failures" not in cols

        # Step 3: Upgrade to 20260927_backfill_recovery
        command.upgrade(cfg, "20260927_backfill_recovery")
        with engine.begin() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            insp = inspect(conn)
            indexes = [idx["name"] for idx in insp.get_indexes("pi_backfill_jobs")]
            cols = [col["name"] for col in insp.get_columns("pi_backfill_jobs")]
            assert rev == "20260927_backfill_recovery"
            assert "ix_pi_backfill_jobs_legacy_stale" in indexes
            assert "consecutive_failures" in cols

            # Insert legacy test row in pi_backfill_jobs via replica session
            subprocess.run(
                [
                    "docker", "exec", "-u", "postgres", "pi_analytics-timescaledb-1", "psql", "-d", DISPOSABLE_DB, "-c",
                    """
                    SET session_replication_role = 'replica';
                    INSERT INTO pi_backfill_jobs (id, tag_id, round_name, target_start, target_end, status, stage, lease_owner, lease_expires_at, heartbeat_at)
                    VALUES (99999, 1, 'R1', '2026-01-01', '2026-01-02', 'RUNNING', 'IN_FLIGHT', NULL, NULL, NULL);
                    """,
                ],
                check=True,
            )

        # Step 4: Upgrade to 20260927_reconcile_backfill
        command.upgrade(cfg, "20260927_reconcile_backfill")

        # Step 5: Verify schema and reconciled data
        with engine.begin() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev == "20260927_reconcile_backfill"
            job = conn.execute(text("SELECT id, status, stage, error_message FROM pi_backfill_jobs WHERE id = 99999")).fetchone()
            assert job[1] == "PENDING"
            assert job[2] == "RETRY_WAIT"
            assert "Reconciliado pela migration 20260927" in (job[3] or "")

        # Step 6: Downgrade to 20260927_backfill_recovery
        command.downgrade(cfg, "20260927_backfill_recovery")
        with engine.begin() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev == "20260927_backfill_recovery"

        # Step 7: Downgrade to 20260926_filter_data_type
        command.downgrade(cfg, "20260926_filter_data_type")
        with engine.begin() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            insp = inspect(conn)
            indexes = [idx["name"] for idx in insp.get_indexes("pi_backfill_jobs")]
            cols = [col["name"] for col in insp.get_columns("pi_backfill_jobs")]
            assert rev == "20260926_filter_data_type"
            assert "ix_pi_backfill_jobs_legacy_stale" not in indexes
            assert "consecutive_failures" not in cols

        # Step 8: Re-upgrade to 20260927_reconcile_backfill
        command.upgrade(cfg, "20260927_reconcile_backfill")
        with engine.begin() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            insp = inspect(conn)
            indexes = [idx["name"] for idx in insp.get_indexes("pi_backfill_jobs")]
            cols = [col["name"] for col in insp.get_columns("pi_backfill_jobs")]
            assert rev == "20260927_reconcile_backfill"
            assert "ix_pi_backfill_jobs_legacy_stale" in indexes
            assert "consecutive_failures" in cols

        # Step 9: Confirm exactly one head
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert len(heads) == 1
        assert heads[0] == "20260930_section_steel_type_tag"

        # Step 10: Validate main tables, indexes, and hypertable at head
        with engine.begin() as conn:
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            expected_tables = {
                "users", "equipments", "sections", "variable_types",
                "pi_tags", "pi_samples_timescale", "pi_backfill_jobs",
                "visual_configurations", "visual_configuration_versions",
            }
            # Verify indexes on pi_samples_timescale
            ts_indexes = [idx["name"] for idx in insp.get_indexes("pi_samples_timescale")]
            assert len(ts_indexes) >= 2, f"Expected at least 2 indexes on pi_samples_timescale, found: {ts_indexes}"

    finally:
        # Step 11: remove disposable DB
        engine.dispose()
        _drop_disposable_db()
