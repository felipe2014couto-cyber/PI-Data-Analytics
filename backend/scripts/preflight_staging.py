"""Safe, read-only preflight diagnostic script for the staging database.

Validates the staging environment, database connectivity, TimescaleDB extensions,
and schema state without modifying data, running migrations, or leaking secrets.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

# Ensure backend root is on sys.path when executed directly
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def _redact_url(raw_url: str) -> str:
    """Safely redact password from a database URL."""
    try:
        u = make_url(raw_url)
        return str(u.set(password="***"))
    except Exception:
        # Fallback to simple parser if dialect is unusual
        parsed = urlparse(raw_url)
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
        return raw_url


def run_preflight(env_file_path: Path | None = None) -> int:
    """Run all preflight checks against staging database."""
    print("=" * 60)
    print("STAGING PREFLIGHT DIAGNOSTIC (READ-ONLY)")
    print("=" * 60)

    # 1. Environment and Config resolution
    selected_env_file = None
    if env_file_path and env_file_path.is_file():
        selected_env_file = env_file_path
    elif Path(".env.staging").is_file():
        selected_env_file = Path(".env.staging")
    elif Path("backend/.env.staging").is_file():
        selected_env_file = Path("backend/.env.staging")

    if selected_env_file:
        print(f"Loading environment from: {selected_env_file}")
        from dotenv import load_dotenv
        load_dotenv(selected_env_file, override=False)

    if not os.environ.get("APP_ENV"):
        os.environ["APP_ENV"] = "staging"

    from app.core.config import Settings
    settings = Settings(
        _env_file=selected_env_file,
        app_env=os.environ.get("APP_ENV", "staging"),
    ) if selected_env_file else Settings()

    db_url = settings.database_url
    redacted_url = _redact_url(db_url)
    parsed = make_url(db_url)

    print(f"Target APP_ENV:       {settings.app_env}")
    print(f"Database Target:      {redacted_url}")
    print(f"Host:                 {parsed.host}")
    print(f"Port:                 {parsed.port}")
    print(f"Database Name:        {parsed.database}")
    print(f"User:                 {parsed.username}")
    print("-" * 60)

    # Sanity checks on target
    if parsed.port not in (6543, 5432):
        print(f"[WARN] Non-standard database port: {parsed.port}")

    # 2. Database Connectivity
    connect_args = {"connect_timeout": 5}
    if settings.database_password is not None and not db_url.startswith("sqlite"):
        connect_args["password"] = settings.database_password.get_secret_value()

    engine = create_engine(db_url, connect_args=connect_args)
    try:
        with engine.connect() as conn:
            # PostgreSQL Version
            version = conn.execute(text("SELECT version();")).scalar()
            print(f"[OK] Connection established")
            print(f"     Engine Version: {str(version).split(',')[0] if version else 'unknown'}")

            # Extensions
            ext_rows = conn.execute(text(
                "SELECT extname, extversion FROM pg_extension WHERE extname IN ('timescaledb', 'pg_stat_statements');"
            )).all()
            ext_map = {name: ver for name, ver in ext_rows}
            print(f"     TimescaleDB extension: {ext_map.get('timescaledb', 'NOT INSTALLED')}")
            print(f"     pg_stat_statements:    {ext_map.get('pg_stat_statements', 'NOT INSTALLED')}")

            # Inspector checks
            insp = inspect(conn)
            table_names = insp.get_table_names()
            print("-" * 60)
            print(f"Database Tables Found: {len(table_names)}")

            # Alembic Version
            current_rev = None
            if "alembic_version" in table_names:
                current_rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
                print(f"Current Alembic Revision: {current_rev}")
            else:
                print("[WARN] alembic_version table does NOT exist")

            # pi_backfill_jobs
            if "pi_backfill_jobs" in table_names:
                cols = [c["name"] for c in insp.get_columns("pi_backfill_jobs")]
                has_cf = "consecutive_failures" in cols
                print(f"pi_backfill_jobs table: EXISTS (columns={len(cols)}, has consecutive_failures={has_cf})")

                job_count = conn.execute(text("SELECT COUNT(*) FROM pi_backfill_jobs;")).scalar()
                status_rows = conn.execute(text(
                    "SELECT status, COUNT(*) FROM pi_backfill_jobs GROUP BY status ORDER BY status;"
                )).all()
                print(f"  Total backfill jobs: {job_count}")
                for st, count in status_rows:
                    print(f"    - status '{st}': {count}")

                # Check job 7188 if present
                cf_col_sql = ", consecutive_failures" if has_cf else ""
                job_7188 = conn.execute(text(
                    f"SELECT id, tag_id, status, stage, attempts, checkpoint_start, next_start, "
                    f"target_end, lease_owner, lease_expires_at, heartbeat_at, next_attempt_at, "
                    f"error_message {cf_col_sql} "
                    f"FROM pi_backfill_jobs WHERE id = 7188;"
                )).mappings().first()
                if job_7188:
                    print(f"  Job 7188 details:")
                    print(f"    id:                   {job_7188['id']}")
                    print(f"    tag_id:               {job_7188['tag_id']}")
                    print(f"    status:               {job_7188['status']}")
                    print(f"    stage:                {job_7188['stage']}")
                    print(f"    attempts:             {job_7188['attempts']}")
                    print(f"    checkpoint_start:     {job_7188['checkpoint_start']}")
                    print(f"    next_start:           {job_7188['next_start']}")
                    print(f"    target_end:           {job_7188['target_end']}")
                    print(f"    lease_owner:          {job_7188['lease_owner']}")
                    print(f"    lease_expires_at:     {job_7188['lease_expires_at']}")
                    print(f"    heartbeat_at:         {job_7188['heartbeat_at']}")
                    print(f"    next_attempt_at:      {job_7188['next_attempt_at']}")
                    print(f"    error_message:        {job_7188['error_message']}")
                    print(f"    consecutive_failures: {job_7188.get('consecutive_failures', 'COLUMN_NOT_PRESENT')}")
                else:
                    print(f"  Job 7188: NOT FOUND in pi_backfill_jobs")
            else:
                print("[INFO] pi_backfill_jobs table does NOT exist yet")

            # pi_ingestion_state
            if "pi_ingestion_state" in table_names:
                state_count = conn.execute(text("SELECT COUNT(*) FROM pi_ingestion_state;")).scalar()
                wm_count = conn.execute(text("SELECT COUNT(*) FROM pi_ingestion_state WHERE watermark_ts IS NOT NULL;")).scalar()
                print(f"pi_ingestion_state table: EXISTS (total_rows={state_count}, non_null_watermarks={wm_count})")
            else:
                print("[INFO] pi_ingestion_state table does NOT exist yet")

    except Exception as exc:
        print(f"[ERROR] Database preflight check failed: {exc}")
        return 1

    print("=" * 60)
    print("PREFLIGHT CHECK COMPLETED SUCCESSFULLY (No changes made)")
    print("=" * 60)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only preflight diagnostic for staging")
    parser.add_argument("--env-file", type=Path, default=None, help="Path to staging .env file")
    args = parser.parse_args()
    sys.exit(run_preflight(args.env_file))


if __name__ == "__main__":
    main()
