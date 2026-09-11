"""Catalog auxiliary PI points referenced by CEP configurations."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_cep_dependencies"
down_revision: Union[str, None] = "20260913_timescale_mode_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pi_tags") as batch:
            batch.add_column(sa.Column("tag_kind", sa.String(length=16), nullable=False, server_default="PRIMARY"))
        op.create_table(
            "cep_variable_tag_dependencies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("variable_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=True),
            sa.Column("dependency_type", sa.String(length=32), nullable=False),
            sa.Column("source_reference", sa.String(length=255), nullable=False),
            sa.Column("pi_web_id", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
            sa.Column("error_message", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["variable_id"], ["cep_variables.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tag_id"], ["pi_tags.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("variable_id", "dependency_type", name="uq_cep_variable_dependency_type"),
        )
        op.create_index("ix_cep_dependency_tag", "cep_variable_tag_dependencies", ["tag_id"])
        op.create_index("ix_cep_dependency_status", "cep_variable_tag_dependencies", ["status"])
        return
    op.add_column("pi_tags", sa.Column("tag_kind", sa.String(length=16), nullable=False, server_default="PRIMARY"))
    op.create_table(
        "cep_variable_tag_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("variable_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=True),
        sa.Column("dependency_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.Column("pi_web_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["variable_id"], ["cep_variables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["pi_tags.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("variable_id", "dependency_type", name="uq_cep_variable_dependency_type"),
    )
    op.create_index("ix_cep_dependency_tag", "cep_variable_tag_dependencies", ["tag_id"])
    op.create_index("ix_cep_dependency_status", "cep_variable_tag_dependencies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_cep_dependency_status", table_name="cep_variable_tag_dependencies")
    op.drop_index("ix_cep_dependency_tag", table_name="cep_variable_tag_dependencies")
    op.drop_table("cep_variable_tag_dependencies")
    op.drop_column("pi_tags", "tag_kind")
