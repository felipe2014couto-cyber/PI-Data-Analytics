"""Classification tag repository."""
from typing import List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.classification_tag import ClassificationTag, SectionClassificationTag


class ClassificationTagRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, tag_id: int) -> Optional[ClassificationTag]:
        return self.db.get(ClassificationTag, tag_id)

    def get_by_name(self, name: str) -> Optional[ClassificationTag]:
        stmt = select(ClassificationTag).where(ClassificationTag.name == name)
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, search: Optional[str] = None) -> Sequence[ClassificationTag]:
        stmt = select(ClassificationTag)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(ClassificationTag.name.ilike(pattern))
        stmt = stmt.order_by(ClassificationTag.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, name: str) -> ClassificationTag:
        tag = ClassificationTag(name=name)
        self.db.add(tag)
        self.db.flush()
        return tag

    def set_section_tags(self, section_id: int, tag_ids: Sequence[int]) -> None:
        stmt = select(SectionClassificationTag).where(
            SectionClassificationTag.section_id == section_id,
        )
        for assoc in self.db.execute(stmt).scalars().all():
            self.db.delete(assoc)
        self.db.flush()
        for tag_id in tag_ids:
            self.db.add(SectionClassificationTag(section_id=section_id, classification_tag_id=tag_id))
        self.db.flush()

    def section_tag_ids(self, section_id: int) -> List[int]:
        stmt = select(SectionClassificationTag.classification_tag_id).where(
            SectionClassificationTag.section_id == section_id,
        ).order_by(SectionClassificationTag.classification_tag_id.asc())
        return [int(row) for row in self.db.execute(stmt).scalars().all()]

    def count_section_usages(self, tag_id: int) -> int:
        stmt = select(func.count()).select_from(SectionClassificationTag).where(
            SectionClassificationTag.classification_tag_id == tag_id,
        )
        return int(self.db.execute(stmt).scalar_one() or 0)