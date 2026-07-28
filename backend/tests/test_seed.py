"""Seed script tests."""
import importlib.util
from pathlib import Path

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_module", SCRIPTS / "seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_is_idempotent(db_session: Session) -> None:
    seed = _load_seed_module()
    first = seed.run_seed()
    assert first["equipments"]["created"] == 1
    assert first["sections"]["created"] == 4
    assert first["variable_types"]["created"] == 6

    second = seed.run_seed()
    assert second["equipments"]["created"] == 0
    assert second["sections"]["created"] == 0
    assert second["variable_types"]["created"] == 0
    assert second["equipments"]["updated"] == 1
    assert second["sections"]["updated"] == 4
    assert second["variable_types"]["updated"] == 6

    from app.models.equipment import Equipment
    from app.models.section import Section
    from app.models.variable_type import VariableType

    assert db_session.query(Equipment).count() == 1
    assert db_session.query(Section).count() == 4
    assert db_session.query(VariableType).count() == 6
