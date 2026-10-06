"""Remove legacy interpolated PI history and sampling selectors.

The forward migration intentionally deletes only operational rows whose source
is one of the retired INTERPOLATED modes. RECORDED rows and recorded CAGGs are
untouched. Downgrade restores the two compatibility columns with RECORDED
defaults, but deleted legacy samples, coverage, states, or jobs are not
reconstructed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_recorded_only_cleanup"
down_revision: Union[str, None] = "20261002_sip_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETIRED_MODES = "('INTERPOLATED_10S', 'INTERPOLATED_300S')"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Compressed Timescale chunks require tuple decompression for DELETE.
        # Scope the limit change to this migration transaction; do not alter
        # server or session configuration outside the cleanup operation.
        op.execute("SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
        # Remove only the retired operational source rows. The legacy table is
        # retained for compatibility, but any such rows are removed as well.
        op.execute(f"DELETE FROM pi_samples_timescale WHERE source_mode IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_samples WHERE source_mode IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_ingestion_coverage WHERE mode IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_ingestion_state WHERE source_mode IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_backfill_jobs WHERE mode IN {_RETIRED_MODES}")
    else:
        op.execute(f"DELETE FROM pi_samples_timescale WHERE upper(source_mode) IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_samples WHERE upper(source_mode) IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_ingestion_coverage WHERE upper(mode) IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_ingestion_state WHERE upper(source_mode) IN {_RETIRED_MODES}")
        op.execute(f"DELETE FROM pi_backfill_jobs WHERE upper(mode) IN {_RETIRED_MODES}")

    if bind.dialect.name == "postgresql":
        op.drop_column("pi_tags", "sampling_mode")
        op.drop_column("pi_ingestion_state", "sampling_mode")
    else:
        inspector = sa.inspect(bind)
        for table_name in ("pi_tags", "pi_ingestion_state"):
            if table_name in inspector.get_table_names() and "sampling_mode" in {
                column["name"] for column in inspector.get_columns(table_name)
            }:
                op.drop_column(table_name, "sampling_mode")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.add_column(
            "pi_ingestion_state",
            sa.Column("sampling_mode", sa.String(length=32), nullable=False, server_default="RECORDED"),
        )
        op.add_column(
            "pi_tags",
            sa.Column("sampling_mode", sa.String(length=20), nullable=False, server_default="RECORDED"),
        )
    else:
        inspector = sa.inspect(bind)
        tables = set(inspector.get_table_names())
        for table_name, length in (("pi_ingestion_state", 32), ("pi_tags", 20)):
            if table_name in tables and "sampling_mode" not in {
                column["name"] for column in inspector.get_columns(table_name)
            }:
                op.add_column(
                    table_name,
                    sa.Column("sampling_mode", sa.String(length=length), nullable=False, server_default="RECORDED"),
                )
