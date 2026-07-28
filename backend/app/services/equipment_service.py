"""Equipment business rules."""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DependencyExistsError,
    DuplicateCodeError,
    NotFoundError,
)
from app.models.equipment import Equipment
from app.repositories.equipment_repository import EquipmentRepository
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate


class EquipmentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = EquipmentRepository(db)

    def get(self, equipment_id: int) -> Equipment:
        equipment = self.repo.get(equipment_id)
        if equipment is None:
            raise NotFoundError(
                "Equipamento nao encontrado.",
                details={"equipment_id": equipment_id},
            )
        return equipment

    def list(
        self,
        search: Optional[str],
        active: Optional[bool],
        page: int,
        page_size: int,
    ):
        return self.repo.list(
            search=search,
            active=active,
            page=page,
            page_size=page_size,
        )

    def create(self, payload: EquipmentCreate) -> Equipment:
        existing = self.repo.get_by_code(payload.code)
        if existing is not None:
            raise DuplicateCodeError(
                "Ja existe um equipamento com este codigo.",
                details={"code": payload.code},
            )
        equipment = Equipment(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            active=payload.active,
        )
        self.repo.add(equipment)
        self.db.commit()
        self.db.refresh(equipment)
        return equipment

    def update(self, equipment_id: int, payload: EquipmentUpdate) -> Equipment:
        equipment = self.get(equipment_id)
        if payload.code is not None and payload.code != equipment.code:
            existing = self.repo.get_by_code(payload.code)
            if existing is not None and existing.id != equipment.id:
                raise DuplicateCodeError(
                    "Ja existe um equipamento com este codigo.",
                    details={"code": payload.code},
                )
            equipment.code = payload.code
        if payload.name is not None:
            equipment.name = payload.name
        if payload.description is not None:
            equipment.description = payload.description
        if payload.active is not None:
            equipment.active = payload.active
        self.db.commit()
        self.db.refresh(equipment)
        return equipment

    def delete(self, equipment_id: int) -> None:
        equipment = self.get(equipment_id)
        sections_count = self.repo.count_sections(equipment_id)
        tags_count = self.repo.count_tags(equipment_id)
        if sections_count > 0 or tags_count > 0:
            raise DependencyExistsError(
                "Nao e possivel excluir o equipamento pois existem secoes ou tags relacionadas. "
                "Utilize a desativacao logica.",
                details={
                    "equipment_id": equipment_id,
                    "sections": sections_count,
                    "pi_tags": tags_count,
                },
            )
        self.repo.delete(equipment)
        self.db.commit()
