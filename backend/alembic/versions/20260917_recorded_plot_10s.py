"""Add the ten-second Plot aggregate for short visual ranges."""
from typing import Sequence, Union

from alembic import op


revision: str = "20260917_recorded_plot_10s"
down_revision: Union[str, None] = "20260916_recorded_plot_cagg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE MATERIALIZED VIEW pi_recorded_plot_10s
        WITH (
            timescaledb.continuous,
            timescaledb.materialized_only = false
        ) AS
        SELECT
            tag_id,
            time_bucket(INTERVAL '10 seconds', ts) AS bucket,
            count(*) AS sample_count,
            min(value_double) AS min_value,
            max(value_double) AS max_value,
            first(value_double, ts) AS first_value,
            last(value_double, ts) AS last_value,
            avg(value_double) AS avg_value,
            min(ts) AS first_ts,
            max(ts) AS last_ts
        FROM pi_samples_timescale
        WHERE source_mode = 'RECORDED'
          AND value_type IN ('double', 'float', 'int')
        GROUP BY tag_id, time_bucket(INTERVAL '10 seconds', ts)
        WITH NO DATA
        """
    )
    op.execute("CREATE INDEX ix_pi_recorded_plot_10s_tag_bucket ON pi_recorded_plot_10s (tag_id, bucket DESC)")
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'pi_recorded_plot_10s',
            start_offset => INTERVAL '2 days',
            end_offset => INTERVAL '2 minutes',
            schedule_interval => INTERVAL '1 minute'
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("SELECT remove_continuous_aggregate_policy('pi_recorded_plot_10s', if_exists => true)")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS pi_recorded_plot_10s CASCADE")
