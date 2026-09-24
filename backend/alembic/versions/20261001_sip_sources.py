"""Add reusable read-only SIP Oracle sources."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_sip_sources"
down_revision: Union[str, None] = "20260930_section_steel_type_tag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sip_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("variable_type_id", sa.Integer(), sa.ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("timestamp_column", sa.String(128), nullable=False),
        sa.Column("value_column", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_sip_sources_equipment_id", "sip_sources", ["equipment_id"])
    op.create_index("ix_sip_sources_section_id", "sip_sources", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_sip_sources_section_id", table_name="sip_sources")
    op.drop_index("ix_sip_sources_equipment_id", table_name="sip_sources")
    op.drop_table("sip_sources")
