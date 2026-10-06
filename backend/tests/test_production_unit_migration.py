"""The UM migration creates derived tables only and has a reversible schema."""
import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_derived_schema_upgrade_indexes_keys_and_downgrade():
    path = Path(__file__).parents[1] / 'alembic/versions/20261004_production_units.py'
    spec = importlib.util.spec_from_file_location('production_unit_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                inspector = inspect(connection)
                assert set(inspector.get_table_names()) == {'production_unit_materializations','production_unit_segments','production_unit_tag_stats'}
                assert inspector.get_pk_constraint('production_unit_tag_stats')['constrained_columns'] == ['segment_id','tag_id']
                assert inspector.get_unique_constraints('production_unit_segments')[0]['column_names'] == ['um_tag_id','start_ts']
                assert inspector.get_indexes('production_unit_materializations')[0]['column_names'] == ['equipment_id','um_tag_id','start_ts','end_ts']
                migration.downgrade()
                assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
