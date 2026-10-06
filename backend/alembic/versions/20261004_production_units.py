"""Derived UM segments and unfiltered statistics; RECORDED is untouched."""
import sqlalchemy as sa
from alembic import op

revision = "20261004_production_units"
down_revision = "20261003_recorded_only_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("production_unit_materializations",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('equipment_id', sa.Integer(), sa.ForeignKey('equipments.id', ondelete="CASCADE"), primary_key=False, nullable=False),
        sa.Column('section_id', sa.Integer(), sa.ForeignKey('sections.id', ondelete="CASCADE"), primary_key=False, nullable=True),
        sa.Column('um_tag_id', sa.Integer(), sa.ForeignKey('pi_tags.id', ondelete="CASCADE"), primary_key=False, nullable=False),
        sa.Column('start_ts', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column('end_ts', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column('segments', sa.JSON(), primary_key=False, nullable=False),
        sa.Column('source_versions', sa.JSON(), primary_key=False, nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index('ix_production_unit_materialization_scope', 'production_unit_materializations', ['equipment_id', 'um_tag_id', 'start_ts', 'end_ts'])
    op.create_table("production_unit_segments",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('equipment_id', sa.Integer(), sa.ForeignKey('equipments.id', ondelete="CASCADE"), primary_key=False, nullable=False),
        sa.Column('um_tag_id', sa.Integer(), sa.ForeignKey('pi_tags.id', ondelete="CASCADE"), primary_key=False, nullable=False),
        sa.Column('um_value', sa.String(), primary_key=False, nullable=True),
        sa.Column('start_ts', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column('end_ts', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('end_reason', sa.String(length=32), primary_key=False, nullable=False),
        sa.Column('status', sa.String(length=16), primary_key=False, nullable=False),
        sa.Column('state_ts', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("um_tag_id", "start_ts", name="uq_production_unit_occurrence"),
    )
    op.create_table("production_unit_tag_stats",
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('production_unit_segments.id', ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('pi_tags.id', ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column('raw_sample_count', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('filtered_sample_count', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('sample_count', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('excluded_quality_count', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('average', sa.Float(), primary_key=False, nullable=True),
        sa.Column('minimum', sa.Float(), primary_key=False, nullable=True),
        sa.Column('maximum', sa.Float(), primary_key=False, nullable=True),
        sa.Column('first_timestamp', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('last_timestamp', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('first_value', sa.String(), primary_key=False, nullable=True),
        sa.Column('last_value', sa.String(), primary_key=False, nullable=True),
        sa.Column('source_version', sa.String(length=64), primary_key=False, nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )


def downgrade():
    op.drop_table("production_unit_tag_stats")
    op.drop_table("production_unit_segments")
    op.drop_table("production_unit_materializations")
