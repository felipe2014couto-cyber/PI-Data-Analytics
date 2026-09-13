"""Keep Plot aggregates materialized beyond their selection horizons."""
from typing import Sequence, Union

from alembic import op


revision: str = "20260920_plot_refresh_horizons"
down_revision: Union[str, None] = "20260919_backfill_job_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_policy(name: str, *, start: str, end: str, schedule: str) -> None:
    op.execute(f"SELECT remove_continuous_aggregate_policy('{name}', if_exists => true)")
    op.execute(
        f"""
        SELECT add_continuous_aggregate_policy(
            '{name}',
            start_offset => INTERVAL '{start}',
            end_offset => INTERVAL '{end}',
            schedule_interval => INTERVAL '{schedule}'
        )
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Each refresh horizon exceeds the longest range routed to that aggregate.
    # The safety margin prevents the first display buckets from falling just
    # outside materialization as wall-clock time advances.
    _replace_policy("pi_recorded_plot_10s", start="3 days", end="2 minutes", schedule="1 minute")
    _replace_policy("pi_recorded_plot_hourly", start="32 days", end="2 minutes", schedule="5 minutes")
    _replace_policy("pi_recorded_plot_daily", start="400 days", end="1 hour", schedule="15 minutes")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _replace_policy("pi_recorded_plot_10s", start="2 days", end="2 minutes", schedule="1 minute")
    _replace_policy("pi_recorded_plot_hourly", start="7 days", end="2 minutes", schedule="5 minutes")
    _replace_policy("pi_recorded_plot_daily", start="90 days", end="1 hour", schedule="15 minutes")
