"""PiTag repository."""
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.pi_tag import PiTag, PiTagValidationStatus


class PiTagRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, pi_tag_id: int) -> Optional[PiTag]:
        return self.db.get(PiTag, pi_tag_id)

    def get_by_server_and_name(
        self,
        pi_server: str,
        pi_tag_name: str,
        exclude_id: Optional[int] = None,
    ) -> Optional[PiTag]:
        stmt = select(PiTag).where(
            PiTag.pi_server == pi_server,
            PiTag.pi_tag_name == pi_tag_name,
        )
        if exclude_id is not None:
            stmt = stmt.where(PiTag.id != exclude_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        search: Optional[str] = None,
        equipment_id: Optional[int] = None,
        section_id: Optional[int] = None,
        variable_type_id: Optional[int] = None,
        active: Optional[bool] = None,
        validation_status: Optional[PiTagValidationStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[Sequence[PiTag], int]:
        stmt = select(PiTag)
        count_stmt = select(func.count()).select_from(PiTag)

        conditions = []
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(
                    PiTag.pi_tag_name.ilike(pattern),
                    PiTag.display_name.ilike(pattern),
                    PiTag.pi_server.ilike(pattern),
                )
            )
        if equipment_id is not None:
            conditions.append(PiTag.equipment_id == equipment_id)
        if section_id is not None:
            conditions.append(PiTag.section_id == section_id)
        if variable_type_id is not None:
            conditions.append(PiTag.variable_type_id == variable_type_id)
        if active is not None:
            conditions.append(PiTag.active == active)
        if validation_status is not None:
            conditions.append(PiTag.validation_status == validation_status)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int(self.db.execute(count_stmt).scalar_one() or 0)
        offset = (page - 1) * page_size
        stmt = stmt.order_by(PiTag.pi_server.asc(), PiTag.pi_tag_name.asc()).offset(offset).limit(page_size)
        items: List[PiTag] = list(self.db.execute(stmt).scalars().all())
        return items, total

    def add(self, pi_tag: PiTag) -> PiTag:
        self.db.add(pi_tag)
        self.db.flush()
        return pi_tag

    def delete(self, pi_tag: PiTag) -> None:
        self.db.delete(pi_tag)
        self.db.flush()
