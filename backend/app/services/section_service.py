"""Section business rules."""
from typing import List, Optional
from unicodedata import combining, normalize

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DependencyExistsError,
    DuplicateCodeError,
    InvalidEquipmentError,
    InvalidSectionError,
    NotFoundError,
)
from app.models.section import Section
from app.models.section_analysis_tag import SectionAnalysisFilterType, SectionAnalysisTag
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.variable_type import VariableFilterDataType, VariableType
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.section_repository import SectionRepository
from app.schemas.section import SectionAnalysisTagItem, SectionCreate, SectionUpdate


class SectionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SectionRepository(db)
        self.equipment_repo = EquipmentRepository(db)

    def get(self, section_id: int) -> Section:
        section = self.repo.get(section_id)
        if section is None:
            raise NotFoundError(
                "Secao nao encontrada.",
                details={"section_id": section_id},
            )
        return section

    def list(
        self,
        search: Optional[str],
        equipment_id: Optional[int],
        active: Optional[bool],
        process_type: Optional[str] = None,
        group_code: Optional[str] = None,
        classification_tag_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ):
        return self.repo.list(
            search=search,
            equipment_id=equipment_id,
            active=active,
            process_type=process_type,
            group_code=group_code,
            classification_tag_id=classification_tag_id,
            page=page,
            page_size=page_size,
        )

    def _ensure_equipment(self, equipment_id: int) -> None:
        equipment = self.equipment_repo.get(equipment_id)
        if equipment is None:
            raise InvalidEquipmentError(
                "Equipamento informado nao existe.",
                details={"equipment_id": equipment_id},
            )

    def _validate_tag_scope(
        self,
        tag: PiTag,
        equipment_id: int,
        section_id: Optional[int],
        context_details: dict,
    ) -> None:
        if tag.equipment_id != equipment_id or (
            section_id is not None and tag.section_id not in (None, section_id)
        ):
            raise InvalidSectionError(
                "A tag selecionada deve pertencer ao equipamento e a secao, ou ser global do equipamento.",
                details={"tag_id": tag.id, "section_id": section_id, **context_details},
            )

    def _validate_analysis_tags(
        self,
        equipment_id: int,
        section_id: int | None,
        width_tag_id: int | None,
        um_tag_id: int | None,
        thickness_tag_id: int | None,
        steel_type_tag_id: int | None,
    ) -> None:
        selected = {
            "width_tag_id": width_tag_id,
            "um_tag_id": um_tag_id,
            "thickness_tag_id": thickness_tag_id,
            "steel_type_tag_id": steel_type_tag_id,
        }
        existing_fixed_ids = [width_tag_id, um_tag_id, thickness_tag_id]
        legacy_ids = [tag_id for tag_id in existing_fixed_ids if tag_id is not None]
        tag_ids = [tag_id for tag_id in selected.values() if tag_id is not None]
        if len(legacy_ids) != len(set(legacy_ids)):
            raise InvalidSectionError(
                "As tags de largura, UM e espessura devem ser diferentes.",
                details={"tag_ids": legacy_ids},
            )
        if steel_type_tag_id is not None and steel_type_tag_id in legacy_ids:
            raise InvalidSectionError(
                "A tag de tipo de aço deve ser diferente das demais tags fixas.",
                details={"tag_ids": tag_ids},
            )
        for field, tag_id in selected.items():
            if tag_id is None:
                continue
            tag = self.db.get(PiTag, tag_id)
            if tag is None:
                raise InvalidSectionError(
                    "A tag informada nao existe.",
                    details={"field": field, "tag_id": tag_id},
                )
            self._validate_tag_scope(
                tag=tag,
                equipment_id=equipment_id,
                section_id=section_id,
                context_details={"field": field},
            )
            if field in {"width_tag_id", "thickness_tag_id"} and tag.data_type != PiTagDataType.NUMERIC:
                raise InvalidSectionError(
                    "As tags de largura e espessura devem ser numericas.",
                    details={"field": field, "tag_id": tag_id},
                )
            variable_type = self.db.get(VariableType, tag.variable_type_id)
            type_labels = {
                (variable_type.code if variable_type else "").strip().upper(),
                (variable_type.name if variable_type else "").strip().upper(),
            }
            if field == "steel_type_tag_id":
                type_labels = {
                    "".join(char for char in normalize("NFD", label) if not combining(char))
                    .replace("_", " ").replace("-", " ")
                    for label in type_labels
                }
            expected_types = {
                "width_tag_id": {"LARGURA", "WIDTH"},
                "um_tag_id": {"UM", "CODIGO UM", "UNIDADE MATERIAL"},
                "thickness_tag_id": {"ESPESSURA", "THICKNESS"},
                "steel_type_tag_id": {"ACO", "TIPO DE ACO", "TIPO ACO", "TIPO_ACO", "STEEL TYPE", "STEEL_TYPE", "STEEL MODEL", "STEEL_MODEL", "MODELO DO ACO", "MODELO_DO_ACO", "MODELO ACO", "MODELO_ACO"},
            }
            if not type_labels.intersection(expected_types[field]):
                raise InvalidSectionError(
                    "A tag selecionada nao corresponde ao tipo de variavel esperado.",
                    details={"field": field, "tag_id": tag_id, "expected": sorted(expected_types[field])},
                )

    def _sync_dynamic_analysis_tags(
        self,
        section: Section,
        items: Optional[List[SectionAnalysisTagItem]],
        target_equipment_id: int,
    ) -> None:
        if items is None:
            return

        var_type_ids = [item.variable_type_id for item in items]
        if len(var_type_ids) != len(set(var_type_ids)):
            raise InvalidSectionError(
                "Cada tipo de variavel so pode ser associado uma vez por secao.",
                details={"variable_type_ids": var_type_ids},
            )

        for item in items:
            var_type = self.db.get(VariableType, item.variable_type_id)
            if var_type is None:
                raise InvalidSectionError(
                    "O tipo de variavel informado nao existe.",
                    details={"variable_type_id": item.variable_type_id},
                )

            tag = self.db.get(PiTag, item.pi_tag_id)
            if tag is None:
                raise InvalidSectionError(
                    "A tag informada nao existe.",
                    details={"pi_tag_id": item.pi_tag_id},
                )

            self._validate_tag_scope(
                tag=tag,
                equipment_id=target_equipment_id,
                section_id=section.id,
                context_details={"variable_type_id": item.variable_type_id},
            )

            if tag.variable_type_id != item.variable_type_id:
                raise InvalidSectionError(
                    "A tag selecionada nao pertence ao tipo de variavel escolhido.",
                    details={
                        "pi_tag_id": tag.id,
                        "tag_variable_type_id": tag.variable_type_id,
                        "expected_variable_type_id": item.variable_type_id,
                    },
                )

            if item.filter_type == SectionAnalysisFilterType.MIN_MAX:
                if tag.data_type != PiTagDataType.NUMERIC or var_type.filter_data_type != VariableFilterDataType.REAL:
                    raise InvalidSectionError(
                        "O filtro de valor mínimo / máximo (MIN_MAX) só é permitido para variáveis e tags numéricas.",
                        details={
                            "variable_type_id": item.variable_type_id,
                            "pi_tag_id": item.pi_tag_id,
                            "tag_data_type": tag.data_type,
                            "variable_filter_data_type": var_type.filter_data_type,
                        },
                    )

        current_by_var_type = {record.variable_type_id: record for record in section.analysis_tags}
        payload_by_var_type = {item.variable_type_id: item for item in items}

        for var_type_id, record in list(current_by_var_type.items()):
            if var_type_id not in payload_by_var_type:
                self.db.delete(record)

        for var_type_id, item in payload_by_var_type.items():
            if var_type_id in current_by_var_type:
                record = current_by_var_type[var_type_id]
                if record.pi_tag_id != item.pi_tag_id:
                    record.pi_tag_id = item.pi_tag_id
                if record.filter_type != item.filter_type:
                    record.filter_type = item.filter_type
            else:
                new_assoc = SectionAnalysisTag(
                    section_id=section.id,
                    variable_type_id=var_type_id,
                    pi_tag_id=item.pi_tag_id,
                    filter_type=item.filter_type,
                )
                self.db.add(new_assoc)

    def create(self, payload: SectionCreate) -> Section:
        self._ensure_equipment(payload.equipment_id)
        existing = self.repo.get_by_code(payload.equipment_id, payload.code)
        if existing is not None:
            raise DuplicateCodeError(
                "Ja existe uma secao com este codigo neste equipamento.",
                details={"equipment_id": payload.equipment_id, "code": payload.code},
            )
        section = Section(
            equipment_id=payload.equipment_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            active=payload.active,
            process_type=payload.process_type,
            group_code=payload.group_code,
            width_tag_id=payload.width_tag_id,
            um_tag_id=payload.um_tag_id,
            thickness_tag_id=payload.thickness_tag_id,
            steel_type_tag_id=payload.steel_type_tag_id,
        )
        self.repo.add(section)
        self._set_classification_tags(section.id, payload.classification_tag_ids)
        self._validate_analysis_tags(
            equipment_id=section.equipment_id,
            section_id=section.id,
            width_tag_id=section.width_tag_id,
            um_tag_id=section.um_tag_id,
            thickness_tag_id=section.thickness_tag_id,
            steel_type_tag_id=section.steel_type_tag_id,
        )
        if payload.analysis_tags is not None:
            self._sync_dynamic_analysis_tags(section, payload.analysis_tags, section.equipment_id)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise InvalidSectionError(
                "Violacao de integridade nas tags de analise da secao.",
                details={"error": str(exc.orig) if hasattr(exc, "orig") else str(exc)},
            )
        self.db.expire(section, ["classification_tags", "analysis_tags"])
        self.db.refresh(section)
        return section

    def _set_classification_tags(self, section_id: int, tag_ids: Optional[List[int]]) -> None:
        from app.services.classification_tag_service import ClassificationTagService

        if tag_ids is None:
            return
        ClassificationTagService(self.db).set_section_tags(section_id, tag_ids)

    def update(self, section_id: int, payload: SectionUpdate) -> Section:
        section = self.get(section_id)
        target_equipment_id = payload.equipment_id or section.equipment_id
        if payload.equipment_id is not None and payload.equipment_id != section.equipment_id:
            self._ensure_equipment(payload.equipment_id)
            section.equipment_id = payload.equipment_id
        if payload.code is not None and payload.code != section.code:
            existing = self.repo.get_by_code(target_equipment_id, payload.code)
            if existing is not None and existing.id != section.id:
                raise DuplicateCodeError(
                    "Ja existe uma secao com este codigo neste equipamento.",
                    details={"equipment_id": target_equipment_id, "code": payload.code},
                )
            section.code = payload.code
        if payload.name is not None:
            section.name = payload.name
        if payload.description is not None:
            section.description = payload.description
        if payload.active is not None:
            section.active = payload.active
        if "process_type" in payload.model_fields_set:
            section.process_type = payload.process_type
        if "group_code" in payload.model_fields_set:
            section.group_code = payload.group_code
        if "classification_tag_ids" in payload.model_fields_set and payload.classification_tag_ids is not None:
            self._set_classification_tags(section.id, payload.classification_tag_ids)
        self._validate_analysis_tags(
            equipment_id=target_equipment_id,
            section_id=section.id,
            width_tag_id=payload.width_tag_id if "width_tag_id" in payload.model_fields_set else section.width_tag_id,
            um_tag_id=payload.um_tag_id if "um_tag_id" in payload.model_fields_set else section.um_tag_id,
            thickness_tag_id=payload.thickness_tag_id if "thickness_tag_id" in payload.model_fields_set else section.thickness_tag_id,
            steel_type_tag_id=payload.steel_type_tag_id if "steel_type_tag_id" in payload.model_fields_set else section.steel_type_tag_id,
        )
        if "width_tag_id" in payload.model_fields_set:
            section.width_tag_id = payload.width_tag_id
        if "um_tag_id" in payload.model_fields_set:
            section.um_tag_id = payload.um_tag_id
        if "thickness_tag_id" in payload.model_fields_set:
            section.thickness_tag_id = payload.thickness_tag_id
        if "steel_type_tag_id" in payload.model_fields_set:
            section.steel_type_tag_id = payload.steel_type_tag_id
        if "analysis_tags" in payload.model_fields_set and payload.analysis_tags is not None:
            self._sync_dynamic_analysis_tags(section, payload.analysis_tags, target_equipment_id)
        elif payload.equipment_id is not None and payload.equipment_id != section.equipment_id:
            for item in section.analysis_tags:
                self._validate_tag_scope(
                    tag=item.pi_tag,
                    equipment_id=target_equipment_id,
                    section_id=section.id,
                    context_details={"variable_type_id": item.variable_type_id},
                )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise InvalidSectionError(
                "Violacao de integridade nas tags de analise da secao.",
                details={"error": str(exc.orig) if hasattr(exc, "orig") else str(exc)},
            )
        self.db.expire(section, ["classification_tags", "analysis_tags"])
        self.db.refresh(section)
        return section

    def delete(self, section_id: int) -> None:
        section = self.get(section_id)
        tags_count = self.repo.count_tags(section_id)
        if tags_count > 0:
            raise DependencyExistsError(
                "Nao e possivel excluir a secao pois existem tags relacionadas. "
                "Utilize a desativacao logica.",
                details={"section_id": section_id, "pi_tags": tags_count},
            )
        self.repo.delete(section)
        self.db.commit()
