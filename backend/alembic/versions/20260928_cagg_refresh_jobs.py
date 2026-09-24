"""Add durable, range-scoped continuous aggregate refresh jobs."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_cagg_refresh_jobs"
down_revision: Union[str, None] = "20260927_reconcile_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pi_backfill_jobs", sa.Column("materialization_status", sa.String(32), nullable=False, server_default="NOT_REQUESTED"))
    op.add_column("pi_backfill_jobs", sa.Column("materialization_error", sa.Text(), nullable=True))
    op.create_table(
        "pi_cagg_refresh_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backfill_job_id", sa.Integer(), sa.ForeignKey("pi_backfill_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("pi_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_pi_cagg_refresh_jobs_pending", "pi_cagg_refresh_jobs", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_pi_cagg_refresh_jobs_pending", table_name="pi_cagg_refresh_jobs")
    op.drop_table("pi_cagg_refresh_jobs")
    op.drop_column("pi_backfill_jobs", "materialization_error")
    op.drop_column("pi_backfill_jobs", "materialization_status")
