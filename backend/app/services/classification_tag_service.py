"""Classification tag business rules."""
from typing import Sequence

from sqlalchemy.orm import Session

from app.core.exceptions import DependencyExistsError, DuplicateCodeError, InvalidSectionError, NotFoundError
from app.models.classification_tag import ClassificationTag
from app.repositories.classification_tag_repository import ClassificationTagRepository


class ClassificationTagService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ClassificationTagRepository(db)

    def list(self, search: str | None = None) -> Sequence[ClassificationTag]:
        return self.repo.list(search=search)

    def get(self, tag_id: int) -> ClassificationTag:
        tag = self.repo.get(tag_id)
        if tag is None:
            raise NotFoundError(
                "Tag de classificacao nao encontrada.",
                details={"classification_tag_id": tag_id},
            )
        return tag

    def create(self, name: str) -> ClassificationTag:
        existing = self.repo.get_by_name(name)
        if existing is not None:
            raise DuplicateCodeError(
                "Ja existe uma tag de classificacao com este nome.",
                details={"name": name},
            )
        tag = self.repo.create(name)
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def delete(self, tag_id: int) -> None:
        tag = self.get(tag_id)
        usages = self.repo.count_section_usages(tag_id)
        if usages > 0:
            raise DependencyExistsError(
                "Nao e possivel excluir a tag de classificacao pois existem secoes vinculadas.",
                details={"classification_tag_id": tag_id, "sections": usages},
            )
        self.db.delete(tag)
        self.db.commit()

    def set_section_tags(self, section_id: int, tag_ids: Sequence[int]) -> None:
        tag_ids = list(dict.fromkeys(tag_ids))
        for tag_id in tag_ids:
            if self.repo.get(tag_id) is None:
                raise InvalidSectionError(
                    "A tag de classificacao informada nao existe.",
                    details={"classification_tag_id": tag_id},
                )
        self.repo.set_section_tags(section_id, tag_ids)
