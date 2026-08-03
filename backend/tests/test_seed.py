"""Seed script tests."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
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
    assert first["equipments"]["created"] == 2
    assert first["sections"]["created"] == 7
    assert first["variable_types"]["created"] == 8
    assert first["pi_tags"]["created"] == 73

    second = seed.run_seed()
    assert second["equipments"]["created"] == 0
    assert second["sections"]["created"] == 0
    assert second["variable_types"]["created"] == 0
    assert second["pi_tags"]["created"] == 0
    assert second["equipments"]["updated"] == 2
    assert second["sections"]["updated"] == 7
    assert second["variable_types"]["updated"] == 8
    assert second["pi_tags"]["updated"] == 73

    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag
    from app.models.section import Section
    from app.models.variable_type import VariableType

    assert db_session.query(Equipment).count() == 2
    assert db_session.query(Section).count() == 7
    assert db_session.query(VariableType).count() == 8
    assert db_session.query(PiTag).count() == 73


def test_rb1_equipment_exists(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    assert rb1.name == "Equipamento RB1"
    assert rb1.active is True


def test_rb1_sections_exist(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.section import Section

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    sections = (
        db_session.query(Section)
        .filter(Section.equipment_id == rb1.id)
        .all()
    )
    codes = {s.code for s in sections}
    assert codes == {"DECAPAGEM_ELETROLITICA", "DECAPAGEM_QUIMICA", "FORNO"}
    for s in sections:
        assert s.equipment_id == rb1.id


def test_rb1_variable_types_reuse_and_create(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.variable_type import VariableType

    vt = db_session.query(VariableType).all()
    codes = {v.code for v in vt}
    assert "TEMPERATURE" in codes
    assert "CURRENT" in codes
    assert "SPEED" in codes
    assert "IRON_CONTENT" in codes
    assert "OXYGEN" in codes
    assert "PRESSURE" in codes


def test_rb1_pi_tag_count_by_section(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag
    from app.models.section import Section

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    sections = {
        s.code: s.id
        for s in db_session.query(Section).filter(Section.equipment_id == rb1.id).all()
    }

    de_id = sections["DECAPAGEM_ELETROLITICA"]
    dq_id = sections["DECAPAGEM_QUIMICA"]
    fr_id = sections["FORNO"]

    manifest_by_section = {}
    for t in seed._RB1_TAGS:
        manifest_by_section.setdefault(t["section"], []).append(t)

    assert db_session.query(PiTag).filter(PiTag.section_id == de_id).count() == len(manifest_by_section["DECAPAGEM_ELETROLITICA"])
    assert db_session.query(PiTag).filter(PiTag.section_id == dq_id).count() == len(manifest_by_section["DECAPAGEM_QUIMICA"])
    assert db_session.query(PiTag).filter(PiTag.section_id == fr_id).count() >= len(manifest_by_section["FORNO"])


def test_rb1_pi_tags_are_pending(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag, PiTagValidationStatus

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    manifest_tags = {t["tag"] for t in seed._RB1_TAGS}
    tags = (
        db_session.query(PiTag)
        .filter(PiTag.equipment_id == rb1.id, PiTag.pi_tag_name.in_(manifest_tags))
        .all()
    )
    assert len(tags) == 73
    for tag in tags:
        assert tag.validation_status == PiTagValidationStatus.PENDING
        assert tag.pi_web_id is None
        assert tag.pi_server == "PIMS"


def test_rb1_no_online_tags(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    for tag in tags:
        assert "_ONLINE" not in tag.pi_tag_name


def test_rb1_no_rb2_rb4_references(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    for tag in tags:
        assert "RB2" not in tag.pi_tag_name
        assert "RB4" not in tag.pi_tag_name


def test_rb1_excluded_variables_absent(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    display_names = {t.display_name for t in tags}
    excluded = {
        "Concentracao de sulfato de sodio", "Condutividade", "pH",
        "Ferro da Decapagem Quimica", "HF", "HNO3",
        "Emissividade", "Pirometro 02", "Pulverizacao", "Vazao",
        "Produtividade", "TV", "Alongamento", "Carga do laminador",
    }
    assert display_names.isdisjoint(excluded)


def test_rb1_velocity_target_tag_exists(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    target = (
        db_session.query(PiTag)
        .filter(
            PiTag.equipment_id == rb1.id,
            PiTag.pi_tag_name == "LFI_RB1_FRN_VELOCIDADE_LIM_OBJ",
        )
        .one_or_none()
    )
    assert target is not None
    assert target.description == "Valor objetivo"


def test_rb1_second_run_no_duplicates(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    manifest_tags = {t["tag"] for t in seed._RB1_TAGS}
    count = (
        db_session.query(PiTag)
        .filter(PiTag.equipment_id == rb1.id, PiTag.pi_tag_name.in_(manifest_tags))
        .count()
    )
    assert count == 73


def test_rb1_tag_names_match_xml(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    tag_names = {t.pi_tag_name for t in tags}

    expected_tags = {
        "LFI_RB1_COR_ESC1", "LFI_RB1_COR_ESC2", "LFI_RB1_COR_ESC3", "LFI_RB1_COR_ESC4",
        "LFI_RB1_COR_RETF1", "LFI_RB1_COR_RETF2", "LFI_RB1_COR_RETF3", "LFI_RB1_COR_RETF4",
        "LFI_RB1_TPR_TANQ1", "LFI_RB1_TPR_TANQ2", "LFI_RB1_DE_TF_REAL",
        "LFI_RB1_TPR_BAN",
        "LFI_RB1_PERC_OXIG_REAL", "LFI_RB1_PCI_MISTURA_REAL",
        "LFI_RB1_TEMP_PRMT1", "LFI_RB1_VEL_PROC_PV",
        "LFI_RB1_TIC1_PV", "LFI_RB1_TIC2_PV", "LFI_RB1_TIC3_PV", "LFI_RB1_TIC4_PV",
        "LFI_RB1_TIC5_PV", "LFI_RB1_TIC6_PV", "LFI_RB1_TIC7_PV", "LFI_RB1_TIC8_PV",
    }
    assert tag_names >= expected_tags

    for tag in tags:
        assert tag.pi_tag_name.startswith("LFI_RB1_")


def test_rb1_manifest_24_variables(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    read_tags = [t for t in tags if t.description == "Leitura"]
    assert len(read_tags) == 24


def test_rb1_manifest_73_references(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    assert len(tags) == 73
    read_count = sum(1 for t in tags if t.description == "Leitura")
    lim_inf_count = sum(1 for t in tags if t.description == "Limite inferior")
    lim_sup_count = sum(1 for t in tags if t.description == "Limite superior")
    target_count = sum(1 for t in tags if t.description == "Valor objetivo")
    assert read_count == 24
    assert lim_inf_count == 24
    assert lim_sup_count == 24
    assert target_count == 1


def test_rb1_correct_associations(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag
    from app.models.section import Section

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    sections = {
        s.code: s.id
        for s in db_session.query(Section).filter(Section.equipment_id == rb1.id).all()
    }
    tags = db_session.query(PiTag).filter(PiTag.equipment_id == rb1.id).all()
    for tag in tags:
        assert tag.equipment_id == rb1.id
        assert tag.section_id in sections.values()
        section = db_session.query(Section).filter(Section.id == tag.section_id).one()
        assert section.equipment_id == rb1.id
        assert tag.variable_type_id is not None


def test_rb1_no_silent_overwrite(db_session: Session) -> None:
    seed = _load_seed_module()
    seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    rb1 = db_session.query(Equipment).filter(Equipment.code == "RB1").one()
    original = (
        db_session.query(PiTag)
        .filter(PiTag.pi_tag_name == "LFI_RB1_COR_ESC1")
        .one()
    )
    original_id = original.id
    seed.run_seed()
    after = db_session.query(PiTag).filter(PiTag.id == original_id).one()
    assert after.id == original_id
    assert after.pi_tag_name == "LFI_RB1_COR_ESC1"


def test_seed_rollback_on_failure(db_session: Session) -> None:
    seed = _load_seed_module()
    call_count = [0]
    original_upsert_pi_tags = seed.upsert_pi_tags

    def failing_upsert_pi_tags(db):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Simulated failure during PI tag upsert")
        return original_upsert_pi_tags(db)

    seed.upsert_pi_tags = failing_upsert_pi_tags
    with pytest.raises(RuntimeError, match="Simulated failure"):
        seed.run_seed()
    from app.models.equipment import Equipment
    from app.models.pi_tag import PiTag

    assert db_session.query(PiTag).count() == 0
    assert db_session.query(Equipment).filter(Equipment.code == "RB1").count() == 0
    seed.upsert_pi_tags = original_upsert_pi_tags
