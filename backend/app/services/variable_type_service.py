"""VariableType business rules."""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DependencyExistsError,
    DuplicateCodeError,
    NotFoundError,
)
from app.models.variable_type import VariableType
from app.repositories.variable_type_repository import VariableTypeRepository
from app.schemas.variable_type import VariableTypeCreate, VariableTypeUpdate


class VariableTypeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = VariableTypeRepository(db)

    def get(self, variable_type_id: int) -> VariableType:
        item = self.repo.get(variable_type_id)
        if item is None:
            raise NotFoundError(
                "Tipo de variavel nao encontrado.",
                details={"variable_type_id": variable_type_id},
            )
        return item

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

    def create(self, payload: VariableTypeCreate) -> VariableType:
        existing = self.repo.get_by_code(payload.code)
        if existing is not None:
            raise DuplicateCodeError(
                "Ja existe um tipo de variavel com este codigo.",
                details={"code": payload.code},
            )
        item = VariableType(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            default_unit=payload.default_unit,
            active=payload.active,
        )
        self.repo.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def update(self, variable_type_id: int, payload: VariableTypeUpdate) -> VariableType:
        item = self.get(variable_type_id)
        if payload.code is not None and payload.code != item.code:
            existing = self.repo.get_by_code(payload.code)
            if existing is not None and existing.id != item.id:
                raise DuplicateCodeError(
                    "Ja existe um tipo de variavel com este codigo.",
                    details={"code": payload.code},
                )
            item.code = payload.code
        if payload.name is not None:
            item.name = payload.name
        if payload.description is not None:
            item.description = payload.description
        if payload.default_unit is not None:
            item.default_unit = payload.default_unit
        if payload.active is not None:
            item.active = payload.active
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, variable_type_id: int) -> None:
        item = self.get(variable_type_id)
        tags_count = self.repo.count_tags(variable_type_id)
        if tags_count > 0:
            raise DependencyExistsError(
                "Nao e possivel excluir o tipo de variavel pois existem tags relacionadas. "
                "Utilize a desativacao logica.",
                details={"variable_type_id": variable_type_id, "pi_tags": tags_count},
            )
        self.repo.delete(item)
        self.db.commit()
