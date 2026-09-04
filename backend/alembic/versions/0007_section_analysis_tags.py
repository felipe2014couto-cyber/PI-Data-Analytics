"""Add optional analysis tag references to sections.

Revision ID: 0007_section_analysis_tags
Revises: 0006_pi_tag_cep_limits
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_section_analysis_tags"
down_revision: Union[str, None] = "0006_pi_tag_cep_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode keeps the migration compatible with SQLite and allows these
    # optional references to coexist with pi_tags -> sections.
    with op.batch_alter_table("sections", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("width_tag_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("um_tag_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("thickness_tag_id", sa.Integer(), nullable=True))
    op.create_index("ix_sections_width_tag_id", "sections", ["width_tag_id"])
    op.create_index("ix_sections_um_tag_id", "sections", ["um_tag_id"])
    op.create_index("ix_sections_thickness_tag_id", "sections", ["thickness_tag_id"])


def downgrade() -> None:
    op.drop_index("ix_sections_thickness_tag_id", table_name="sections")
    op.drop_index("ix_sections_um_tag_id", table_name="sections")
    op.drop_index("ix_sections_width_tag_id", table_name="sections")
    with op.batch_alter_table("sections", recreate="always") as batch_op:
        batch_op.drop_column("thickness_tag_id")
        batch_op.drop_column("um_tag_id")
        batch_op.drop_column("width_tag_id")
