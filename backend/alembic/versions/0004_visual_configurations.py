"""owned versioned visual configurations

Revision ID: 0004_visual_configurations
Revises: 0003_must_change_password
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0004_visual_configurations"
down_revision: Union[str, None] = "0003_must_change_password"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "visual_configurations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("current_version >= 1", name="ck_visual_configurations_version_positive"),
    )
    op.create_index("ix_visual_configurations_owner_updated", "visual_configurations", ["owner_id", "updated_at"])
    op.create_table(
        "visual_configuration_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("configuration_id", sa.String(36), sa.ForeignKey("visual_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("version >= 1", name="ck_visual_configuration_versions_positive"),
        sa.UniqueConstraint("configuration_id", "version", name="uq_visual_configuration_versions_number"),
    )
    op.create_index("ix_visual_configuration_versions_config_created", "visual_configuration_versions", ["configuration_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_visual_configuration_versions_config_created", table_name="visual_configuration_versions")
    op.drop_table("visual_configuration_versions")
    op.drop_index("ix_visual_configurations_owner_updated", table_name="visual_configurations")
    op.drop_table("visual_configurations")
