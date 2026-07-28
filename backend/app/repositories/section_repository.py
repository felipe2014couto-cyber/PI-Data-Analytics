"""Section repository."""
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.section import Section


class SectionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, section_id: int) -> Optional[Section]:
        return self.db.get(Section, section_id)

    def get_by_code(self, equipment_id: int, code: str) -> Optional[Section]:
        stmt = select(Section).where(
            Section.equipment_id == equipment_id,
            Section.code == code,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        search: Optional[str] = None,
        equipment_id: Optional[int] = None,
        active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[Sequence[Section], int]:
        stmt = select(Section)
        count_stmt = select(func.count()).select_from(Section)

        conditions = []
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(or_(Section.code.ilike(pattern), Section.name.ilike(pattern)))
        if equipment_id is not None:
            conditions.append(Section.equipment_id == equipment_id)
        if active is not None:
            conditions.append(Section.active == active)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int(self.db.execute(count_stmt).scalar_one() or 0)
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Section.equipment_id.asc(), Section.code.asc()).offset(offset).limit(page_size)
        items: List[Section] = list(self.db.execute(stmt).scalars().all())
        return items, total

    def add(self, section: Section) -> Section:
        self.db.add(section)
        self.db.flush()
        return section

    def delete(self, section: Section) -> None:
        self.db.delete(section)
        self.db.flush()

    def count_tags(self, section_id: int) -> int:
        from app.models.pi_tag import PiTag

        stmt = select(func.count()).select_from(PiTag).where(PiTag.section_id == section_id)
        return int(self.db.execute(stmt).scalar_one() or 0)
