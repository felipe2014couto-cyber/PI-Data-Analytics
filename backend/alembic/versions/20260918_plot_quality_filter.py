"""Filter invalid/non-numeric samples inside Plot aggregates."""
from typing import Sequence, Union

from alembic import op


revision: str = "20260918_plot_quality_filter"
down_revision: Union[str, None] = "20260917_recorded_plot_10s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NUMERIC = """
source_mode = 'RECORDED'
AND value_type IN ('double', 'float', 'int')
AND value_double IS NOT NULL
AND good IS TRUE
AND questionable IS FALSE
AND substituted IS FALSE
"""


def _drop_aggregates() -> None:
    for name in ("pi_recorded_plot_10s", "pi_recorded_plot_hourly", "pi_recorded_plot_daily"):
        op.execute(f"SELECT remove_continuous_aggregate_policy('{name}', if_exists => true)")
    for name in ("pi_recorded_plot_10s", "pi_recorded_plot_hourly", "pi_recorded_plot_daily"):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name} CASCADE")


def _create_aggregate(name: str, bucket: str) -> None:
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {name}
        WITH (
            timescaledb.continuous,
            timescaledb.materialized_only = false
        ) AS
        SELECT
            tag_id,
            time_bucket(INTERVAL '{bucket}', ts) AS bucket,
            count(*) AS sample_count,
            min(value_double) AS min_value,
            max(value_double) AS max_value,
            first(value_double, ts) AS first_value,
            last(value_double, ts) AS last_value,
            avg(value_double) AS avg_value,
            min(ts) AS first_ts,
            max(ts) AS last_ts
        FROM pi_samples_timescale
        WHERE {_NUMERIC}
        GROUP BY tag_id, time_bucket(INTERVAL '{bucket}', ts)
        WITH NO DATA
        """
    )
    op.execute(f"CREATE INDEX ix_{name}_tag_bucket ON {name} (tag_id, bucket DESC)")


def _add_policies() -> None:
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
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'pi_recorded_plot_hourly',
            start_offset => INTERVAL '7 days',
            end_offset => INTERVAL '2 minutes',
            schedule_interval => INTERVAL '5 minutes'
        )
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'pi_recorded_plot_daily',
            start_offset => INTERVAL '90 days',
            end_offset => INTERVAL '1 hour',
            schedule_interval => INTERVAL '15 minutes'
        )
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _drop_aggregates()
    _create_aggregate("pi_recorded_plot_10s", "10 seconds")
    _create_aggregate("pi_recorded_plot_hourly", "1 hour")
    _create_aggregate("pi_recorded_plot_daily", "1 day")
    _add_policies()
    # This index touches the live hypertable.  Build it concurrently so a
    # production ingestion writer is not blocked by the migration lock.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pi_samples_recorded_numeric_quality
            ON pi_samples_timescale (tag_id, ts DESC)
            WHERE source_mode = 'RECORDED'
              AND value_type IN ('double', 'float', 'int')
              AND value_double IS NOT NULL
              AND good IS TRUE
              AND questionable IS FALSE
              AND substituted IS FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_pi_samples_recorded_numeric_quality")
    _drop_aggregates()
