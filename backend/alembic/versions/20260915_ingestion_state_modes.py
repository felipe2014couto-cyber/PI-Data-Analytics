"""Track ingestion watermarks independently for each tag and source mode."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_ingestion_state_modes"
down_revision: Union[str, None] = "20260914_cep_dependencies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite is used only by the migration fixture.  Keep its existing
        # primary key shape, but expose the same columns to application code.
        with op.batch_alter_table("pi_ingestion_state") as batch:
            batch.add_column(sa.Column("source_mode", sa.String(length=32), nullable=False, server_default="RECORDED"))
            batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        return

    op.add_column("pi_ingestion_state", sa.Column("source_mode", sa.String(length=32), nullable=False, server_default="RECORDED"))
    op.add_column("pi_ingestion_state", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("pi_ingestion_state_pkey", "pi_ingestion_state", type_="primary")
    op.create_primary_key("pi_ingestion_state_pkey", "pi_ingestion_state", ["tag_id", "source_mode"])
    op.create_index("ix_pi_ingestion_state_mode_watermark", "pi_ingestion_state", ["source_mode", "watermark_ts"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pi_ingestion_state") as batch:
            batch.drop_column("next_attempt_at")
            batch.drop_column("source_mode")
        return
    op.drop_index("ix_pi_ingestion_state_mode_watermark", table_name="pi_ingestion_state")
    op.drop_constraint("pi_ingestion_state_pkey", "pi_ingestion_state", type_="primary")
    op.create_primary_key("pi_ingestion_state_pkey", "pi_ingestion_state", ["tag_id"])
    op.drop_column("pi_ingestion_state", "next_attempt_at")
    op.drop_column("pi_ingestion_state", "source_mode")
