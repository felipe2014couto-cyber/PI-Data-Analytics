"""Catalog of SIP Oracle SELECT sources."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, require_admin
from app.core.exceptions import InvalidEquipmentError, InvalidSectionError, InvalidVariableTypeError, NotFoundError, ValidationError
from app.models import Equipment, Section, SipSource, SipDatabaseTag, SipReloadJob, VariableType
from app.schemas.sip import SipColumnsRequest, SipColumnsResponse, SipSourceCreate, SipSourceResponse, SipSourceUpdate, SipDatabaseTagCreate, SipDatabaseTagResponse
from app.services.sip_oracle_service import SipOracleService, validated_select

router = APIRouter(prefix="/sip", tags=["sip"])


def _references(db: Session, equipment_id: int, section_id: int | None, variable_type_id: int) -> None:
    if db.get(Equipment, equipment_id) is None:
        raise InvalidEquipmentError()
    if db.get(VariableType, variable_type_id) is None:
        raise InvalidVariableTypeError()
    if section_id is not None:
        section = db.get(Section, section_id)
        if section is None or section.equipment_id != equipment_id:
            raise InvalidSectionError("A seção deve pertencer ao equipamento informado.")


def _columns(sql: str) -> list[str]:
    return SipOracleService().inspect_columns(validated_select(sql))


def _validate_columns(sql: str, timestamp_column: str, value_column: str) -> str:
    safe_sql = validated_select(sql)
    columns = {name.upper() for name in _columns(safe_sql)}
    if timestamp_column.upper() not in columns or value_column.upper() not in columns or timestamp_column.upper() == value_column.upper():
        raise ValidationError("Escolha colunas distintas de Timestamp e Value retornadas pelo SQL.")
    return safe_sql


@router.post("/columns", response_model=SipColumnsResponse, dependencies=[Depends(require_admin)])
def inspect_sip_columns(payload: SipColumnsRequest) -> SipColumnsResponse:
    return SipColumnsResponse(columns=_columns(payload.sql_text))


@router.get("/sources", response_model=list[SipSourceResponse])
def list_sip_sources(db: Session = Depends(get_db_session)):
    return db.scalars(select(SipSource).order_by(SipSource.name, SipSource.id)).all()


@router.post("/sources", response_model=SipSourceResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_sip_source(payload: SipSourceCreate, db: Session = Depends(get_db_session)):
    _references(db, payload.equipment_id, payload.section_id, payload.variable_type_id)
    values = payload.model_dump()
    values["sql_text"] = _validate_columns(payload.sql_text, payload.timestamp_column, payload.value_column)
    source = SipSource(**values)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.put("/sources/{source_id}", response_model=SipSourceResponse, dependencies=[Depends(require_admin)])
def update_sip_source(source_id: int, payload: SipSourceUpdate, db: Session = Depends(get_db_session)):
    source = db.get(SipSource, source_id)
    if source is None:
        raise NotFoundError("Fonte SIP não encontrada.")
    values = payload.model_dump(exclude_unset=True)
    merged = {key: values.get(key, getattr(source, key)) for key in ("equipment_id", "section_id", "variable_type_id", "sql_text", "timestamp_column", "value_column")}
    _references(db, merged["equipment_id"], merged["section_id"], merged["variable_type_id"])
    if any(key in values for key in ("sql_text", "timestamp_column", "value_column")):
        values["sql_text"] = _validate_columns(merged["sql_text"], merged["timestamp_column"], merged["value_column"])
    for key, value in values.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_sip_source(source_id: int, db: Session = Depends(get_db_session)):
    source = db.get(SipSource, source_id)
    if source is None:
        raise NotFoundError("Fonte SIP não encontrada.")
    if db.scalar(select(SipReloadJob.id).where(SipReloadJob.source_id == source_id).limit(1)) is not None:
        raise ValidationError("Remova primeiro os registros de recarga SIP desta consulta.")
    db.delete(source)
    db.commit()


@router.get("/database-tags", response_model=list[SipDatabaseTagResponse])
def list_database_tags(db: Session = Depends(get_db_session)):
    return db.scalars(select(SipDatabaseTag).order_by(SipDatabaseTag.name, SipDatabaseTag.id)).all()


@router.post("/database-tags", response_model=SipDatabaseTagResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_database_tag(payload: SipDatabaseTagCreate, db: Session = Depends(get_db_session)):
    _references(db, payload.equipment_id, payload.section_id, payload.variable_type_id)
    safe_sql = validated_select(payload.sql_text)
    if payload.value_column.upper() not in {column.upper() for column in _columns(safe_sql)}:
        raise ValidationError("Escolha uma coluna Value retornada pelo SQL.")
    # Validate that the query currently returns at most one scalar value.
    # fetch_value also rejects temporal binds and uses an Oracle read-only transaction.
    SipOracleService().fetch_value(safe_sql, payload.value_column)
    tag = SipDatabaseTag(**{**payload.model_dump(), "sql_text": safe_sql})
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.put("/database-tags/{tag_id}", response_model=SipDatabaseTagResponse, dependencies=[Depends(require_admin)])
def update_database_tag(tag_id: int, payload: SipDatabaseTagCreate, db: Session = Depends(get_db_session)):
    tag = db.get(SipDatabaseTag, tag_id)
    if tag is None:
        raise NotFoundError("Tag de Banco não encontrada.")
    _references(db, payload.equipment_id, payload.section_id, payload.variable_type_id)
    safe_sql = validated_select(payload.sql_text)
    if payload.value_column.upper() not in {column.upper() for column in _columns(safe_sql)}:
        raise ValidationError("Escolha uma coluna Value retornada pelo SQL.")
    # Validate that the query currently returns at most one scalar value.
    # fetch_value also rejects temporal binds and uses an Oracle read-only transaction.
    SipOracleService().fetch_value(safe_sql, payload.value_column)
    for key, value in {**payload.model_dump(), "sql_text": safe_sql}.items():
        setattr(tag, key, value)
    db.commit()
    db.refresh(tag)
    return tag


@router.get("/database-tags/{tag_id}/value")
def read_database_tag(tag_id: int, db: Session = Depends(get_db_session)):
    tag = db.get(SipDatabaseTag, tag_id)
    if tag is None or not tag.active:
        raise NotFoundError("Tag de Banco não encontrada.")
    return {"id": tag.id, "value": SipOracleService().fetch_value(tag.sql_text, tag.value_column)}


@router.delete("/database-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_database_tag(tag_id: int, db: Session = Depends(get_db_session)):
    tag = db.get(SipDatabaseTag, tag_id)
    if tag is None:
        raise NotFoundError("Tag de Banco não encontrada.")
    db.delete(tag)
    db.commit()
