"""Section business rules."""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DependencyExistsError,
    DuplicateCodeError,
    InvalidEquipmentError,
    NotFoundError,
)
from app.models.section import Section
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
        )
        self.repo.add(section)
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
