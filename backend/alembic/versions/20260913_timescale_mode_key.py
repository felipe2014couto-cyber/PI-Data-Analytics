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
        # The SQLite compatibility fixture cannot represent a TimescaleDB
        # hypertable constraint rewrite reliably (its original PK is unnamed).
        # PostgreSQL is the production path and receives the real composite
        # key below; SQLite keeps the prior shape for migration smoke tests.
        return
    else:
        op.drop_constraint("pi_samples_timescale_pkey", "pi_samples_timescale", type_="primary")
        op.create_primary_key("pi_samples_timescale_pkey", "pi_samples_timescale", ["tag_id", "ts", "source_mode"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    else:
        op.drop_constraint("pi_samples_timescale_pkey", "pi_samples_timescale", type_="primary")
        op.create_primary_key("pi_samples_timescale_pkey", "pi_samples_timescale", ["tag_id", "ts"])
