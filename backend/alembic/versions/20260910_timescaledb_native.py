"""Create the non-destructive TimescaleDB storage and durable job metadata.

The legacy ``pi_samples`` table is deliberately left untouched.  This
revision creates ``pi_samples_timescale`` and copies legacy rows with an
idempotent UPSERT so it can be run after a validated dump restore.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260910_timescaledb_native"
down_revision: Union[str, None] = "e03e14f8ffdd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Keep the repository's SQLite migration fixture usable. This branch
        # is never a production target and deliberately does not pretend to
        # provide a hypertable or TimescaleDB extension.
        op.create_table(
            "pi_samples_timescale",
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
            sa.Column("value_type", sa.String(length=12), nullable=False),
            sa.Column("value_double", sa.Float()),
            sa.Column("value_text", sa.Text()),
            sa.Column("value_boolean", sa.Boolean()),
            sa.Column("good", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("questionable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("substituted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_mode", sa.String(length=32), nullable=False),
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("tag_id", "ts"),
        )
        return

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                RAISE EXCEPTION 'TimescaleDB nao esta instalada. Valide CREATE EXTENSION antes do upgrade.';
            END IF;
        END $$;
        """
    )
    op.create_table(
        "pi_samples_timescale",
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value_type", sa.String(length=12), nullable=False),
        sa.Column("value_double", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("good", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("questionable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("substituted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tag_id"], ["pi_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tag_id", "ts"),
    )
    op.execute(
        "SELECT create_hypertable('pi_samples_timescale', 'ts', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    op.create_index("ix_pi_samples_timescale_tag_ts", "pi_samples_timescale", ["tag_id", "ts"])

    # Existing attempts created this table before adding the complete coverage
    # contract.  ADD COLUMN IF NOT EXISTS keeps the migration safe on either
    # a restored vanilla database or a fresh staging database.
    op.execute("ALTER TABLE pi_ingestion_coverage ADD COLUMN IF NOT EXISTS interval_seconds INTEGER")
    op.execute("ALTER TABLE pi_ingestion_coverage ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'COMPLETE'")
    op.execute("ALTER TABLE pi_ingestion_coverage ADD COLUMN IF NOT EXISTS pi_web_id VARCHAR(255)")
    op.execute("ALTER TABLE pi_ingestion_coverage ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("UPDATE pi_ingestion_coverage SET status = 'LEGACY_UNVERIFIED' WHERE lower(mode) = 'empty'")
    op.execute("UPDATE pi_ingestion_coverage SET mode = 'RECORDED' WHERE lower(mode) IN ('recorded', 'backfill')")
    op.execute(
        "ALTER TABLE pi_ingestion_coverage ADD CONSTRAINT ck_pi_ingestion_coverage_range "
        "CHECK (range_start < range_end)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_pi_ingestion_coverage_lookup ON pi_ingestion_coverage (tag_id, mode, interval_seconds, range_start, range_end)")

    op.execute("ALTER TABLE pi_ingestion_state ADD COLUMN IF NOT EXISTS watermark_ts TIMESTAMPTZ")
    op.execute("ALTER TABLE pi_ingestion_state ADD COLUMN IF NOT EXISTS sampling_mode VARCHAR(32) NOT NULL DEFAULT 'RECORDED'")
    op.execute("ALTER TABLE pi_backfill_jobs ADD COLUMN IF NOT EXISTS t0 TIMESTAMPTZ")
    op.execute("ALTER TABLE pi_backfill_jobs ADD COLUMN IF NOT EXISTS round_name VARCHAR(8)")
    op.execute("ALTER TABLE pi_backfill_jobs ADD COLUMN IF NOT EXISTS stage VARCHAR(32) NOT NULL DEFAULT 'PENDING'")
    op.execute("ALTER TABLE pi_backfill_jobs ADD COLUMN IF NOT EXISTS checkpoint_start TIMESTAMPTZ")
    op.execute("ALTER TABLE pi_backfill_jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE pi_backfill_jobs ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ")
    op.execute("ALTER TABLE pi_tag_deletion_jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE pi_tag_deletion_jobs ADD COLUMN IF NOT EXISTS last_error TEXT")

    # Copy, never rename or drop, the legacy table.  Values from previous
    # workers are normalized to the explicit per-tag mode contract.
    op.execute(
        """
        INSERT INTO pi_samples_timescale (
            tag_id, ts, value_type, value_double, value_text, value_boolean,
            good, questionable, substituted, source_mode
        )
        SELECT tag_id, ts, value_type, value_double, value_text, value_boolean,
               good, questionable, substituted,
               CASE WHEN upper(source_mode) LIKE 'INTERPOLATED%' THEN upper(source_mode)
                    ELSE 'RECORDED' END
        FROM pi_samples
        ON CONFLICT (tag_id, ts) DO UPDATE SET
            value_type = EXCLUDED.value_type,
            value_double = EXCLUDED.value_double,
            value_text = EXCLUDED.value_text,
            value_boolean = EXCLUDED.value_boolean,
            good = EXCLUDED.good,
            questionable = EXCLUDED.questionable,
            substituted = EXCLUDED.substituted,
            source_mode = EXCLUDED.source_mode
        """
    )

    # Hypercore is the only compression strategy for the pinned TimescaleDB
    # image.  The fallback is retained solely for a deliberately older image
    # used in a compatibility test; both branches are mutually exclusive.
    op.execute(
        """
        DO $$
        DECLARE
            v_major INTEGER;
            v_minor INTEGER;
        BEGIN
            v_major := split_part((SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'), '.', 1)::INTEGER;
            v_minor := split_part((SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'), '.', 2)::INTEGER;
            IF v_major > 2 OR (v_major = 2 AND v_minor >= 18) THEN
                ALTER TABLE pi_samples_timescale SET (
                    timescaledb.enable_columnstore = true,
                    timescaledb.segmentby = 'tag_id',
                    timescaledb.orderby = 'ts DESC'
                );
                CALL add_columnstore_policy('pi_samples_timescale', after => INTERVAL '7 days', if_not_exists => TRUE);
            ELSE
                ALTER TABLE pi_samples_timescale SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'tag_id',
                    timescaledb.compress_orderby = 'ts DESC'
                );
                PERFORM add_compression_policy('pi_samples_timescale', compress_after => INTERVAL '7 days', if_not_exists => TRUE);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Rollback keeps the legacy table and data.  Remove only objects created by
    # this revision; the earlier native table remains available for recovery.
    op.execute("DROP INDEX IF EXISTS ix_pi_samples_timescale_tag_ts")
    op.drop_table("pi_samples_timescale")
