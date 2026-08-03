"""Tests for CEP variable seed and model constraints."""
import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ALEMBIC_DIR = ROOT / "alembic"
ALEMBIC_INI = ROOT / "alembic.ini"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_module", SCRIPTS / "seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Migration tests (real alembic upgrade/downgrade)
# ---------------------------------------------------------------------------

class TestCepMigration:
    """Test actual alembic upgrade and downgrade for cep_variables."""

    def _run_alembic(self, db_url: str, direction: str) -> subprocess.CompletedProcess:
        """Run alembic upgrade/downgrade against a temporary database."""
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        cmd = [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", direction, "head"]
        if direction == "downgrade":
            cmd = [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "downgrade", "0004_visual_configurations"]
        return subprocess.run(
            cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
        )

    def test_upgrade_creates_cep_variables_table(self):
        """Upgrade from 0004 creates the cep_variables table."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db_url = f"sqlite:///{db_path}"
            # First run full upgrade to get all tables
            env = os.environ.copy()
            env["DATABASE_URL"] = db_url
            subprocess.run(
                [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
            )
            # Verify cep_variables exists
            engine = create_engine(db_url)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            assert "cep_variables" in tables
            # Verify columns
            columns = {col["name"] for col in inspector.get_columns("cep_variables")}
            assert "id" in columns
            assert "equipment_id" in columns
            assert "section_id" in columns
            assert "variable_type_id" in columns
            assert "reading_tag_id" in columns
            assert "lower_limit_tag_id" in columns
            assert "upper_limit_tag_id" in columns
            assert "target_tag_id" in columns
            assert "code" in columns
            assert "name" in columns
            assert "active" in columns
            assert "created_at" in columns
            assert "updated_at" in columns
            # Verify target_tag_id is nullable
            target_col = [col for col in inspector.get_columns("cep_variables") if col["name"] == "target_tag_id"][0]
            assert target_col["nullable"] is True
            engine.dispose()
        finally:
            os.unlink(db_path)

    def test_downgrade_removes_cep_variables(self):
        """Downgrade from 0005 removes only cep_variables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db_url = f"sqlite:///{db_path}"
            env = os.environ.copy()
            env["DATABASE_URL"] = db_url
            # Full upgrade
            subprocess.run(
                [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
            )
            # Downgrade
            result = subprocess.run(
                [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "downgrade", "0004_visual_configurations"],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"Downgrade failed: {result.stderr}"
            # Verify cep_variables is gone
            engine = create_engine(db_url)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            assert "cep_variables" not in tables
            # Verify other tables still exist
            assert "equipments" in tables
            assert "pi_tags" in tables
            assert "visual_configurations" in tables
            engine.dispose()
        finally:
            os.unlink(db_path)

    def test_reupgrade_after_downgrade(self):
        """Re-upgrade after downgrade recreates the table cleanly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db_url = f"sqlite:///{db_path}"
            env = os.environ.copy()
            env["DATABASE_URL"] = db_url
            # Upgrade
            subprocess.run(
                [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
            )
            # Downgrade
            subprocess.run(
                [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "downgrade", "0004_visual_configurations"],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
            )
            # Re-upgrade
            result = subprocess.run(
                [str(ALEMBIC_INI.parent / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"Re-upgrade failed: {result.stderr}"
            engine = create_engine(db_url)
            inspector = inspect(engine)
            assert "cep_variables" in inspector.get_table_names()
            engine.dispose()
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Seed rollback test
# ---------------------------------------------------------------------------

class TestCepSeedRollback:
    """Test that seed failure mid-execution rolls back all changes."""

    def test_rollback_on_failure_after_partial_work(self, db_session: Session):
        """If upsert_cep_variables fails, no CEP variables should persist."""
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        # Run seed once to establish baseline
        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        baseline_count = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).count()
        assert baseline_count == 24

        # Monkeypatch upsert_cep_variables to fail
        original_func = seed.upsert_cep_variables

        def failing_upsert(db):
            # Do some work to prove rollback is needed
            db.query(CepVariable).filter(CepVariable.equipment_id == eq.id).delete()
            db.flush()
            raise RuntimeError("Simulated failure in cep_variables seed")

        seed.upsert_cep_variables = failing_upsert
        try:
            with pytest.raises(RuntimeError, match="Simulated failure"):
                seed.run_seed()
        finally:
            seed.upsert_cep_variables = original_func

        # Verify rollback: count should still be 24
        db_session.expire_all()
        after_count = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).count()
        assert after_count == 24, f"Expected 24 after rollback, got {after_count}"


# ---------------------------------------------------------------------------
# Migration and model tests
# ---------------------------------------------------------------------------

class TestCepVariableModel:
    def test_table_exists(self, db_session: Session):
        from app.models.cep_variable import CepVariable
        result = db_session.query(CepVariable).count()
        assert result == 0

    def test_create_cep_variable(self, db_session: Session):
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment
        from app.models.section import Section
        from app.models.variable_type import VariableType
        from app.models.pi_tag import PiTag, PiTagDataType, PiTagValidationStatus

        eq = Equipment(code="TEST_EQ", name="Test Equipment", active=True)
        db_session.add(eq)
        db_session.flush()

        sec = Section(equipment_id=eq.id, code="TEST_SEC", name="Test Section", active=True)
        db_session.add(sec)
        db_session.flush()

        vt = VariableType(code="TEST_VT", name="Test Variable Type", active=True)
        db_session.add(vt)
        db_session.flush()

        reading = PiTag(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            pi_server="PIMS", pi_tag_name="TEST_READING", display_name="Test Reading",
            data_type=PiTagDataType.NUMERIC, validation_status=PiTagValidationStatus.PENDING, active=True,
        )
        lower = PiTag(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            pi_server="PIMS", pi_tag_name="TEST_LOWER", display_name="Test Lower",
            data_type=PiTagDataType.NUMERIC, validation_status=PiTagValidationStatus.PENDING, active=True,
        )
        upper = PiTag(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            pi_server="PIMS", pi_tag_name="TEST_UPPER", display_name="Test Upper",
            data_type=PiTagDataType.NUMERIC, validation_status=PiTagValidationStatus.PENDING, active=True,
        )
        db_session.add_all([reading, lower, upper])
        db_session.flush()

        cv = CepVariable(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            reading_tag_id=reading.id, lower_limit_tag_id=lower.id, upper_limit_tag_id=upper.id,
            code="TEST_CEP", name="Test CEP Variable", active=True,
        )
        db_session.add(cv)
        db_session.commit()

        assert cv.id is not None
        assert cv.code == "TEST_CEP"
        assert cv.active is True

    def test_target_tag_optional(self, db_session: Session):
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment
        from app.models.section import Section
        from app.models.variable_type import VariableType
        from app.models.pi_tag import PiTag, PiTagDataType, PiTagValidationStatus

        eq = Equipment(code="TEST_EQ2", name="Test Equipment 2", active=True)
        db_session.add(eq)
        db_session.flush()
        sec = Section(equipment_id=eq.id, code="TEST_SEC2", name="Test Section 2", active=True)
        db_session.add(sec)
        db_session.flush()
        vt = VariableType(code="TEST_VT2", name="Test Variable Type 2", active=True)
        db_session.add(vt)
        db_session.flush()

        tags = []
        for name in ["R", "L", "U"]:
            t = PiTag(
                equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
                pi_server="PIMS", pi_tag_name=f"TAG_{name}", display_name=f"Tag {name}",
                data_type=PiTagDataType.NUMERIC, validation_status=PiTagValidationStatus.PENDING, active=True,
            )
            tags.append(t)
        db_session.add_all(tags)
        db_session.flush()

        cv = CepVariable(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            reading_tag_id=tags[0].id, lower_limit_tag_id=tags[1].id, upper_limit_tag_id=tags[2].id,
            target_tag_id=None, code="NO_TARGET", name="No Target", active=True,
        )
        db_session.add(cv)
        db_session.commit()
        assert cv.target_tag_id is None

    def test_unique_constraint_equipment_code(self, db_session: Session):
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment
        from app.models.section import Section
        from app.models.variable_type import VariableType
        from app.models.pi_tag import PiTag, PiTagDataType, PiTagValidationStatus

        eq = Equipment(code="TEST_EQ3", name="Test Equipment 3", active=True)
        db_session.add(eq)
        db_session.flush()
        sec = Section(equipment_id=eq.id, code="TEST_SEC3", name="Test Section 3", active=True)
        db_session.add(sec)
        db_session.flush()
        vt = VariableType(code="TEST_VT3", name="Test Variable Type 3", active=True)
        db_session.add(vt)
        db_session.flush()

        tags = []
        for name in ["R", "L", "U"]:
            t = PiTag(
                equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
                pi_server="PIMS", pi_tag_name=f"TAG3_{name}", display_name=f"Tag3 {name}",
                data_type=PiTagDataType.NUMERIC, validation_status=PiTagValidationStatus.PENDING, active=True,
            )
            tags.append(t)
        db_session.add_all(tags)
        db_session.flush()

        cv1 = CepVariable(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            reading_tag_id=tags[0].id, lower_limit_tag_id=tags[1].id, upper_limit_tag_id=tags[2].id,
            code="DUP_TEST", name="First", active=True,
        )
        db_session.add(cv1)
        db_session.commit()

        cv2 = CepVariable(
            equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
            reading_tag_id=tags[0].id, lower_limit_tag_id=tags[1].id, upper_limit_tag_id=tags[2].id,
            code="DUP_TEST", name="Second", active=True,
        )
        db_session.add(cv2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------

class TestCepSeed:
    def test_24_cep_variables_created(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        count = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).count()
        assert count == 24

    def test_three_sections_used(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment
        from app.models.section import Section

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        section_ids = (
            db_session.query(CepVariable.section_id)
            .filter(CepVariable.equipment_id == eq.id)
            .distinct()
            .all()
        )
        section_codes = set()
        for (sid,) in section_ids:
            sec = db_session.query(Section).get(sid)
            section_codes.add(sec.code)
        assert section_codes == {"DECAPAGEM_ELETROLITICA", "DECAPAGEM_QUIMICA", "FORNO"}

    def test_24_readings_24_lowers_24_uppers(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        variables = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).all()
        assert len(variables) == 24
        assert all(v.reading_tag_id is not None for v in variables)
        assert all(v.lower_limit_tag_id is not None for v in variables)
        assert all(v.upper_limit_tag_id is not None for v in variables)

    def test_only_velocity_has_target(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        variables = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).all()
        targets = [v for v in variables if v.target_tag_id is not None]
        assert len(targets) == 1
        assert targets[0].code == "VEL"

    def test_73_references_associated(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        variables = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).all()
        # 24 readings + 24 lowers + 24 uppers + 1 target = 73
        total_refs = 0
        for v in variables:
            total_refs += 3  # reading + lower + upper
            if v.target_tag_id is not None:
                total_refs += 1
        assert total_refs == 73

    def test_no_online_tags(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment
        from app.models.pi_tag import PiTag

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        variables = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).all()
        all_tag_ids = set()
        for v in variables:
            all_tag_ids.add(v.reading_tag_id)
            all_tag_ids.add(v.lower_limit_tag_id)
            all_tag_ids.add(v.upper_limit_tag_id)
            if v.target_tag_id:
                all_tag_ids.add(v.target_tag_id)
        tags = db_session.query(PiTag).filter(PiTag.id.in_(all_tag_ids)).all()
        for tag in tags:
            assert "_ONLINE" not in tag.pi_tag_name

    def test_no_rb2_rb4_references(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment
        from app.models.pi_tag import PiTag

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        variables = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).all()
        all_tag_ids = set()
        for v in variables:
            all_tag_ids.add(v.reading_tag_id)
            all_tag_ids.add(v.lower_limit_tag_id)
            all_tag_ids.add(v.upper_limit_tag_id)
            if v.target_tag_id:
                all_tag_ids.add(v.target_tag_id)
        tags = db_session.query(PiTag).filter(PiTag.id.in_(all_tag_ids)).all()
        for tag in tags:
            assert "RB2" not in tag.pi_tag_name
            assert "RB4" not in tag.pi_tag_name

    def test_second_run_no_duplicates(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        count = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).count()
        assert count == 24

    def test_excluded_variables_absent(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        variables = db_session.query(CepVariable).filter(CepVariable.equipment_id == eq.id).all()
        names = {v.name for v in variables}
        excluded = {
            "Concentracao de sulfato de sodio", "Condutividade", "pH",
            "Ferro da Decapagem Quimica", "HF", "HNO3",
            "Emissividade", "Pirometro 02", "Pulverizacao", "Vazao",
            "Produtividade", "TV", "Alongamento", "Carga do laminador",
        }
        assert names.isdisjoint(excluded)

    def test_conflict_does_not_overwrite_silently(self, db_session: Session):
        seed = _load_seed_module()
        from app.models.cep_variable import CepVariable
        from app.models.equipment import Equipment

        seed.run_seed()
        eq = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
        var = db_session.query(CepVariable).filter(
            CepVariable.equipment_id == eq.id, CepVariable.code == "ESC_01"
        ).one()
        original_name = var.name
        var.name = "MODIFIED"
        db_session.commit()

        # Re-run seed — should update back to original
        result = seed.run_seed()
        db_session.expire_all()
        var_updated = db_session.query(CepVariable).filter(
            CepVariable.equipment_id == eq.id, CepVariable.code == "ESC_01"
        ).one()
        assert var_updated.name == original_name
        assert result["cep_variables"]["updated"] == 24
