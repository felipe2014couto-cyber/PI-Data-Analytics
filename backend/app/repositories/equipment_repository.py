"""Equipment repository."""
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.equipment import Equipment


class EquipmentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, equipment_id: int) -> Optional[Equipment]:
        return self.db.get(Equipment, equipment_id)

    def get_by_code(self, code: str) -> Optional[Equipment]:
        stmt = select(Equipment).where(Equipment.code == code)
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        search: Optional[str] = None,
        active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[Sequence[Equipment], int]:
        stmt = select(Equipment)
        count_stmt = select(func.count()).select_from(Equipment)

        conditions = []
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(or_(Equipment.code.ilike(pattern), Equipment.name.ilike(pattern)))
        if active is not None:
            conditions.append(Equipment.active == active)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int(self.db.execute(count_stmt).scalar_one() or 0)
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Equipment.code.asc()).offset(offset).limit(page_size)
        items: List[Equipment] = list(self.db.execute(stmt).scalars().all())
        return items, total

    def add(self, equipment: Equipment) -> Equipment:
        self.db.add(equipment)
        self.db.flush()
        return equipment

    def delete(self, equipment: Equipment) -> None:
        self.db.delete(equipment)
        self.db.flush()

    def count_sections(self, equipment_id: int) -> int:
        from app.models.section import Section

        stmt = select(func.count()).select_from(Section).where(Section.equipment_id == equipment_id)
        return int(self.db.execute(stmt).scalar_one() or 0)

    def count_tags(self, equipment_id: int) -> int:
        from app.models.pi_tag import PiTag

        stmt = select(func.count()).select_from(PiTag).where(PiTag.equipment_id == equipment_id)
        return int(self.db.execute(stmt).scalar_one() or 0)
