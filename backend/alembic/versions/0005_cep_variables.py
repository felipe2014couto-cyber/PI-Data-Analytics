"""cep_variables table for CEP variable configuration

Revision ID: 0005_cep_variables
Revises: 0004_visual_configurations
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0005_cep_variables"
down_revision: Union[str, None] = "0004_visual_configurations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cep_variables",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("variable_type_id", sa.Integer(), sa.ForeignKey("variable_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reading_tag_id", sa.Integer(), sa.ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lower_limit_tag_id", sa.Integer(), sa.ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("upper_limit_tag_id", sa.Integer(), sa.ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_tag_id", sa.Integer(), sa.ForeignKey("pi_tags.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("equipment_id", "code", name="uq_cep_variables_equip_code"),
    )
    op.create_index("ix_cep_variables_equipment_id", "cep_variables", ["equipment_id"])
    op.create_index("ix_cep_variables_section_id", "cep_variables", ["section_id"])
    op.create_index("ix_cep_variables_active", "cep_variables", ["active"])


def downgrade() -> None:
    op.drop_index("ix_cep_variables_active", table_name="cep_variables")
    op.drop_index("ix_cep_variables_section_id", table_name="cep_variables")
    op.drop_index("ix_cep_variables_equipment_id", table_name="cep_variables")
    op.drop_table("cep_variables")
