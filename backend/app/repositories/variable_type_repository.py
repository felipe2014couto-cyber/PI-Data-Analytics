"""VariableType repository."""
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.variable_type import VariableType


class VariableTypeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, variable_type_id: int) -> Optional[VariableType]:
        return self.db.get(VariableType, variable_type_id)

    def get_by_code(self, code: str) -> Optional[VariableType]:
        stmt = select(VariableType).where(VariableType.code == code)
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        search: Optional[str] = None,
        active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[Sequence[VariableType], int]:
        stmt = select(VariableType)
        count_stmt = select(func.count()).select_from(VariableType)

        conditions = []
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(or_(VariableType.code.ilike(pattern), VariableType.name.ilike(pattern)))
        if active is not None:
            conditions.append(VariableType.active == active)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int(self.db.execute(count_stmt).scalar_one() or 0)
        offset = (page - 1) * page_size
        stmt = stmt.order_by(VariableType.code.asc()).offset(offset).limit(page_size)
        items: List[VariableType] = list(self.db.execute(stmt).scalars().all())
        return items, total

    def add(self, variable_type: VariableType) -> VariableType:
        self.db.add(variable_type)
        self.db.flush()
        return variable_type

    def delete(self, variable_type: VariableType) -> None:
        self.db.delete(variable_type)
        self.db.flush()

    def count_tags(self, variable_type_id: int) -> int:
        from app.models.pi_tag import PiTag

        stmt = select(func.count()).select_from(PiTag).where(PiTag.variable_type_id == variable_type_id)
        return int(self.db.execute(stmt).scalar_one() or 0)
