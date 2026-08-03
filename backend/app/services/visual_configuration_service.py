"""Ownership-safe visual configuration versioning."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import VisualConfiguration, VisualConfigurationVersion
from app.models.user import User
from app.schemas.visual_configuration import VisualConfigurationCreate


class VisualConfigurationService:
    def __init__(self, db: Session, user: User): self.db, self.user = db, user

    def _owned(self, config_id: str) -> VisualConfiguration:
        item = self.db.scalar(select(VisualConfiguration).where(VisualConfiguration.id == config_id, VisualConfiguration.owner_id == self.user.id))
        if not item: raise NotFoundError("Configuracao visual nao encontrada.")
        return item

    def _version(self, config_id: str, version: int) -> VisualConfigurationVersion:
        self._owned(config_id)
        item = self.db.scalar(select(VisualConfigurationVersion).where(VisualConfigurationVersion.configuration_id == config_id, VisualConfigurationVersion.version == version))
        if not item: raise NotFoundError("Versao visual nao encontrada.")
        return item

    def create(self, payload: VisualConfigurationCreate) -> VisualConfiguration:
        item = VisualConfiguration(owner_id=self.user.id, name=payload.name.strip(), description=payload.description, current_version=1)
        self.db.add(item); self.db.flush()
        self.db.add(VisualConfigurationVersion(configuration_id=item.id, version=1, snapshot=payload.document.model_dump(), created_by_user_id=self.user.id, operation="create"))
        try: self.db.commit()
        except Exception: self.db.rollback(); raise
        self.db.refresh(item); return item

    def list_all(self) -> list[VisualConfiguration]:
        return list(self.db.scalars(select(VisualConfiguration).where(VisualConfiguration.owner_id == self.user.id).order_by(VisualConfiguration.updated_at.desc(), VisualConfiguration.id)).all())

    def get(self, config_id: str) -> tuple[VisualConfiguration, VisualConfigurationVersion]:
        item = self._owned(config_id); return item, self._version(config_id, item.current_version)

    def history(self, config_id: str) -> list[VisualConfigurationVersion]:
        self._owned(config_id)
        return list(self.db.scalars(select(VisualConfigurationVersion).where(VisualConfigurationVersion.configuration_id == config_id).order_by(VisualConfigurationVersion.version.desc())).all())

    def get_version(self, config_id: str, version: int) -> VisualConfigurationVersion: return self._version(config_id, version)

    def _advance(self, item: VisualConfiguration, expected: int, snapshot: dict, operation: str, **values) -> VisualConfiguration:
        next_version = expected + 1
        result = self.db.execute(update(VisualConfiguration).where(VisualConfiguration.id == item.id, VisualConfiguration.owner_id == self.user.id, VisualConfiguration.current_version == expected).values(current_version=next_version, **values))
        if result.rowcount != 1: self.db.rollback(); raise ConflictError("A configuracao foi alterada em outra sessao.")
        self.db.add(VisualConfigurationVersion(configuration_id=item.id, version=next_version, snapshot=snapshot, created_by_user_id=self.user.id, operation=operation))
        try: self.db.commit()
        except Exception: self.db.rollback(); raise
        return self._owned(item.id)

    def update(self, config_id: str, expected: int, document: dict) -> VisualConfiguration:
        return self._advance(self._owned(config_id), expected, document, "update")

    def rename(self, config_id: str, expected: int, name: str) -> VisualConfiguration:
        item, current = self.get(config_id); return self._advance(item, expected, current.snapshot, "rename", name=name.strip())

    def restore(self, config_id: str, expected: int, version: int) -> VisualConfiguration:
        item = self._owned(config_id); source = self._version(config_id, version)
        return self._advance(item, expected, source.snapshot, "restore")

    def delete(self, config_id: str) -> None:
        item = self._owned(config_id)
        self.db.delete(item)
        self.db.commit()
