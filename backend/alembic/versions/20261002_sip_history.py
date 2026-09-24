"""Persist SIP temporal samples and register scalar database tags."""
import sqlalchemy as sa
from alembic import op

revision = "20261002_sip_history"
down_revision = "20261001_sip_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("sip_samples_timescale",
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sip_sources.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("value_double", sa.Float()), sa.Column("value_text", sa.Text()),
        sa.Column("value_boolean", sa.Boolean()), sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_sip_samples_source_ts", "sip_samples_timescale", ["source_id", "ts"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SELECT create_hypertable('sip_samples_timescale', 'ts', if_not_exists => TRUE, migrate_data => TRUE)")
    op.create_table("sip_reload_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sip_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    op.create_index("ix_sip_reload_jobs_status_id", "sip_reload_jobs", ["status", "id"])
    op.create_table("sip_coverage",
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sip_sources.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("start_time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("query_fingerprint", sa.String(64), nullable=False))
    op.create_table("sip_database_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id", ondelete="RESTRICT")),
        sa.Column("variable_type_id", sa.Integer(), sa.ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("value_column", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))


def downgrade() -> None:
    op.drop_table("sip_database_tags")
    op.drop_table("sip_coverage")
    op.drop_index("ix_sip_reload_jobs_status_id", table_name="sip_reload_jobs")
    op.drop_table("sip_reload_jobs")
    op.drop_index("ix_sip_samples_source_ts", table_name="sip_samples_timescale")
    op.drop_table("sip_samples_timescale")
