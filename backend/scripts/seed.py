"""Idempotent seed for PI Analytics Data."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.logging import configure_logging, logger  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models.equipment import Equipment
from app.models.section import Section
from app.models.variable_type import VariableType

EQUIPMENTS: List[dict] = [
    {
        "code": "RB3",
        "name": "Equipamento RB3",
        "description": "Equipamento de referencia cadastrado pelo seed.",
        "active": True,
    },
]

RB3_SECTIONS: List[dict] = [
    {"code": "ENTRADA", "name": "Entrada"},
    {"code": "FORNO", "name": "Forno"},
    {"code": "PROCESSO", "name": "Processo"},
    {"code": "SAIDA", "name": "Saida"},
]

VARIABLE_TYPES: List[dict] = [
    {
        "code": "TEMPERATURE",
        "name": "Temperatura",
        "description": "Medicao de temperatura.",
        "default_unit": "C",
    },
    {
        "code": "SPEED",
        "name": "Velocidade",
        "description": "Velocidade linear de processo.",
        "default_unit": "m/min",
    },
    {
        "code": "PRESSURE",
        "name": "Pressao",
        "description": "Pressao de processo.",
        "default_unit": "bar",
    },
    {
        "code": "FLOW",
        "name": "Vazao",
        "description": "Vazao de fluido ou gas.",
        "default_unit": None,
    },
    {
        "code": "CURRENT",
        "name": "Corrente",
        "description": "Corrente eletrica.",
        "default_unit": "A",
    },
    {
        "code": "TORQUE",
        "name": "Torque",
        "description": "Torque mecanico.",
        "default_unit": "%",
    },
]


def upsert_equipments(db: Session) -> Tuple[int, int]:
    created = 0
    updated = 0
    for data in EQUIPMENTS:
        existing = db.query(Equipment).filter(Equipment.code == data["code"]).one_or_none()
        if existing is None:
            db.add(Equipment(**data))
            created += 1
        else:
            existing.name = data["name"]
            existing.description = data["description"]
            existing.active = data["active"]
            updated += 1
    db.flush()
    return created, updated


def upsert_sections(db: Session) -> Tuple[int, int]:
    equipment = db.query(Equipment).filter(Equipment.code == "RB3").one()
    created = 0
    updated = 0
    for data in RB3_SECTIONS:
        existing = (
            db.query(Section)
            .filter(Section.equipment_id == equipment.id, Section.code == data["code"])
            .one_or_none()
        )
        if existing is None:
            db.add(Section(equipment_id=equipment.id, active=True, **data))
            created += 1
        else:
            existing.name = data["name"]
            updated += 1
    db.flush()
    return created, updated


def upsert_variable_types(db: Session) -> Tuple[int, int]:
    created = 0
    updated = 0
    for data in VARIABLE_TYPES:
        existing = (
            db.query(VariableType)
            .filter(VariableType.code == data["code"])
            .one_or_none()
        )
        if existing is None:
            db.add(VariableType(active=True, **data))
            created += 1
        else:
            existing.name = data["name"]
            existing.description = data["description"]
            existing.default_unit = data["default_unit"]
            existing.active = True
            updated += 1
    db.flush()
    return created, updated


def run_seed() -> dict:
    configure_logging()
    db = SessionLocal()
    try:
        equipment_stats = upsert_equipments(db)
        section_stats = upsert_sections(db)
        variable_type_stats = upsert_variable_types(db)
        db.commit()
        result = {
            "equipments": {"created": equipment_stats[0], "updated": equipment_stats[1]},
            "sections": {"created": section_stats[0], "updated": section_stats[1]},
            "variable_types": {"created": variable_type_stats[0], "updated": variable_type_stats[1]},
        }
        logger.info("Seed finished: %s", result)
        return result
    except Exception:
        db.rollback()
        logger.exception("Seed failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    summary = run_seed()
    print(summary)
