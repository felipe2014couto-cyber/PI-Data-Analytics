"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-15 13:50:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "equipments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("code", name="uq_equipments_code"),
    )
    op.create_index("ix_equipments_code", "equipments", ["code"], unique=True)
    op.create_index("ix_equipments_active", "equipments", ["active"])

    op.create_table(
        "sections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipments.id"],
            name="fk_sections_equipment_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("equipment_id", "code", name="uq_sections_equipment_code"),
    )
    op.create_index("ix_sections_equipment_id", "sections", ["equipment_id"])
    op.create_index("ix_sections_active", "sections", ["active"])

    op.create_table(
        "variable_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("default_unit", sa.String(length=32), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("code", name="uq_variable_types_code"),
    )
    op.create_index("ix_variable_types_code", "variable_types", ["code"], unique=True)
    op.create_index("ix_variable_types_active", "variable_types", ["active"])

    op.create_table(
        "pi_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("variable_type_id", sa.Integer(), nullable=False),
        sa.Column("pi_server", sa.String(length=128), nullable=False),
        sa.Column("pi_tag_name", sa.String(length=255), nullable=False),
        sa.Column("pi_web_id", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("engineering_unit", sa.String(length=32), nullable=True),
        sa.Column(
            "data_type",
            sa.Enum("NUMERIC", "NON_NUMERIC", name="pi_tag_data_type", native_enum=False, length=32),
            nullable=False,
            server_default="NUMERIC",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "validation_status",
            sa.Enum(
                "PENDING",
                "VALID",
                "INVALID",
                "ERROR",
                name="pi_tag_validation_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("validation_message", sa.String(length=500), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipments.id"],
            name="fk_pi_tags_equipment_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name="fk_pi_tags_section_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["variable_type_id"],
            ["variable_types.id"],
            name="fk_pi_tags_variable_type_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("pi_server", "pi_tag_name", name="uq_pi_tags_server_tag"),
    )
    op.create_index("ix_pi_tags_equipment_id", "pi_tags", ["equipment_id"])
    op.create_index("ix_pi_tags_section_id", "pi_tags", ["section_id"])
    op.create_index("ix_pi_tags_variable_type_id", "pi_tags", ["variable_type_id"])
    op.create_index("ix_pi_tags_pi_tag_name", "pi_tags", ["pi_tag_name"])
    op.create_index("ix_pi_tags_active", "pi_tags", ["active"])
    op.create_index("ix_pi_tags_validation_status", "pi_tags", ["validation_status"])


def downgrade() -> None:
    op.drop_index("ix_pi_tags_validation_status", table_name="pi_tags")
    op.drop_index("ix_pi_tags_active", table_name="pi_tags")
    op.drop_index("ix_pi_tags_pi_tag_name", table_name="pi_tags")
    op.drop_index("ix_pi_tags_variable_type_id", table_name="pi_tags")
    op.drop_index("ix_pi_tags_section_id", table_name="pi_tags")
    op.drop_index("ix_pi_tags_equipment_id", table_name="pi_tags")
    op.drop_table("pi_tags")

    op.drop_index("ix_variable_types_active", table_name="variable_types")
    op.drop_index("ix_variable_types_code", table_name="variable_types")
    op.drop_table("variable_types")

    op.drop_index("ix_sections_active", table_name="sections")
    op.drop_index("ix_sections_equipment_id", table_name="sections")
    op.drop_table("sections")

    op.drop_index("ix_equipments_active", table_name="equipments")
    op.drop_index("ix_equipments_code", table_name="equipments")
    op.drop_table("equipments")
