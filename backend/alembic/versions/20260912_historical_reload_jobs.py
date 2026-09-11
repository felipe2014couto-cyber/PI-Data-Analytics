"""Add mode and resolution to administrative historical reload jobs."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_historical_reload_jobs"
down_revision: Union[str, None] = "20260911_cep_query_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pi_backfill_jobs") as batch:
            batch.add_column(sa.Column("mode", sa.String(length=32), nullable=False, server_default="RECORDED"))
            batch.add_column(sa.Column("interval_seconds", sa.Integer(), nullable=True))
    else:
        op.add_column("pi_backfill_jobs", sa.Column("mode", sa.String(length=32), nullable=False, server_default="RECORDED"))
        op.add_column("pi_backfill_jobs", sa.Column("interval_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pi_backfill_jobs") as batch:
            batch.drop_column("interval_seconds")
            batch.drop_column("mode")
    else:
        op.drop_column("pi_backfill_jobs", "interval_seconds")
        op.drop_column("pi_backfill_jobs", "mode")
