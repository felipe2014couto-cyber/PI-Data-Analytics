"""RECORDED-only production statistics grouped by configured UM state segments."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
import unicodedata

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.equipment import Equipment
from app.models.section import Section
from app.models.section_analysis_tag import SectionAnalysisTag
from app.models.variable_type import VariableType
from app.schemas.pi import AnalysisFilterRequest
from app.schemas.production_unit import (
    ProductionUnitAnalysisResponse, ProductionUnitFilterConfiguration,
    ProductionUnitFilterRule, ProductionUnitSegment, ProductionUnitVariable,
)
from app.services.production_unit_filters import (
    build_filter_state_intervals, dynamic_string_condition, generic_text_condition,
    merge_coverage, numeric_condition,
)

MAX_ANALYSIS_TAGS = 50
MAX_PERIOD_DAYS = 31
MAX_UM_SEGMENTS = 500
MAX_FILTER_TAGS = 50
MAX_FILTER_STATE_EVENTS = 200_000
UM_VARIABLE_TYPE_NAMES = {"UM", "CODIGO UM", "UNIDADE MATERIAL"}


def _is_um_variable_type(variable_type: VariableType | None) -> bool:
    if variable_type is None or not variable_type.active:
        return False
    labels = {variable_type.code, variable_type.name}
    normalized = {
        " ".join("".join(char for char in unicodedata.normalize("NFD", label.upper()) if not unicodedata.combining(char)).replace("_", " ").replace("-", " ").split())
        for label in labels
    }
    return bool(normalized & UM_VARIABLE_TYPE_NAMES)


@dataclass(frozen=True)
class _Segment:
    start: datetime
    end: datetime
    value: str | None
    status: str
    start_reason: str
    end_reason: str
    state_source_timestamp: datetime | None


def _valid_um_value(event) -> str | None:
    get = event.get if hasattr(event, "get") else lambda key: getattr(event, key)
    if not get("good") or get("questionable") or get("substituted"):
        return None
    value = get("value_text")
    if value is None and get("value_boolean") is not None:
        value = "true" if get("value_boolean") else "false"
    if value is None and get("value_double") is not None:
        value = str(get("value_double"))
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _build_segments(events, start: datetime, end: datetime) -> list[_Segment]:
    """Build disjoint [start,end) segments; bad/empty UM states are unassigned."""
    current_value: str | None = None
    current_source: datetime | None = None
    current_start = start
    current_reason = "QUERY_START"
    segments: list[_Segment] = []

    for event in events:
        ts = event["ts"] if hasattr(event, "get") else event.ts
        if ts < start:
            value = _valid_um_value(event)
            if value is not None:
                current_value, current_source = value, ts
            else:
                current_value, current_source = None, None
            continue
        if ts > end:
            break
        value = _valid_um_value(event)
        if value == current_value and (value is not None or current_value is None):
            # Repeated event values do not create new UM intervals. Bad events
            # while already unassigned also do not fragment the unknown range.
            continue
        if ts > current_start:
            segments.append(_Segment(
                start=current_start, end=ts, value=current_value,
                status="ASSIGNED" if current_value is not None else "UNASSIGNED",
                start_reason=current_reason,
                end_reason="INVALID_UM_STATE" if value is None else "NEXT_UM",
                state_source_timestamp=current_source,
            ))
        previous_value = current_value
        current_start = ts
        current_value = value
        current_source = ts if value is not None else None
        current_reason = "UNKNOWN_STATE" if value is None else "STATE_RECOVERED" if previous_value is None else "UM_TRANSITION"

    if current_start < end:
        segments.append(_Segment(
            start=current_start, end=end, value=current_value,
            status="ASSIGNED" if current_value is not None else "UNASSIGNED",
            start_reason=current_reason, end_reason="QUERY_END",
            state_source_timestamp=current_source,
        ))
    return segments


def _active_dynamic_filter(item: AnalysisFilterRequest) -> bool:
    if item.min is not None or item.max is not None:
        return True
    return any(value and value.strip() not in {"", "ALL", "TODOS"} for value in (item.expression, item.value))


def _sample_column(alias: str, value_kind: str) -> str:
    if value_kind == "numeric": return f"{alias}.value_double"
    if value_kind == "digital":
        return f"COALESCE({alias}.value_text, CASE WHEN {alias}.value_boolean IS TRUE THEN 'ON' WHEN {alias}.value_boolean IS FALSE THEN 'OFF' END)"
    if value_kind == "text":
        return f"COALESCE({alias}.value_text, CASE WHEN {alias}.value_boolean IS TRUE THEN 'ON' WHEN {alias}.value_boolean IS FALSE THEN 'OFF' END, {alias}.value_double::text)"
    raise AssertionError(value_kind)


def _um_value_matches(rule: ProductionUnitFilterRule, value: str | None) -> bool:
    if value is None:
        return False
    if rule.kind == "numeric":
        try: actual, expected = float(value), float(rule.value)
        except (TypeError, ValueError): return False
        second = float(rule.second_value) if rule.second_value is not None else None
        return {
            "equal": actual == expected, "notEqual": actual != expected,
            "greaterThan": actual > expected, "greaterThanOrEqual": actual >= expected,
            "lessThan": actual < expected, "lessThanOrEqual": actual <= expected,
            "between": second is not None and expected <= actual <= second,
            "outside": second is not None and (actual < expected or actual > second),
        }.get(rule.operator or "", False)
    if rule.kind != "text":
        return True
    target = str(rule.value if rule.value is not None else "")
    subject = value if rule.case_sensitive else value.lower()
    expected = target if rule.case_sensitive else target.lower()
    if rule.operator == "equal": return subject == expected
    if rule.operator == "notEqual": return subject != expected
    if rule.operator == "contains": return expected in subject
    if rule.operator == "startsWith": return subject.startswith(expected)
    if rule.operator == "endsWith": return subject.endswith(expected)
    if rule.operator == "wildcard":
        return any(re.fullmatch(".*".join(re.escape(part) for part in item.strip().split("*")), subject) is not None
                   for item in target.split(";") if item.strip())
    return False


class ProductionUnitService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _resolve_filter_plan(self, section: Section | None, tags: list[PiTag], configuration: ProductionUnitFilterConfiguration,
                             dynamic_filters: list[AnalysisFilterRequest], equipment_id: int | None = None):
        equipment_id = equipment_id if equipment_id is not None else section.equipment_id if section is not None else None
        if equipment_id is None:
            raise ValidationError("Informe equipamento para resolver as tags de filtro.")
        enabled = configuration.filters_enabled
        rules = [rule for rule in configuration.rules if rule.enabled] if enabled else []
        dynamic = [item for item in dynamic_filters if _active_dynamic_filter(item)] if enabled else []
        targets: set[int] = set()
        resolved_rules: list[tuple[ProductionUnitFilterRule, int | None]] = []
        for index, rule in enumerate(rules):
            if rule.series_instance_id:
                raise ValidationError("Filtros vinculados a uma instância de série não são suportados na análise por UM; use o filtro da tag.")
            target_id = rule.tag_id
            if rule.kind in {"numeric", "text", "excludeValue"}:
                if target_id is None:
                    raise ValidationError(f"O filtro {rule.id} não informa a tag de origem.")
                if rule.section_tag_map is not None:
                    if section is None:
                        continue  # A regra mapeada por seção não se aplica ao escopo do equipamento inteiro.
                    if section.id not in rule.section_tag_map:
                        continue  # Mesmo comportamento neutro da configuração multisseção.
                    target_id = rule.section_tag_map[section.id]
                if target_id is None:
                    raise ValidationError(f"O filtro {rule.id} não resolve uma tag para a seção selecionada.")
                targets.add(target_id)
                if rule.kind == "numeric" and rule.operator not in {"equal", "notEqual", "greaterThan", "greaterThanOrEqual", "lessThan", "lessThanOrEqual", "between", "outside"}:
                    raise ValidationError(f"Operador numérico não suportado no filtro {rule.id}.")
                if rule.kind == "text" and rule.operator not in {"equal", "notEqual", "contains", "startsWith", "endsWith", "wildcard"}:
                    raise ValidationError(f"Operador textual não suportado no filtro {rule.id}.")
                if rule.kind == "excludeValue" and rule.value_type is None:
                    raise ValidationError(f"O filtro {rule.id} não informa o tipo do valor excluído.")
                if rule.kind == "text" and not isinstance(rule.value, str):
                    raise ValidationError(f"O filtro textual {rule.id} não contém texto válido.")
                if rule.kind == "excludeValue":
                    valid_type = ((rule.value_type == "number" and isinstance(rule.value, (int, float)) and not isinstance(rule.value, bool))
                                  or (rule.value_type == "string" and isinstance(rule.value, str) and bool(rule.value.strip()))
                                  or (rule.value_type == "boolean" and isinstance(rule.value, bool)))
                    if not valid_type:
                        raise ValidationError(f"O valor de exclusão do filtro {rule.id} é incompatível com seu tipo.")
            resolved_rules.append((rule, target_id))

        variable_ids = {item.variable_type_id for item in dynamic}
        dynamic_specs: list[tuple[AnalysisFilterRequest, int, str]] = []
        if variable_ids:
            if section is None:
                raise ValidationError("Filtros dinâmicos por variável exigem uma seção específica.")
            associations = self.db.query(SectionAnalysisTag).filter(
                SectionAnalysisTag.section_id == section.id,
                SectionAnalysisTag.variable_type_id.in_(variable_ids),
            ).all()
            by_variable = {item.variable_type_id: item for item in associations}
            for item in dynamic:
                association = by_variable.get(item.variable_type_id)
                if association is None or association.pi_tag is None or association.variable_type is None:
                    raise ValidationError(f"A variável de filtro {item.variable_type_id} não está configurada na seção.")
                if not association.pi_tag.active:
                    raise ValidationError(f"A tag do filtro {association.pi_tag.pi_tag_name} está inativa.")
                kind = association.variable_type.filter_data_type.value
                if kind not in {"REAL", "STRING", "DIGITAL"}:
                    raise ValidationError(f"Tipo de filtro não suportado para {association.pi_tag.pi_tag_name}.")
                targets.add(association.pi_tag_id)
                dynamic_specs.append((item, association.pi_tag_id, kind))

        if len(targets) > MAX_FILTER_TAGS:
            raise ValidationError(f"A análise aceita até {MAX_FILTER_TAGS} tags de contexto/filtro.")
        target_tags = self.db.query(PiTag).filter(PiTag.id.in_(targets)).all() if targets else []
        by_target = {tag.id: tag for tag in target_tags}
        for tag_id in targets:
            tag = by_target.get(tag_id)
            scope_matches = tag is not None and (tag.section_id is None if section is None else tag.section_id in (None, section.id))
            if tag is None or not tag.active or tag.equipment_id != equipment_id or not scope_matches:
                raise ValidationError(f"A tag de filtro {tag_id} está ausente, inativa ou fora do escopo da seção.")
        return resolved_rules, dynamic_specs, targets

    def resolve_um_tag(self, equipment_id: int, section_id: int | None) -> PiTag:
        """Resolve exactly one active UM in the requested equipment/section scope."""
        equipment = self.db.get(Equipment, equipment_id)
        if equipment is None or not equipment.active:
            raise NotFoundError("Equipamento não encontrado ou inativo.")

        section = None
        if section_id is not None:
            section = self.db.get(Section, section_id)
            if section is None or not section.active or section.equipment_id != equipment_id:
                raise ValidationError("A seção informada não pertence ao equipamento ou está inativa.")

        scoped_tags = self.db.query(PiTag).filter(
            PiTag.equipment_id == equipment_id,
            PiTag.active.is_(True),
            PiTag.section_id.is_(None) if section is None else PiTag.section_id == section.id,
        ).all()
        candidates = [tag for tag in scoped_tags if hasattr(tag, "variable_type") and _is_um_variable_type(tag.variable_type)]

        if section is not None and section.um_tag_id is not None:
            configured = self.db.get(PiTag, section.um_tag_id)
            if configured is None or not configured.active:
                raise ValidationError("A tag UM configurada para esta seção está ausente ou inativa.")
            configured_is_um = _is_um_variable_type(configured.variable_type) if hasattr(configured, "variable_type") else True
            if getattr(configured, "equipment_id", equipment_id) != equipment_id or getattr(configured, "section_id", None) not in (None, section.id) or not configured_is_um:
                raise ValidationError("A tag UM configurada para esta seção está fora do escopo ou não é do tipo UM.")
            if all(tag.id != configured.id for tag in candidates):
                candidates.append(configured)

        if len(candidates) > 1:
            scope = "o equipamento inteiro" if section is None else "esta seção"
            raise ValidationError(f"Configuração ambígua: há mais de uma tag UM ativa para {scope}.")
        if not candidates:
            if section is None:
                raise ValidationError("Não há tag UM configurada para o equipamento inteiro.")
            raise ValidationError("Não há tag UM configurada para esta seção.")
        um_tag = candidates[0]
        if um_tag.data_type != PiTagDataType.NON_NUMERIC:
            raise ValidationError("A tag configurada como UM deve ser STRING/DIGITAL.")
        return um_tag

    @staticmethod
    def _compile_filters(section: Section, aggregate_tags: list[PiTag], aliases: dict[int, str],
                         rules: list[tuple[ProductionUnitFilterRule, int | None]],
                         dynamic_specs: list[tuple[AnalysisFilterRequest, int, str]],
                         configuration: ProductionUnitFilterConfiguration):
        params: dict[str, Any] = {}
        conditions: list[str] = []
        counter = 0

        def add_tag_condition(target_id: int, predicate_builder) -> str:
            nonlocal counter
            direct_prefix, state_prefix = f"pf{counter}_d", f"pf{counter}_s"
            counter += 1
            direct = predicate_builder("p", direct_prefix)
            # With one analyzed tag, a rule targeting that same tag is a
            # per-sample predicate. Its as-of state is never consulted.
            if len(aggregate_tags) == 1 and aggregate_tags[0].id == target_id:
                return f"({direct})"
            alias = aliases[target_id]
            state = predicate_builder(alias, state_prefix)
            same_ref = f":pf_same_{counter}"
            params[f"pf_same_{counter}"] = target_id
            return f"((t.tag_id = {same_ref} AND ({direct})) OR (t.tag_id <> {same_ref} AND ({state})))"

        for rule, target_id in rules:
            if rule.kind in {"numeric", "text", "excludeValue"} and target_id is None:
                continue
            if rule.kind == "weekday":
                days = rule.days or []
                if not days:
                    raise ValidationError(f"O filtro {rule.id} precisa conter ao menos um dia da semana.")
                day_numbers = {"monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6, "sunday": 0}
                refs = []
                for i, day in enumerate(sorted({day_numbers[x] for x in days})):
                    name = f"weekday_{counter}_{i}"; params[name] = day; refs.append(f":{name}")
                conditions.append(f"((EXTRACT(ISODOW FROM p.ts AT TIME ZONE 'America/Sao_Paulo')::integer % 7) IN ({', '.join(refs)}))")
                counter += 1
                continue
            if rule.kind == "timeRange":
                if not rule.start_time or not rule.end_time:
                    raise ValidationError(f"O filtro {rule.id} precisa informar início e fim HH:mm.")
                for value in (rule.start_time, rule.end_time):
                    if len(value) != 5 or value[2] != ":" or not value[:2].isdigit() or not value[3:].isdigit() or int(value[:2]) > 23 or int(value[3:]) > 59:
                        raise ValidationError(f"O filtro {rule.id} contém horário inválido.")
                start_name, end_name = f"time_start_{counter}", f"time_end_{counter}"
                params[start_name], params[end_name] = rule.start_time, rule.end_time
                local_time = "TO_CHAR(p.ts AT TIME ZONE 'America/Sao_Paulo', 'HH24:MI')"
                if rule.start_time <= rule.end_time:
                    conditions.append(f"({local_time} >= :{start_name} AND {local_time} <= :{end_name})")
                else:
                    conditions.append(f"({local_time} >= :{start_name} OR {local_time} <= :{end_name})")
                counter += 1
                continue
            assert target_id is not None
            if rule.kind == "numeric":
                def build_numeric(alias, prefix):
                    col = f"{alias}.value_double"
                    return f"{col} IS NOT NULL AND {numeric_condition(col, rule.operator or '', rule.value, rule.second_value, params, prefix)}"
                conditions.append(add_tag_condition(target_id, build_numeric))
            elif rule.kind == "text":
                value = str(rule.value if rule.value is not None else "")
                def build_text(alias, prefix):
                    col = _sample_column(alias, "text")
                    return generic_text_condition(col, rule.operator or "", value, params, prefix, case_sensitive=rule.case_sensitive)
                conditions.append(add_tag_condition(target_id, build_text))
            elif rule.kind == "excludeValue":
                value_type = rule.value_type
                col = "p.value_double" if value_type == "number" else "p.value_boolean" if value_type == "boolean" else "p.value_text"
                value_name = f"exclude_{counter}"; params[value_name] = rule.value if value_type != "string" else str(rule.value)
                if value_type == "string" and not rule.case_sensitive:
                    exclusion = f"LOWER({col}) = LOWER(:{value_name})"
                else:
                    exclusion = f"{col} = :{value_name}"
                same_ref = f":exclude_tag_{counter}"; params[f"exclude_tag_{counter}"] = target_id
                conditions.append(f"(t.tag_id <> {same_ref} OR NOT COALESCE(({exclusion}), FALSE))")
                counter += 1

        for item, target_id, data_type in dynamic_specs:
            def build_dynamic(alias, prefix):
                if data_type == "REAL":
                    col = f"{alias}.value_double"
                    parts = [f"{col} IS NOT NULL"]
                    if item.min is not None:
                        name = f"{prefix}_min"; params[name] = item.min; parts.append(f"{col} >= :{name}")
                    if item.max is not None:
                        name = f"{prefix}_max"; params[name] = item.max; parts.append(f"{col} <= :{name}")
                    if item.min is not None and item.max is not None and item.min > item.max:
                        raise ValidationError("Valor mínimo não pode ser maior que o valor máximo.")
                    if item.min is None and item.max is None:
                        raw = (item.value or item.expression or "").strip()
                        if not raw or raw.upper() in {"ALL", "TODOS"}:
                            raise ValidationError(f"Filtro REAL ativo da variável {item.variable_type_id} não contém um limite válido.")
                        try: exact = float(raw)
                        except ValueError as exc: raise ValidationError("O filtro REAL deve conter um número.") from exc
                        if not math.isfinite(exact): raise ValidationError("O filtro REAL deve conter um número finito.")
                        name = f"{prefix}_exact"; params[name] = exact; parts.append(f"{col} = :{name}")
                    return " AND ".join(parts)
                if data_type == "DIGITAL":
                    raw = (item.value or item.expression or "").strip().upper()
                    if raw not in {"ON", "OFF"}:
                        raise ValidationError(f"Estado DIGITAL não suportado: {raw}.")
                    expected = "TRUE" if raw == "ON" else "FALSE"
                    return f"{alias}.value_boolean IS {expected}"
                expression = (item.value if item.value and item.value.upper() not in {"ALL", "TODOS"} else item.expression or "").strip()
                if not expression:
                    raise ValidationError(f"Filtro STRING ativo da variável {item.variable_type_id} está vazio.")
                return dynamic_string_condition(_sample_column(alias, "text"), expression, params, prefix)
            conditions.append(add_tag_condition(target_id, build_dynamic))

        if configuration.filters_enabled:
            quality = configuration.quality
            if quality.exclude_bad: conditions.append("p.good IS TRUE")
            if quality.exclude_questionable: conditions.append("p.questionable IS FALSE")
            if quality.exclude_substituted: conditions.append("p.substituted IS FALSE")
        return " AND ".join(f"({item})" for item in conditions) if conditions else "TRUE", params

    def analyze(self, section_id: int | None, tag_ids: list[int], start: datetime, end: datetime,
                filter_configuration: ProductionUnitFilterConfiguration | None = None,
                analysis_filters: list[AnalysisFilterRequest] | None = None, *, equipment_id: int | None = None, use_store: bool = True, collect_quality_counts: bool = False) -> ProductionUnitAnalysisResponse:
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValidationError("Informe um intervalo válido com timezone explícito.")
        if (end - start).total_seconds() > MAX_PERIOD_DAYS * 86400:
            raise ValidationError(f"A análise por UM aceita períodos de até {MAX_PERIOD_DAYS} dias.")
        unique_tag_ids = list(dict.fromkeys(tag_ids))
        if not unique_tag_ids or len(unique_tag_ids) > MAX_ANALYSIS_TAGS:
            raise ValidationError(f"Selecione de 1 a {MAX_ANALYSIS_TAGS} tags de processo.")

        section = self.db.get(Section, section_id) if section_id is not None else None
        if section_id is not None and (section is None or not section.active):
            raise NotFoundError("Seção não encontrada ou inativa.")
        resolved_equipment_id = section.equipment_id if section is not None else equipment_id
        if resolved_equipment_id is None:
            raise ValidationError("Informe equipment_id para resolver a UM do equipamento inteiro.")
        if equipment_id is not None and section is not None and equipment_id != section.equipment_id:
            raise ValidationError("A seção informada não pertence ao equipamento selecionado.")
        um_tag = self.resolve_um_tag(resolved_equipment_id, section_id)

        tags = self.db.query(PiTag).filter(
            PiTag.id.in_(unique_tag_ids),
            PiTag.equipment_id == resolved_equipment_id,
            PiTag.active.is_(True),
        ).all()
        by_id = {tag.id: tag for tag in tags}
        if len(by_id) != len(unique_tag_ids):
            raise ValidationError("Uma ou mais tags selecionadas estão ausentes, inativas ou pertencem a outro equipamento.")
        unique_tag_ids = [tag_id for tag_id in unique_tag_ids if tag_id != um_tag.id]
        tags = [by_id[tag_id] for tag_id in unique_tag_ids]
        if not tags:
            raise ValidationError("Selecione ao menos uma tag de processo diferente da própria UM.")

        filter_configuration = filter_configuration or ProductionUnitFilterConfiguration()
        resolved_rules, dynamic_specs, filter_tag_ids = self._resolve_filter_plan(
            section, tags, filter_configuration, analysis_filters or [], equipment_id=resolved_equipment_id,
        )
        # The selected series' own rules inspect each process sample directly.
        # Only context tags used to filter other selected series need as-of
        # event and coverage state.
        if len(tags) == 1:
            filter_tag_ids.discard(tags[0].id)

        from app.services.production_unit_store import ProductionUnitStore
        # Preserve original filtering SQL for every explicit sample filter.
        allow_stats = not resolved_rules and not dynamic_specs
        stored = ProductionUnitStore(self.db).load(resolved_equipment_id, section_id, um_tag, tags, start, end, allow_stats) if use_store else None
        cached_rows = []
        if stored is not None:
            stored_segments, cached_rows = stored
            segments = [_Segment(item.start_time, item.end_time, item.um_value, item.status, item.start_reason, item.end_reason, item.state_source_timestamp) for item in stored_segments]
        else:
            event_rows = self.db.execute(text("""
                SELECT ts, value_text, value_double, value_boolean, good, questionable, substituted
                FROM (
                    (SELECT ts, value_text, value_double, value_boolean, good, questionable, substituted, ingested_at
                     FROM pi_samples_timescale
                     WHERE tag_id=:tag_id AND source_mode='RECORDED' AND ts < :start
                     ORDER BY ts DESC, (good AND NOT questionable AND NOT substituted) DESC, ingested_at DESC, value_text DESC NULLS LAST LIMIT 1)
                    UNION ALL
                    (SELECT ts, value_text, value_double, value_boolean, good, questionable, substituted, ingested_at
                     FROM pi_samples_timescale
                     WHERE tag_id=:tag_id AND source_mode='RECORDED' AND ts >= :start AND ts <= :end)
                ) events ORDER BY ts, (good AND NOT questionable AND NOT substituted) ASC,
                    ingested_at ASC, value_text NULLS FIRST, value_boolean NULLS FIRST, value_double NULLS FIRST
            """), {"tag_id": um_tag.id, "start": start, "end": end}).mappings().all()
            segments = _build_segments(event_rows, start, end)
        um_selection_rules = [rule for rule, target in resolved_rules if target == um_tag.id and rule.kind in {"numeric", "text"}]
        if um_selection_rules:
            cached_rows = []
            segments = [segment for segment in segments if all(_um_value_matches(rule, segment.value) for rule in um_selection_rules)]
        if len(segments) > MAX_UM_SEGMENTS:
            raise ValidationError(f"O período contém mais de {MAX_UM_SEGMENTS} intervalos de UM; reduza a janela.")

        filter_state_rows: list[dict[str, Any]] = []
        if filter_tag_ids:
            context_events = self.db.execute(text("""
                WITH in_window AS (
                    SELECT tag_id, ts, value_text, value_double, value_boolean, good, questionable, substituted,
                        row_number() OVER (PARTITION BY tag_id, ts ORDER BY
                            (good AND NOT questionable AND NOT substituted) DESC, ingested_at DESC,
                            value_text NULLS LAST, value_boolean NULLS LAST, value_double NULLS LAST) AS duplicate_rank
                    FROM pi_samples_timescale
                    WHERE tag_id = ANY(CAST(:tag_ids AS integer[])) AND source_mode='RECORDED'
                      AND ts > :start AND ts < :end
                )
                SELECT tag_id, ts, value_text, value_double, value_boolean, good, questionable, substituted
                FROM (
                    SELECT DISTINCT ON (tag_id) tag_id, ts, value_text, value_double, value_boolean,
                        good, questionable, substituted
                    FROM pi_samples_timescale
                    WHERE tag_id = ANY(CAST(:tag_ids AS integer[])) AND source_mode='RECORDED' AND ts <= :start
                    ORDER BY tag_id, ts DESC, (good AND NOT questionable AND NOT substituted) DESC,
                        ingested_at DESC, value_text NULLS LAST, value_boolean NULLS LAST, value_double NULLS LAST
                ) seeds
                UNION ALL
                SELECT tag_id, ts, value_text, value_double, value_boolean, good, questionable, substituted
                FROM in_window WHERE duplicate_rank=1
                ORDER BY tag_id, ts LIMIT :state_event_limit
            """), {"tag_ids": sorted(filter_tag_ids), "start": start, "end": end,
                  "state_event_limit": MAX_FILTER_STATE_EVENTS + 1}).mappings().all()
            if len(context_events) > MAX_FILTER_STATE_EVENTS:
                raise ValidationError(f"O período contém mais de {MAX_FILTER_STATE_EVENTS} eventos de estado para os filtros; reduza a janela ou a quantidade de filtros.")
            coverage_rows = self.db.execute(text("""
                SELECT tag_id, range_start, range_end
                FROM pi_ingestion_coverage
                WHERE tag_id = ANY(CAST(:tag_ids AS integer[])) AND mode='RECORDED'
                  AND interval_seconds IS NULL AND status IN ('COMPLETE', 'EMPTY_CONFIRMED')
                  AND range_end > :start AND range_start < :end
                ORDER BY tag_id, range_start
            """), {"tag_ids": sorted(filter_tag_ids), "start": start, "end": end}).mappings().all()
            coverage_by_tag = merge_coverage(coverage_rows, filter_tag_ids)
            filter_state_rows = build_filter_state_intervals(context_events, coverage_by_tag, start, end)

        if filter_configuration.filters_enabled:
            cached_rows = [row for row in cached_rows if len(row.get("quality_counts", {})) == 8]
            quality = filter_configuration.quality
            mask = (1 if quality.exclude_bad else 0) | (2 if quality.exclude_questionable else 0) | (4 if quality.exclude_substituted else 0)
            for row in cached_rows:
                counts = row.get("quality_counts", {})
                row["filtered_sample_count"] = counts.get(str(mask), row["raw_sample_count"])
                row["excluded_quality_count"] = row["filtered_sample_count"] - counts.get("7", row["sample_count"])
        cached_indices = {index for index in range(len(segments)) if sum(row["segment_index"] == index for row in cached_rows) == len(tags)}
        cached_rows = [row for row in cached_rows if row["segment_index"] in cached_indices]
        segments_json = json.dumps([
            {"segment_index": index, "start_ts": item.start.isoformat(), "end_ts": item.end.isoformat(), "um_value": item.value}
            for index, item in enumerate(segments) if index not in cached_indices
        ])
        tags_json = json.dumps([
            {"tag_id": tag.id, "tag_name": tag.pi_tag_name, "display_name": tag.display_name,
             "data_type": tag.data_type.value if hasattr(tag.data_type, "value") else str(tag.data_type),
             "unit": tag.engineering_unit}
            for tag in tags
        ])
        state_json = json.dumps(filter_state_rows)
        state_aliases = {tag_id: f"fs{index}" for index, tag_id in enumerate(sorted(filter_tag_ids))}
        filter_sql, filter_params = self._compile_filters(section, tags, state_aliases, resolved_rules, dynamic_specs, filter_configuration)
        state_joins = " ".join(
            f"LEFT JOIN filter_states {alias} ON {alias}.tag_id=:filter_tag_{index} AND p.ts >= {alias}.start_ts AND p.ts < {alias}.end_ts"
            for index, (tag_id, alias) in enumerate(sorted(state_aliases.items()))
        )
        state_params = {f"filter_tag_{index}": tag_id for index, tag_id in enumerate(sorted(state_aliases))}
        quality_count_sql = ",\n".join(
            f"count(p.ts) FILTER (WHERE {' AND '.join(condition for bit, condition in ((1, 'p.good'), (2, 'NOT p.questionable'), (4, 'NOT p.substituted')) if mask & bit) or 'TRUE'}) AS quality_count_{mask}"
            for mask in range(8)
        )
        quality_count_sql = quality_count_sql + "," if collect_quality_counts else ""
        aggregate_rows = self.db.execute(text(f"""
            WITH segments AS (
                SELECT * FROM jsonb_to_recordset(CAST(:segments AS jsonb))
                AS x(segment_index integer, start_ts timestamptz, end_ts timestamptz, um_value text)
            ), tags AS (
                SELECT * FROM jsonb_to_recordset(CAST(:tags AS jsonb))
                AS x(tag_id integer, tag_name text, display_name text, data_type text, unit text)
            ), filter_states AS (
                SELECT * FROM jsonb_to_recordset(CAST(:filter_states AS jsonb))
                AS x(tag_id integer, start_ts timestamptz, end_ts timestamptz,
                    value_double double precision, value_text text, value_boolean boolean)
            )
            SELECT s.segment_index, t.tag_id, t.tag_name, t.display_name, t.data_type, t.unit,
                {quality_count_sql}
                count(p.ts) AS raw_sample_count,
                count(p.ts) FILTER (WHERE {filter_sql}) AS filtered_sample_count,
                count(p.ts) FILTER (WHERE ({filter_sql}) AND p.good AND NOT p.questionable AND NOT p.substituted
                    AND ((t.data_type='NUMERIC' AND p.value_double IS NOT NULL)
                      OR (t.data_type<>'NUMERIC' AND (p.value_text IS NOT NULL OR p.value_boolean IS NOT NULL OR p.value_double IS NOT NULL)))) AS sample_count,
                count(p.ts) FILTER (WHERE ({filter_sql}) AND p.ts IS NOT NULL AND NOT (p.good AND NOT p.questionable AND NOT p.substituted)) AS excluded_quality_count,
                avg(p.value_double) FILTER (WHERE ({filter_sql}) AND t.data_type='NUMERIC' AND p.good AND NOT p.questionable AND NOT p.substituted AND p.value_double IS NOT NULL) AS average,
                min(p.value_double) FILTER (WHERE ({filter_sql}) AND t.data_type='NUMERIC' AND p.good AND NOT p.questionable AND NOT p.substituted AND p.value_double IS NOT NULL) AS minimum,
                max(p.value_double) FILTER (WHERE ({filter_sql}) AND t.data_type='NUMERIC' AND p.good AND NOT p.questionable AND NOT p.substituted AND p.value_double IS NOT NULL) AS maximum,
                min(p.ts) FILTER (WHERE ({filter_sql}) AND p.good AND NOT p.questionable AND NOT p.substituted AND p.ts IS NOT NULL
                    AND ((t.data_type='NUMERIC' AND p.value_double IS NOT NULL) OR (t.data_type<>'NUMERIC' AND (p.value_text IS NOT NULL OR p.value_boolean IS NOT NULL OR p.value_double IS NOT NULL)))) AS first_timestamp,
                max(p.ts) FILTER (WHERE ({filter_sql}) AND p.good AND NOT p.questionable AND NOT p.substituted AND p.ts IS NOT NULL
                    AND ((t.data_type='NUMERIC' AND p.value_double IS NOT NULL) OR (t.data_type<>'NUMERIC' AND (p.value_text IS NOT NULL OR p.value_boolean IS NOT NULL OR p.value_double IS NOT NULL)))) AS last_timestamp,
                (array_agg(COALESCE(p.value_text, p.value_boolean::text, p.value_double::text)
                    ORDER BY p.ts, p.ingested_at, p.value_text NULLS FIRST, p.value_boolean NULLS FIRST, p.value_double NULLS FIRST)
                    FILTER (WHERE ({filter_sql}) AND t.data_type<>'NUMERIC' AND p.good AND NOT p.questionable AND NOT p.substituted AND p.ts IS NOT NULL AND COALESCE(p.value_text, p.value_boolean::text, p.value_double::text) IS NOT NULL))[1] AS first_value,
                (array_agg(COALESCE(p.value_text, p.value_boolean::text, p.value_double::text)
                    ORDER BY p.ts DESC, p.ingested_at DESC, p.value_text DESC NULLS LAST, p.value_boolean DESC NULLS LAST, p.value_double DESC NULLS LAST)
                    FILTER (WHERE ({filter_sql}) AND t.data_type<>'NUMERIC' AND p.good AND NOT p.questionable AND NOT p.substituted AND p.ts IS NOT NULL AND COALESCE(p.value_text, p.value_boolean::text, p.value_double::text) IS NOT NULL))[1] AS last_value
            FROM segments s CROSS JOIN tags t
            LEFT JOIN pi_samples_timescale p ON p.tag_id=t.tag_id AND p.source_mode='RECORDED'
              AND p.ts >= s.start_ts AND p.ts < s.end_ts
              AND p.ts >= :analysis_start AND p.ts < :analysis_end
            {state_joins}
            GROUP BY s.segment_index,t.tag_id,t.tag_name,t.display_name,t.data_type,t.unit
            ORDER BY s.segment_index,t.tag_id
        """), {"segments": segments_json, "tags": tags_json, "filter_states": state_json,
                "analysis_start": start, "analysis_end": end, **state_params, **filter_params}).mappings().all()

        runtime_raw_sample_count = sum(int(row["raw_sample_count"] or 0) for row in aggregate_rows)
        aggregate_rows = list(aggregate_rows) + cached_rows
        self.last_aggregate_rows = aggregate_rows
        variables_by_segment: dict[int, list[ProductionUnitVariable]] = {}
        for row in aggregate_rows:
            variables_by_segment.setdefault(row["segment_index"], []).append(ProductionUnitVariable(
                tag_id=row["tag_id"], tag_name=row["tag_name"], display_name=row["display_name"],
                data_type=row["data_type"], unit=row["unit"], sample_count=int(row["sample_count"] or 0),
                raw_sample_count=int(row["raw_sample_count"] or 0),
                filtered_sample_count=int(row["filtered_sample_count"] or 0),
                excluded_quality_count=int(row["excluded_quality_count"] or 0),
                average=float(row["average"]) if row["average"] is not None else None,
                minimum=float(row["minimum"]) if row["minimum"] is not None else None,
                maximum=float(row["maximum"]) if row["maximum"] is not None else None,
                first_timestamp=row["first_timestamp"], last_timestamp=row["last_timestamp"],
                first_value=row["first_value"], last_value=row["last_value"],
            ))
        output_segments = [ProductionUnitSegment(
            segment_id=f"{um_tag.id}:{item.start.isoformat()}", um_value=item.value,
            status=item.status, start_time=item.start, end_time=item.end,
            duration_seconds=(item.end-item.start).total_seconds(), start_reason=item.start_reason,
            end_reason=item.end_reason, state_source_timestamp=item.state_source_timestamp,
            variables=variables_by_segment.get(index, []),
        ) for index, item in enumerate(segments)]
        return ProductionUnitAnalysisResponse(
            section_id=section.id if section is not None else None,
            equipment_id=resolved_equipment_id, um_tag_id=um_tag.id, um_tag_name=um_tag.pi_tag_name,
            start_time=start, end_time=end, segments=output_segments,
            strategy="production_unit_precomputed" if cached_indices else "production_unit_filtered_runtime" if stored is not None else "production_unit_recorded_runtime",
            precomputed_segments=len(cached_indices), runtime_segments=len(segments) - len(cached_indices),
            runtime_raw_sample_count=runtime_raw_sample_count,
        )
