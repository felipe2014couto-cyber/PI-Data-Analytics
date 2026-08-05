"""Optional CEP limit tag references on PI tags.

Revision ID: 0006_pi_tag_cep_limits
Revises: 0005_cep_variables
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_pi_tag_cep_limits"
down_revision: Union[str, None] = "0005_cep_variables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pi_tags", sa.Column("lower_limit_tag", sa.String(length=255), nullable=True))
    op.add_column("pi_tags", sa.Column("upper_limit_tag", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("pi_tags", "upper_limit_tag")
    op.drop_column("pi_tags", "lower_limit_tag")
