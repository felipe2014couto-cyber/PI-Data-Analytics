"""Add filter_type to section_analysis_tags.

Revision ID: 20260929_section_filter_type
Revises: 20260928_cagg_refresh_jobs
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260929_section_filter_type"
down_revision: Union[str, None] = "20260928_cagg_refresh_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "section_analysis_tags",
        sa.Column(
            "filter_type",
            sa.String(16),
            nullable=False,
            server_default="SELECTION",
        ),
    )


def downgrade() -> None:
    op.drop_column("section_analysis_tags", "filter_type")
