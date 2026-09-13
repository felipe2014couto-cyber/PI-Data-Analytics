"""Add the one-minute PI Plot aggregate used by dynamic visual queries."""
from typing import Sequence, Union

from alembic import op


revision: str = "20260922_recorded_plot_1m"
down_revision: Union[str, None] = "20260921_recorded_plot_5m"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE MATERIALIZED VIEW pi_recorded_plot_1m
        WITH (
            timescaledb.continuous,
            timescaledb.materialized_only = false
        ) AS
        SELECT
            tag_id,
            time_bucket(INTERVAL '1 minute', ts) AS bucket,
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
        GROUP BY tag_id, time_bucket(INTERVAL '1 minute', ts)
        WITH NO DATA
        """
    )
    op.execute("CREATE INDEX ix_pi_recorded_plot_1m_tag_bucket ON pi_recorded_plot_1m (tag_id, bucket DESC)")
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'pi_recorded_plot_1m',
            start_offset => INTERVAL '3 days',
            end_offset => INTERVAL '2 minutes',
            schedule_interval => INTERVAL '1 minute'
        )
        """
    )
    op.execute(
        """
        SELECT add_retention_policy(
            'pi_recorded_plot_1m',
            drop_after => INTERVAL '45 days',
            schedule_interval => INTERVAL '1 day'
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SELECT remove_retention_policy('pi_recorded_plot_1m', if_exists => true)")
    op.execute("SELECT remove_continuous_aggregate_policy('pi_recorded_plot_1m', if_exists => true)")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS pi_recorded_plot_1m CASCADE")
