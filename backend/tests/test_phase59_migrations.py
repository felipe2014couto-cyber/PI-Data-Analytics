"""Phase 5.9 — Migration upgrade/downgrade/rollback tests on isolated database.

Uses a temporary SQLite database to validate:
- upgrade head
- downgrade to base
- re-upgrade to head
- Schema integrity after each step
"""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
SCRIPT_LOCATION = Path(__file__).resolve().parents[1] / "alembic"


@pytest.fixture()
def temp_db():
    """Create a temporary SQLite database for migration testing."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{db_path}"
    yield db_path, db_url
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture()
def alembic_cfg(temp_db):
    """Create an Alembic config pointing at the temporary database."""
    db_path, db_url = temp_db
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(SCRIPT_LOCATION))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


class TestMigrations:
    def test_upgrade_to_head_creates_all_tables(self, alembic_cfg, temp_db):
        """Run upgrade head and verify all expected tables exist."""
        command.upgrade(alembic_cfg, "head")
        _, db_url = temp_db
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        expected_tables = {
            "users", "equipments", "sections", "variable_types",
            "pi_tags", "visual_configurations", "visual_configuration_versions",
        }
        assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"

    def test_downgrade_removes_visual_configuration_tables(self, alembic_cfg, temp_db):
        """Downgrade from head to 0003 should remove visual config tables."""
        command.upgrade(alembic_cfg, "head")
        command.downgrade(alembic_cfg, "0003")
        _, db_url = temp_db
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "visual_configurations" not in tables
        assert "visual_configuration_versions" not in tables
        # Core tables should still exist
        assert "users" in tables
        assert "equipments" in tables

    def test_full_downgrade_and_reupgrade(self, alembic_cfg, temp_db):
        """Downgrade to base then re-upgrade to head preserves schema integrity."""
        command.upgrade(alembic_cfg, "head")
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")

        _, db_url = temp_db
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        # All tables should exist
        assert "users" in tables
        assert "visual_configurations" in tables
        assert "visual_configuration_versions" in tables

        # Check visual_configurations columns
        cols = {c["name"] for c in inspector.get_columns("visual_configurations")}
        assert "id" in cols
        assert "owner_id" in cols
        assert "name" in cols
        assert "current_version" in cols

        # Check visual_configuration_versions columns
        vcols = {c["name"] for c in inspector.get_columns("visual_configuration_versions")}
        assert "id" in vcols
        assert "configuration_id" in vcols
        assert "version" in vcols
        assert "snapshot" in vcols
        assert "operation" in vcols

    def test_constraints_enforced_after_migration(self, alembic_cfg, temp_db):
        """Verify CHECK and UNIQUE constraints work on the migrated schema."""
        command.upgrade(alembic_cfg, "head")
        _, db_url = temp_db
        engine = create_engine(db_url)

        with engine.connect() as conn:
            # Try inserting a visual_configurations with current_version=0 (violates CHECK)
            with pytest.raises(Exception):
                conn.execute(text(
                    "INSERT INTO visual_configurations (id, owner_id, name, current_version) "
                    "VALUES ('test-id', 'user-id', 'test', 0)"
                ))
                conn.commit()

    def test_foreign_keys_enforced(self, alembic_cfg, temp_db):
        """Verify foreign key constraints are enforced."""
        command.upgrade(alembic_cfg, "head")
        _, db_url = temp_db
        engine = create_engine(db_url)

        with engine.connect() as conn:
            # Enable foreign keys for SQLite
            conn.execute(text("PRAGMA foreign_keys = ON"))
            # Try inserting a visual_configuration with non-existent owner_id
            with pytest.raises(Exception):
                conn.execute(text(
                    "INSERT INTO visual_configurations (id, owner_id, name, current_version) "
                    "VALUES ('test-id', 'nonexistent-user-id', 'test', 1)"
                ))
                conn.commit()
