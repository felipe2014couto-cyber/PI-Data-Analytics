"""Keep recorded and interpolated samples at the same timestamp."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_timescale_mode_key"
down_revision: Union[str, None] = "20260912_historical_reload_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pi_samples_timescale") as batch:
            batch.drop_constraint("pi_samples_timescale_pkey", type_="primary")
            batch.create_primary_key("pi_samples_timescale_pkey", ["tag_id", "ts", "source_mode"])
    else:
        op.drop_constraint("pi_samples_timescale_pkey", "pi_samples_timescale", type_="primary")
        op.create_primary_key("pi_samples_timescale_pkey", "pi_samples_timescale", ["tag_id", "ts", "source_mode"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pi_samples_timescale") as batch:
            batch.drop_constraint("pi_samples_timescale_pkey", type_="primary")
            batch.create_primary_key("pi_samples_timescale_pkey", ["tag_id", "ts"])
    else:
        op.drop_constraint("pi_samples_timescale_pkey", "pi_samples_timescale", type_="primary")
        op.create_primary_key("pi_samples_timescale_pkey", "pi_samples_timescale", ["tag_id", "ts"])
