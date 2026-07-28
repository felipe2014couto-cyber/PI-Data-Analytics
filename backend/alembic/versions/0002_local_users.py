"""local application users

Revision ID: 0002_local_users
Revises: 0001_initial
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0002_local_users"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("normalized_username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.Enum("ADMIN", "USER", name="userrole", native_enum=False, length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("auth_version >= 1", name="ck_users_auth_version_positive"),
        sa.UniqueConstraint("normalized_username", name="uq_users_normalized_username"),
    )
    op.create_index("ix_users_active_role", "users", ["is_active", "role"])


def downgrade() -> None:
    op.drop_index("ix_users_active_role", table_name="users")
    op.drop_table("users")
