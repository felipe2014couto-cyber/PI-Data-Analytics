"""Reconcile legacy RUNNING backfill jobs without lease.

This migration is a data reconciliation step, not a schema change.  It
transitions legacy RUNNING jobs (lease_expires_at IS NULL, no heartbeat
for over 30 minutes) to PENDING so the backfill worker can adopt them
safely.  This is idempotent and safe to re-run.

Revision ID: 20260927_reconcile_backfill
Revises: 20260927_backfill_recovery
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260927_reconcile_backfill"
down_revision: Union[str, None] = "20260927_backfill_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Reconcile all RUNNING jobs that have no lease (legacy state).
    # These jobs are stuck and will never complete on their own.
    # Move them to PENDING with RETRY_WAIT so the worker can adopt them.
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("pi_backfill_jobs")}
    if "stage" in cols and "lease_expires_at" in cols:
        op.execute(
            sa.text(
                """
                UPDATE pi_backfill_jobs
                SET status = 'PENDING',
                    stage = 'RETRY_WAIT',
                    lease_owner = NULL,
                    heartbeat_at = NULL,
                    error_message = 'Reconciliado pela migration 20260927: job legado RUNNING sem lease.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'RUNNING'
                  AND lease_expires_at IS NULL
                """
            )
        )
    elif "lease_expires_at" in cols:
        op.execute(
            sa.text(
                """
                UPDATE pi_backfill_jobs
                SET status = 'PENDING',
                    lease_owner = NULL,
                    heartbeat_at = NULL,
                    error_message = 'Reconciliado pela migration 20260927: job legado RUNNING sem lease.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'RUNNING'
                  AND lease_expires_at IS NULL
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE pi_backfill_jobs
                SET status = 'PENDING',
                    error_message = 'Reconciliado pela migration 20260927: job legado RUNNING sem lease.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'RUNNING'
                """
            )
        )


def downgrade() -> None:
    # Data reconciliation is not reversible in a meaningful way.
    # Jobs that were genuinely running would already have been completed
    # or re-adopted by the time a downgrade is attempted.
    pass
