"""Section business rules."""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DependencyExistsError,
    DuplicateCodeError,
    InvalidEquipmentError,
    InvalidSectionError,
    NotFoundError,
)
from app.models.section import Section
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.variable_type import VariableType
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.section_repository import SectionRepository
from app.schemas.section import SectionCreate, SectionUpdate


class SectionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SectionRepository(db)
        self.equipment_repo = EquipmentRepository(db)

    def get(self, section_id: int) -> Section:
        section = self.repo.get(section_id)
        if section is None:
            raise NotFoundError(
                "Secao nao encontrada.",
                details={"section_id": section_id},
            )
        return section

    def list(
        self,
        search: Optional[str],
        equipment_id: Optional[int],
        active: Optional[bool],
        page: int,
        page_size: int,
    ):
        return self.repo.list(
            search=search,
            equipment_id=equipment_id,
            active=active,
            page=page,
            page_size=page_size,
        )

    def _ensure_equipment(self, equipment_id: int) -> None:
        equipment = self.equipment_repo.get(equipment_id)
        if equipment is None:
            raise InvalidEquipmentError(
                "Equipamento informado nao existe.",
                details={"equipment_id": equipment_id},
            )

    def _validate_analysis_tags(
        self,
        equipment_id: int,
        section_id: int | None,
        width_tag_id: int | None,
        um_tag_id: int | None,
        thickness_tag_id: int | None,
    ) -> None:
        selected = {
            "width_tag_id": width_tag_id,
            "um_tag_id": um_tag_id,
            "thickness_tag_id": thickness_tag_id,
        }
        tag_ids = [tag_id for tag_id in selected.values() if tag_id is not None]
        if len(tag_ids) != len(set(tag_ids)):
            raise InvalidSectionError(
                "As tags de largura, UM e espessura devem ser diferentes.",
                details={"tag_ids": tag_ids},
            )
        for field, tag_id in selected.items():
            if tag_id is None:
                continue
            tag = self.db.get(PiTag, tag_id)
            if tag is None:
                raise InvalidSectionError(
                    "A tag informada nao existe.",
                    details={"field": field, "tag_id": tag_id},
                )
            if tag.equipment_id != equipment_id or (
                section_id is not None and tag.section_id not in (None, section_id)
            ):
                raise InvalidSectionError(
                    "A tag selecionada deve pertencer ao equipamento e a secao, ou ser global do equipamento.",
                    details={"field": field, "tag_id": tag_id, "section_id": section_id},
                )
            if field in {"width_tag_id", "thickness_tag_id"} and tag.data_type != PiTagDataType.NUMERIC:
                raise InvalidSectionError(
                    "As tags de largura e espessura devem ser numericas.",
                    details={"field": field, "tag_id": tag_id},
                )
            variable_type = self.db.get(VariableType, tag.variable_type_id)
            type_labels = {
                (variable_type.code if variable_type else "").strip().upper(),
                (variable_type.name if variable_type else "").strip().upper(),
            }
            expected_types = {
                "width_tag_id": {"LARGURA", "WIDTH"},
                "um_tag_id": {"UM", "CODIGO UM", "UNIDADE MATERIAL"},
                "thickness_tag_id": {"ESPESSURA", "THICKNESS"},
            }
            if not type_labels.intersection(expected_types[field]):
                raise InvalidSectionError(
                    "A tag selecionada nao corresponde ao tipo de variavel esperado.",
                    details={"field": field, "tag_id": tag_id, "expected": sorted(expected_types[field])},
                )

    def create(self, payload: SectionCreate) -> Section:
        self._ensure_equipment(payload.equipment_id)
        existing = self.repo.get_by_code(payload.equipment_id, payload.code)
        if existing is not None:
            raise DuplicateCodeError(
                "Ja existe uma secao com este codigo neste equipamento.",
                details={"equipment_id": payload.equipment_id, "code": payload.code},
            )
        section = Section(
            equipment_id=payload.equipment_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            active=payload.active,
            width_tag_id=payload.width_tag_id,
            um_tag_id=payload.um_tag_id,
            thickness_tag_id=payload.thickness_tag_id,
        )
        self.repo.add(section)
        self._validate_analysis_tags(
            equipment_id=section.equipment_id,
            section_id=section.id,
            width_tag_id=section.width_tag_id,
            um_tag_id=section.um_tag_id,
            thickness_tag_id=section.thickness_tag_id,
        )
        self.db.commit()
        self.db.refresh(section)
        return section

    def update(self, section_id: int, payload: SectionUpdate) -> Section:
        section = self.get(section_id)
        target_equipment_id = payload.equipment_id or section.equipment_id
        if payload.equipment_id is not None and payload.equipment_id != section.equipment_id:
            self._ensure_equipment(payload.equipment_id)
            section.equipment_id = payload.equipment_id
        if payload.code is not None and payload.code != section.code:
            existing = self.repo.get_by_code(target_equipment_id, payload.code)
            if existing is not None and existing.id != section.id:
                raise DuplicateCodeError(
                    "Ja existe uma secao com este codigo neste equipamento.",
                    details={"equipment_id": target_equipment_id, "code": payload.code},
                )
            section.code = payload.code
        if payload.name is not None:
            section.name = payload.name
        if payload.description is not None:
            section.description = payload.description
        if payload.active is not None:
            section.active = payload.active
        self._validate_analysis_tags(
            equipment_id=target_equipment_id,
            section_id=section.id,
            width_tag_id=payload.width_tag_id if "width_tag_id" in payload.model_fields_set else section.width_tag_id,
            um_tag_id=payload.um_tag_id if "um_tag_id" in payload.model_fields_set else section.um_tag_id,
            thickness_tag_id=payload.thickness_tag_id if "thickness_tag_id" in payload.model_fields_set else section.thickness_tag_id,
        )
        if "width_tag_id" in payload.model_fields_set:
            section.width_tag_id = payload.width_tag_id
        if "um_tag_id" in payload.model_fields_set:
            section.um_tag_id = payload.um_tag_id
        if "thickness_tag_id" in payload.model_fields_set:
            section.thickness_tag_id = payload.thickness_tag_id
        self.db.commit()
        self.db.refresh(section)
        return section

    def delete(self, section_id: int) -> None:
        section = self.get(section_id)
        tags_count = self.repo.count_tags(section_id)
        if tags_count > 0:
            raise DependencyExistsError(
                "Nao e possivel excluir a secao pois existem tags relacionadas. "
                "Utilize a desativacao logica.",
                details={"section_id": section_id, "pi_tags": tags_count},
            )
        self.repo.delete(section)
        self.db.commit()
