"""PiTag business rules."""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateTagError,
    InvalidEquipmentError,
    InvalidSectionError,
    InvalidVariableTypeError,
    NotFoundError,
    SectionNotBelongsToEquipmentError,
)
from app.models.pi_tag import PiTag, PiTagValidationStatus
from app.models.section import Section
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.pi_tag_repository import PiTagRepository
from app.repositories.section_repository import SectionRepository
from app.repositories.variable_type_repository import VariableTypeRepository
from app.schemas.pi_tag import PiTagCreate, PiTagUpdate


class PiTagService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PiTagRepository(db)
        self.equipment_repo = EquipmentRepository(db)
        self.section_repo = SectionRepository(db)
        self.variable_type_repo = VariableTypeRepository(db)

    def get(self, pi_tag_id: int) -> PiTag:
        item = self.repo.get(pi_tag_id)
        if item is None:
            raise NotFoundError(
                "Tag PI nao encontrada.",
                details={"pi_tag_id": pi_tag_id},
            )
        return item

    def list(
        self,
        search: Optional[str],
        equipment_id: Optional[int],
        section_id: Optional[int],
        variable_type_id: Optional[int],
        active: Optional[bool],
        validation_status: Optional[PiTagValidationStatus],
        page: int,
        page_size: int,
    ):
        return self.repo.list(
            search=search,
            equipment_id=equipment_id,
            section_id=section_id,
            variable_type_id=variable_type_id,
            active=active,
            validation_status=validation_status,
            page=page,
            page_size=page_size,
        )

    def _validate_references(
        self,
        equipment_id: int,
        section_id: Optional[int],
        variable_type_id: int,
    ) -> None:
        equipment = self.equipment_repo.get(equipment_id)
        if equipment is None:
            raise InvalidEquipmentError(
                "Equipamento informado nao existe.",
                details={"equipment_id": equipment_id},
            )
        if section_id is not None:
            section = self.section_repo.get(section_id)
            if section is None:
                raise InvalidSectionError(
                    "Secao informada nao existe.",
                    details={"section_id": section_id},
                )
            if section.equipment_id != equipment_id:
                raise SectionNotBelongsToEquipmentError(
                    "A secao selecionada nao pertence ao equipamento informado.",
                    details={
                        "equipment_id": equipment_id,
                        "section_id": section_id,
                        "section_equipment_id": section.equipment_id,
                    },
                )
        variable_type = self.variable_type_repo.get(variable_type_id)
        if variable_type is None:
            raise InvalidVariableTypeError(
                "Tipo de variavel informado nao existe.",
                details={"variable_type_id": variable_type_id},
            )

    def _check_duplicate(
        self,
        pi_server: str,
        pi_tag_name: str,
        exclude_id: Optional[int] = None,
    ) -> None:
        existing = self.repo.get_by_server_and_name(
            pi_server=pi_server,
            pi_tag_name=pi_tag_name,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise DuplicateTagError(
                "Ja existe uma tag com este nome neste PI Server.",
                details={
                    "pi_server": pi_server,
                    "pi_tag_name": pi_tag_name,
                },
            )

    def create(self, payload: PiTagCreate) -> PiTag:
        self._validate_references(
            equipment_id=payload.equipment_id,
            section_id=payload.section_id,
            variable_type_id=payload.variable_type_id,
        )
        self._check_duplicate(pi_server=payload.pi_server, pi_tag_name=payload.pi_tag_name)
        item = PiTag(
            equipment_id=payload.equipment_id,
            section_id=payload.section_id,
            variable_type_id=payload.variable_type_id,
            pi_server=payload.pi_server,
            pi_tag_name=payload.pi_tag_name,
            lower_limit_tag=payload.lower_limit_tag,
            upper_limit_tag=payload.upper_limit_tag,
            pi_web_id=None,
            display_name=payload.display_name,
            description=payload.description,
            engineering_unit=payload.engineering_unit,
            data_type=payload.data_type,
            active=payload.active,
            validation_status=PiTagValidationStatus.PENDING,
            validation_message=None,
            validated_at=None,
        )
        self.repo.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def update(self, pi_tag_id: int, payload: PiTagUpdate) -> PiTag:
        item = self.get(pi_tag_id)
        target_equipment_id = payload.equipment_id if payload.equipment_id is not None else item.equipment_id
        target_section_id = (
            payload.section_id if "section_id" in payload.model_fields_set else item.section_id
        )
        target_variable_type_id = (
            payload.variable_type_id
            if payload.variable_type_id is not None
            else item.variable_type_id
        )

        self._validate_references(
            equipment_id=target_equipment_id,
            section_id=target_section_id,
            variable_type_id=target_variable_type_id,
        )

        if (
            (payload.pi_server is not None and payload.pi_server != item.pi_server)
            or (payload.pi_tag_name is not None and payload.pi_tag_name != item.pi_tag_name)
        ):
            new_server = payload.pi_server or item.pi_server
            new_name = payload.pi_tag_name or item.pi_tag_name
            self._check_duplicate(
                pi_server=new_server,
                pi_tag_name=new_name,
                exclude_id=item.id,
            )

        if payload.equipment_id is not None:
            item.equipment_id = payload.equipment_id
        if "section_id" in payload.model_fields_set:
            item.section_id = payload.section_id
        if payload.variable_type_id is not None:
            item.variable_type_id = payload.variable_type_id
        if payload.pi_server is not None:
            item.pi_server = payload.pi_server
        if payload.pi_tag_name is not None:
            item.pi_tag_name = payload.pi_tag_name
        if "lower_limit_tag" in payload.model_fields_set:
            item.lower_limit_tag = payload.lower_limit_tag
        if "upper_limit_tag" in payload.model_fields_set:
            item.upper_limit_tag = payload.upper_limit_tag
        if payload.display_name is not None:
            item.display_name = payload.display_name
        if payload.description is not None:
            item.description = payload.description
        if payload.engineering_unit is not None:
            item.engineering_unit = payload.engineering_unit
        if payload.data_type is not None:
            item.data_type = payload.data_type
        if payload.active is not None:
            item.active = payload.active

        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, pi_tag_id: int) -> None:
        item = self.get(pi_tag_id)
        # Analysis tag references are nullable IDs on sections so the PI tag
        # can still be removed without leaving a stale assignment behind.
        for section in self.db.query(Section).filter(
            (Section.width_tag_id == item.id)
            | (Section.um_tag_id == item.id)
            | (Section.thickness_tag_id == item.id)
        ).all():
            if section.width_tag_id == item.id:
                section.width_tag_id = None
            if section.um_tag_id == item.id:
                section.um_tag_id = None
            if section.thickness_tag_id == item.id:
                section.thickness_tag_id = None
        self.repo.delete(item)
        self.db.commit()
