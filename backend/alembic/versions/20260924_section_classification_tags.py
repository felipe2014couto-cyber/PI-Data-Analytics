"""Replace section steel_code with classification tags.

Revision ID: 20260924_cls_tags
Revises: 20260923_section_attributes
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260924_cls_tags"
down_revision: Union[str, None] = "20260923_section_attributes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "classification_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("name", name="uq_classification_tags_name"),
    )
    op.create_table(
        "section_classification_tags",
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("classification_tag_id", sa.Integer(), sa.ForeignKey("classification_tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_section_classification_tags_tag", "section_classification_tags", ["classification_tag_id"])

    # Migrate existing steel codes into classification tags before dropping the column.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, steel_code FROM sections WHERE steel_code IS NOT NULL AND TRIM(steel_code) <> ''")
    ).fetchall()
    tag_ids: dict[str, int] = {}
    for (_, steel_code) in rows:
        name = steel_code.strip().upper()
        if name in tag_ids:
            continue
        existing = bind.execute(
            sa.text("SELECT id FROM classification_tags WHERE name = :name"), {"name": name}
        ).fetchone()
        if existing is not None:
            tag_ids[name] = int(existing[0])
            continue
        insert_result = bind.execute(
            sa.text(
                "INSERT INTO classification_tags (name, created_at, updated_at) "
                "VALUES (:name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"name": name},
        )
        tag_ids[name] = int(insert_result.inserted_primary_key[0])

    for (section_id, steel_code) in rows:
        name = steel_code.strip().upper()
        tag_id = tag_ids.get(name)
        if tag_id is None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO section_classification_tags (section_id, classification_tag_id) "
                "SELECT :section_id, :tag_id WHERE NOT EXISTS ("
                "SELECT 1 FROM section_classification_tags "
                "WHERE section_id = :section_id AND classification_tag_id = :tag_id)"
            ),
            {"section_id": section_id, "tag_id": tag_id},
        )

    is_sqlite = bind.dialect.name == "sqlite"
    with op.batch_alter_table("sections", recreate="always" if is_sqlite else "never") as batch_op:
        batch_op.drop_column("steel_code")


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("sections", recreate="always" if is_sqlite else "never") as batch_op:
        batch_op.add_column(sa.Column("steel_code", sa.String(length=64), nullable=True))
    op.drop_index("ix_section_classification_tags_tag", table_name="section_classification_tags")
    op.drop_table("section_classification_tags")
    op.drop_table("classification_tags")
    # Data loss accepted on downgrade: tag associations and names are removed.
