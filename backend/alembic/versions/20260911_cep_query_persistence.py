"""Persist CEP operation lifecycle and terminal results."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_cep_query_persistence"
down_revision: Union[str, None] = "20260910_timescaledb_native"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = sa.JSON()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        json_type = JSONB()

    op.create_table(
        "cep_query_operations",
        sa.Column("query_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request_payload", json_type, nullable=False),
        sa.Column("result_payload", json_type, nullable=True),
        sa.Column("variable_series_payload", json_type, nullable=True),
        sa.Column("error_payload", json_type, nullable=True),
        sa.Column("completed_variables", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_variables", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_work_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_work_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("query_id"),
    )
    op.create_index("ix_cep_query_operations_status", "cep_query_operations", ["status"])
    op.create_index("ix_cep_query_operations_expires_at", "cep_query_operations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_cep_query_operations_expires_at", table_name="cep_query_operations")
    op.drop_index("ix_cep_query_operations_status", table_name="cep_query_operations")
    op.drop_table("cep_query_operations")
