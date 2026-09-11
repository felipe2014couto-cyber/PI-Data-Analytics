"""Idempotent catalog reconciliation for CEP auxiliary PI points."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.integrations.pi.errors import PiIntegrationError
from app.integrations.pi.provider import PiDataProvider
from app.models.cep_variable import CepVariable
from app.models.cep_variable_tag_dependency import CepVariableTagDependency
from app.models.pi_tag import PiTag, PiTagKind, PiTagValidationStatus


@dataclass(frozen=True)
class DependencyReference:
    variable_id: int
    dependency_type: str
    pi_server: str
    pi_tag_name: str
    owner_tag_id: int


class CepDependencyService:
    """Resolve and persist dependencies without fetching historical values."""

    @staticmethod
    def references_for(variable: CepVariable) -> list[DependencyReference]:
        owner = variable.reading_tag
        if owner is None:
            raise ValidationError("Variável CEP sem tag principal.", details={"variable_id": variable.id})
        refs: list[DependencyReference] = []
        grouped = (
            ("LOWER_LIMIT", owner.lower_limit_tag),
            ("UPPER_LIMIT", owner.upper_limit_tag),
        )
        for dependency_type, name in grouped:
            if name and name.strip():
                refs.append(DependencyReference(variable.id, dependency_type, owner.pi_server, name.strip(), owner.id))
        explicit = (
            ("LOWER_LIMIT", variable.lower_limit_tag),
            ("UPPER_LIMIT", variable.upper_limit_tag),
            ("TARGET", variable.target_tag),
        )
        grouped_types = {item.dependency_type for item in refs}
        for dependency_type, tag in explicit:
            if tag is None or tag.id == owner.id or dependency_type in grouped_types:
                continue
            refs.append(DependencyReference(variable.id, dependency_type, tag.pi_server, tag.pi_tag_name, owner.id))
        unique: dict[tuple[str, str, str], DependencyReference] = {}
        for ref in refs:
            unique[(ref.dependency_type, ref.pi_server, ref.pi_tag_name)] = ref
        return list(unique.values())

    @staticmethod
    def _path(ref: DependencyReference) -> str:
        return f"\\\\{ref.pi_server}\\{ref.pi_tag_name}"

    async def reconcile(
        self,
        provider: PiDataProvider,
        variables: Iterable[CepVariable] | None = None,
    ) -> dict[str, int]:
        rows = list(variables) if variables is not None else list(
            self.db.scalars(select(CepVariable).where(CepVariable.active.is_(True)).order_by(CepVariable.id)).all()
        )
        desired: dict[tuple[int, str], DependencyReference] = {}
        for variable in rows:
            for ref in self.references_for(variable):
                desired[(ref.variable_id, ref.dependency_type)] = ref

        resolved = invalid = created = relationships = 0
        for key, ref in desired.items():
            error_message = None
            relation = self.db.scalar(select(CepVariableTagDependency).where(
                CepVariableTagDependency.variable_id == ref.variable_id,
                CepVariableTagDependency.dependency_type == ref.dependency_type,
            ))
            tag = self.db.scalar(select(PiTag).where(
                PiTag.pi_server == ref.pi_server,
                PiTag.pi_tag_name == ref.pi_tag_name,
            ))
            point = None
            if tag is not None and tag.pi_web_id:
                web_id = tag.pi_web_id
            else:
                try:
                    point = await provider.resolve_point(self._path(ref))
                except PiIntegrationError as exc:
                    point = None
                    error_message = exc.safe_message
                else:
                    error_message = None
                web_id = point.web_id if point is not None else None

            if tag is None and web_id:
                tag = self.db.scalar(select(PiTag).where(PiTag.pi_web_id == web_id))
            owner = self.db.get(PiTag, ref.owner_tag_id)
            if web_id:
                if tag is None:
                    if owner is None:
                        raise ValidationError("Tag principal não encontrada.", details={"tag_id": ref.owner_tag_id})
                    tag = PiTag(
                        equipment_id=owner.equipment_id,
                        section_id=owner.section_id,
                        variable_type_id=owner.variable_type_id,
                        pi_server=ref.pi_server,
                        pi_tag_name=ref.pi_tag_name,
                        pi_web_id=web_id,
                        display_name=ref.pi_tag_name,
                        data_type=owner.data_type,
                        active=True,
                        tag_kind=PiTagKind.DEPENDENCY,
                        validation_status=PiTagValidationStatus.VALID,
                        validation_message="Dependência CEP resolvida pelo PI WebId.",
                    )
                    self.db.add(tag)
                    self.db.flush()
                    created += 1
                elif tag.tag_kind != PiTagKind.PRIMARY:
                    tag.tag_kind = PiTagKind.DEPENDENCY
                tag.pi_web_id = web_id
                tag.validation_status = PiTagValidationStatus.VALID
                tag.validation_message = "Dependência CEP resolvida pelo PI WebId."
                tag.active = True
                resolved += 1
                status = "RESOLVED"
                error_message = None
            else:
                invalid += 1
                status = "INVALID"
                error_message = locals().get("error_message") or "Ponto PI auxiliar não encontrado."

            if relation is None:
                relation = CepVariableTagDependency(variable_id=ref.variable_id, dependency_type=ref.dependency_type)
                self.db.add(relation)
                relationships += 1
            relation.tag_id = tag.id if tag is not None and web_id else None
            relation.source_reference = ref.pi_tag_name
            relation.pi_web_id = web_id
            relation.status = status
            relation.error_message = error_message

        variable_ids = {variable.id for variable in rows}
        if variable_ids:
            existing = list(self.db.scalars(select(CepVariableTagDependency).where(CepVariableTagDependency.variable_id.in_(variable_ids))).all())
            for relation in existing:
                if (relation.variable_id, relation.dependency_type) not in desired:
                    self.db.delete(relation)
        self.db.commit()
        return {"variables": len(rows), "dependencies": len(desired), "resolved": resolved, "invalid": invalid, "created": created, "relationships_created": relationships}

    def __init__(self, db: Session) -> None:
        self.db = db
