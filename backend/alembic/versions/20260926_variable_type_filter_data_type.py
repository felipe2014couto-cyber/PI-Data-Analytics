"""Add filter_data_type to variable_types.

Revision ID: 20260926_filter_data_type
Revises: 20260925_section_analysis_tags
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260926_filter_data_type"
down_revision: Union[str, None] = "20260925_section_analysis_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add column with temporary server_default to satisfy NOT NULL during migration
    with op.batch_alter_table("variable_types") as batch_op:
        batch_op.add_column(
            sa.Column(
                "filter_data_type",
                sa.String(length=16),
                nullable=False,
                server_default="REAL",
            )
        )

    # 2. Backfill existing records: UM -> STRING, all others -> REAL
    op.execute(
        sa.text("UPDATE variable_types SET filter_data_type = 'STRING' WHERE code = 'UM'")
    )
    op.execute(
        sa.text("UPDATE variable_types SET filter_data_type = 'REAL' WHERE code != 'UM' OR filter_data_type IS NULL")
    )

    # 3. Remove server_default so that new VariableTypes must explicitly specify their filter_data_type
    with op.batch_alter_table("variable_types") as batch_op:
        batch_op.alter_column(
            "filter_data_type",
            existing_type=sa.String(length=16),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("variable_types") as batch_op:
        batch_op.drop_column("filter_data_type")
