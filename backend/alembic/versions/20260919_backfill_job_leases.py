"""Add durable leases and retry scheduling to backfill jobs."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260919_backfill_job_leases"
down_revision: Union[str, None] = "20260918_plot_quality_filter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("pi_backfill_jobs", sa.Column("lease_owner", sa.String(length=128), nullable=True))
    op.add_column("pi_backfill_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pi_backfill_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pi_backfill_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_pi_backfill_jobs_resumable",
        "pi_backfill_jobs",
        ["status", "next_attempt_at", "id"]
        if bind.dialect.name == "sqlite"
        else ["status", "round_name", "next_attempt_at", "id"],
    )
    op.create_index(
        "ix_pi_backfill_jobs_expired_lease",
        "pi_backfill_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pi_backfill_jobs_expired_lease", table_name="pi_backfill_jobs")
    op.drop_index("ix_pi_backfill_jobs_resumable", table_name="pi_backfill_jobs")
    op.drop_column("pi_backfill_jobs", "next_attempt_at")
    op.drop_column("pi_backfill_jobs", "heartbeat_at")
    op.drop_column("pi_backfill_jobs", "lease_expires_at")
    op.drop_column("pi_backfill_jobs", "lease_owner")
