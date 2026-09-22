"""Recover legacy RUNNING backfill jobs, add consecutive_failures and index for stale detection.

This migration:
  1. Adds consecutive_failures column (INTEGER NOT NULL DEFAULT 0) to pi_backfill_jobs
     for independent retry backoff control, preserving attempts as claims_count.
  2. Adds an index on (status, lease_expires_at, updated_at) for efficient
     detection of stale legacy RUNNING jobs.
  3. Does NOT destructively reset any jobs: the application code handles
     recovery dynamically at startup.

Revision ID: 20260927_backfill_recovery
Revises: 20260926_filter_data_type
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260927_backfill_recovery"
down_revision: Union[str, None] = "20260926_filter_data_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("pi_backfill_jobs")}
    if "consecutive_failures" not in cols:
        op.add_column(
            "pi_backfill_jobs",
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        )

    # Index for detecting stale legacy RUNNING jobs (no lease, old heartbeat).
    if bind.dialect.name != "sqlite":
        op.create_index(
            "ix_pi_backfill_jobs_legacy_stale",
            "pi_backfill_jobs",
            ["status", "lease_expires_at", "updated_at"],
            postgresql_where=sa.text("status = 'RUNNING' AND lease_expires_at IS NULL"),
        )
    else:
        op.create_index(
            "ix_pi_backfill_jobs_legacy_stale",
            "pi_backfill_jobs",
            ["status", "lease_expires_at", "updated_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("pi_backfill_jobs")}
    if "consecutive_failures" in cols:
        op.drop_column("pi_backfill_jobs", "consecutive_failures")
    op.drop_index("ix_pi_backfill_jobs_legacy_stale", table_name="pi_backfill_jobs")
