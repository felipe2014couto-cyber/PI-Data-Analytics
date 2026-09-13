"""Add a five-minute PI Plot aggregate for medium visual ranges."""
from typing import Sequence, Union

from alembic import op


revision: str = "20260921_recorded_plot_5m"
down_revision: Union[str, None] = "20260920_plot_refresh_horizons"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE MATERIALIZED VIEW pi_recorded_plot_5m
        WITH (
            timescaledb.continuous,
            timescaledb.materialized_only = false
        ) AS
        SELECT
            tag_id,
            time_bucket(INTERVAL '5 minutes', ts) AS bucket,
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
          AND value_double IS NOT NULL
          AND good IS TRUE
          AND questionable IS FALSE
          AND substituted IS FALSE
        GROUP BY tag_id, time_bucket(INTERVAL '5 minutes', ts)
        WITH NO DATA
        """
    )
    op.execute("CREATE INDEX ix_pi_recorded_plot_5m_tag_bucket ON pi_recorded_plot_5m (tag_id, bucket DESC)")
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'pi_recorded_plot_5m',
            start_offset => INTERVAL '32 days',
            end_offset => INTERVAL '2 minutes',
            schedule_interval => INTERVAL '2 minutes'
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SELECT remove_continuous_aggregate_policy('pi_recorded_plot_5m', if_exists => true)")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS pi_recorded_plot_5m CASCADE")
