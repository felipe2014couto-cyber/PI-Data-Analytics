"""Add section_analysis_tags table.

Revision ID: 20260925_section_analysis_tags
Revises: 20260924_cls_tags
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260925_section_analysis_tags"
down_revision: Union[str, None] = "20260924_cls_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "section_analysis_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variable_type_id", sa.Integer(), sa.ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pi_tag_id", sa.Integer(), sa.ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("section_id", "variable_type_id", name="uq_section_analysis_tags_section_variable_type"),
    )
    op.create_index("ix_section_analysis_tags_section_id", "section_analysis_tags", ["section_id"])
    op.create_index("ix_section_analysis_tags_variable_type_id", "section_analysis_tags", ["variable_type_id"])
    op.create_index("ix_section_analysis_tags_pi_tag_id", "section_analysis_tags", ["pi_tag_id"])


def downgrade() -> None:
    op.drop_index("ix_section_analysis_tags_pi_tag_id", table_name="section_analysis_tags")
    op.drop_index("ix_section_analysis_tags_variable_type_id", table_name="section_analysis_tags")
    op.drop_index("ix_section_analysis_tags_section_id", table_name="section_analysis_tags")
    op.drop_table("section_analysis_tags")
