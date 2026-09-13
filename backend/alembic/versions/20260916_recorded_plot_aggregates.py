"""Add hourly and daily Plot-style aggregates for raw RecordedValues."""
from typing import Sequence, Union

from alembic import op


revision: str = "20260916_recorded_plot_cagg"
down_revision: Union[str, None] = "20260915_ingestion_state_modes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NUMERIC = "value_type IN ('double', 'float', 'int')"


def _create_view(name: str, bucket: str) -> None:
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
        WHERE source_mode = 'RECORDED'
          AND {_NUMERIC}
        GROUP BY tag_id, time_bucket(INTERVAL '{bucket}', ts)
        WITH NO DATA
        """
    )
    op.execute(
        f"CREATE INDEX ix_{name}_tag_bucket ON {name} (tag_id, bucket DESC)"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite is used by the migration/test fixture and has no hypertables,
        # continuous aggregates, or Timescale Toolkit hyperfunctions.
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit")
    _create_view("pi_recorded_plot_hourly", "1 hour")
    _create_view("pi_recorded_plot_daily", "1 day")

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


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        "SELECT remove_continuous_aggregate_policy('pi_recorded_plot_daily', if_exists => true)"
    )
    op.execute(
        "SELECT remove_continuous_aggregate_policy('pi_recorded_plot_hourly', if_exists => true)"
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS pi_recorded_plot_daily CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS pi_recorded_plot_hourly CASCADE")
