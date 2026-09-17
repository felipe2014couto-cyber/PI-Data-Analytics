"""Add process type, group code and steel code to sections.

Revision ID: 20260923_section_attributes
Revises: 20260922_recorded_plot_1m
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260923_section_attributes"
down_revision: Union[str, None] = "20260922_recorded_plot_1m"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("sections", recreate="always" if is_sqlite else "never") as batch_op:
        batch_op.add_column(sa.Column("process_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("group_code", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("steel_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("sections", recreate="always" if is_sqlite else "never") as batch_op:
        batch_op.drop_column("steel_code")
        batch_op.drop_column("group_code")
        batch_op.drop_column("process_type")