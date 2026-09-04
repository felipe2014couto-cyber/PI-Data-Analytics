"""Allow PI tags to be assigned to an entire equipment.

Revision ID: 0008_pi_tags_equipment_scope
Revises: 0007_section_analysis_tags
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_pi_tags_equipment_scope"
down_revision: Union[str, None] = "0007_section_analysis_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("pi_tags", recreate="always") as batch_op:
        batch_op.alter_column(
            "section_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    # A downgrade is only safe when no equipment-wide tags remain.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM pi_tags WHERE section_id IS NULL")).scalar_one():
        raise RuntimeError("Nao e possivel retornar: existem tags atribuidas ao equipamento inteiro.")
    with op.batch_alter_table("pi_tags", recreate="always") as batch_op:
        batch_op.alter_column(
            "section_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
