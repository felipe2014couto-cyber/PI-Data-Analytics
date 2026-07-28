"""require password change for newly created users

Revision ID: 0003_must_change_password
Revises: 0002_local_users
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0003_must_change_password"
down_revision: Union[str, None] = "0002_local_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    with op.batch_alter_table("users") as batch:
        batch.alter_column("must_change_password", server_default=sa.text("1"), existing_type=sa.Boolean(), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("must_change_password")
