"""Add the optional steel type tag slot to sections."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260930_section_steel_type_tag"
down_revision: Union[str, None] = "20260929_section_filter_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("sections", recreate="always" if is_sqlite else "never") as batch_op:
        batch_op.add_column(sa.Column("steel_type_tag_id", sa.Integer(), nullable=True))
    op.create_index("ix_sections_steel_type_tag_id", "sections", ["steel_type_tag_id"])


def downgrade() -> None:
    op.drop_index("ix_sections_steel_type_tag_id", table_name="sections")
    with op.batch_alter_table("sections", recreate="always" if op.get_bind().dialect.name == "sqlite" else "never") as batch_op:
        batch_op.drop_column("steel_type_tag_id")
