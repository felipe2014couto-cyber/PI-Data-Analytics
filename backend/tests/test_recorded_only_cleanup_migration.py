"""Opt-in PostgreSQL migration test isolated to pi_recorded_cleanup_test_db."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values

from app.core.config import settings

DISPOSABLE_DB = "pi_recorded_cleanup_test_db"
OLD_HEAD = "20261002_sip_history"
NEW_HEAD = "20261003_recorded_only_cleanup"


def _psql(*args: str, sql: str | None = None) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", "-u", "postgres", "pi_analytics-timescaledb-1", "psql", "-v", "ON_ERROR_STOP=1", *args],
        input=sql,
        text=True,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _offline_migration(cfg: Config, action: str) -> str:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        if action == "upgrade":
            command.upgrade(cfg, f"{OLD_HEAD}:{NEW_HEAD}", sql=True)
        else:
            command.downgrade(cfg, f"{NEW_HEAD}:{OLD_HEAD}", sql=True)
    return output.getvalue()


@pytest.mark.skipif(
    os.getenv("RUN_DISPOSABLE_RECORDED_CLEANUP_MIGRATION") != "1",
    reason="explicit opt-in: creates/drops only pi_recorded_cleanup_test_db",
)
def test_recorded_only_cleanup_upgrade_and_downgrade(monkeypatch):
    assert DISPOSABLE_DB.startswith("pi_recorded_cleanup_")
    main_env = "/home/felipe/dev/Dev_analytics/PI-Data-Analytics/backend/.env"
    base_url = dotenv_values(main_env)["DATABASE_URL"]
    monkeypatch.setattr(settings, "database_url", base_url)

    _psql("-d", "postgres", "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{DISPOSABLE_DB}'")
    _psql("-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {DISPOSABLE_DB}")
    _psql("-d", "postgres", "-c", f"CREATE DATABASE {DISPOSABLE_DB} OWNER pi_app")
    try:
        _psql("-d", DISPOSABLE_DB, sql=f"""
            CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('{OLD_HEAD}');
            CREATE TABLE pi_tags (id INTEGER PRIMARY KEY, sampling_mode VARCHAR(20) NOT NULL);
            CREATE EXTENSION IF NOT EXISTS timescaledb;
            CREATE TABLE pi_samples_timescale (
                tag_id INTEGER NOT NULL, ts TIMESTAMPTZ NOT NULL,
                source_mode VARCHAR(32) NOT NULL, value_double DOUBLE PRECISION,
                PRIMARY KEY (tag_id, ts, source_mode)
            );
            SELECT create_hypertable('pi_samples_timescale', 'ts', if_not_exists => TRUE);
            ALTER TABLE pi_samples_timescale SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'tag_id,source_mode',
                timescaledb.compress_orderby = 'ts'
            );
            CREATE TABLE pi_samples (tag_id INTEGER, ts TIMESTAMPTZ, source_mode VARCHAR(32), value_double DOUBLE PRECISION);
            CREATE TABLE pi_ingestion_coverage (id INTEGER PRIMARY KEY, mode VARCHAR(50), interval_seconds INTEGER);
            CREATE TABLE pi_ingestion_state (tag_id INTEGER, source_mode VARCHAR(32), sampling_mode VARCHAR(32));
            CREATE TABLE pi_backfill_jobs (id INTEGER PRIMARY KEY, mode VARCHAR(32));
            INSERT INTO pi_tags VALUES (1, 'INTERPOLATED_10S'), (2, 'RECORDED');
            INSERT INTO pi_samples_timescale VALUES
                (1, now() - interval '100 days', 'INTERPOLATED_10S', 1),
                (2, now() - interval '100 days', 'RECORDED', 2);
            SELECT compress_chunk(chunk) FROM show_chunks('pi_samples_timescale') AS chunk;
            INSERT INTO pi_samples VALUES (1, now(), 'INTERPOLATED_300S', 1), (2, now(), 'RECORDED', 2);
            INSERT INTO pi_ingestion_coverage VALUES (1, 'INTERPOLATED_10S', 10), (2, 'RECORDED', NULL);
            INSERT INTO pi_ingestion_state VALUES (1, 'INTERPOLATED_10S', 'RECORDED'), (2, 'RECORDED', 'RECORDED');
            INSERT INTO pi_backfill_jobs VALUES (1, 'INTERPOLATED_300S'), (2, 'RECORDED');
        """)

        cfg = Config("alembic.ini")
        upgrade_sql = _offline_migration(cfg, "upgrade")
        _psql("-d", DISPOSABLE_DB, sql=upgrade_sql)
        results = _psql("-d", DISPOSABLE_DB, "-At", "-c", """
            SELECT (SELECT string_agg(DISTINCT source_mode, ',') FROM pi_samples_timescale),
                   (SELECT string_agg(DISTINCT source_mode, ',') FROM pi_samples),
                   (SELECT string_agg(DISTINCT mode, ',') FROM pi_ingestion_coverage),
                   (SELECT string_agg(DISTINCT source_mode, ',') FROM pi_ingestion_state),
                   (SELECT string_agg(DISTINCT mode, ',') FROM pi_backfill_jobs),
                   (SELECT count(*) FROM information_schema.columns WHERE table_name IN ('pi_tags','pi_ingestion_state') AND column_name='sampling_mode');
        """)
        assert results.strip().split("|") == ["RECORDED"] * 5 + ["0"]

        downgrade_sql = _offline_migration(cfg, "downgrade")
        _psql("-d", DISPOSABLE_DB, sql=downgrade_sql)
        results = _psql("-d", DISPOSABLE_DB, "-At", "-c", """
            SELECT (SELECT string_agg(sampling_mode, ',' ORDER BY id) FROM pi_tags),
                   (SELECT string_agg(DISTINCT source_mode, ',') FROM pi_samples_timescale),
                   (SELECT version_num FROM alembic_version);
        """)
        assert results.strip().split("|") == ["RECORDED,RECORDED", "RECORDED", OLD_HEAD]
    finally:
        _psql("-d", "postgres", "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{DISPOSABLE_DB}'")
        _psql("-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {DISPOSABLE_DB}")
