"""Helpers for RECORDED as-of filter state used by UM aggregation."""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from app.core.exceptions import ValidationError
from app.schemas.production_unit import ProductionUnitFilterRule
from app.services.string_filter_parser import ExactMatch, RangeMatch, WildcardMatch, parse_string_filter


def merge_coverage(rows, tag_ids: set[int]) -> dict[int, list[tuple[datetime, datetime]]]:
    grouped: dict[int, list[tuple[datetime, datetime]]] = {tag_id: [] for tag_id in tag_ids}
    for row in rows:
        get = row.get if hasattr(row, "get") else lambda key: getattr(row, key)
        grouped.setdefault(get("tag_id"), []).append((get("range_start"), get("range_end")))
    for tag_id, intervals in grouped.items():
        merged: list[tuple[datetime, datetime]] = []
        for left, right in sorted(intervals):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        grouped[tag_id] = merged
    return grouped


def build_filter_state_intervals(events, coverage, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Return valid state intervals, clipped at uncovered coverage and query bounds."""
    by_tag: dict[int, list[Any]] = {}
    for event in events:
        by_tag.setdefault(event["tag_id"], []).append(event)

    output: list[dict[str, Any]] = []
    for tag_id, tag_events in by_tag.items():
        tag_events.sort(key=lambda e: e["ts"])
        covered = coverage.get(tag_id, [])
        for index, event in enumerate(tag_events):
            state_start = max(start, event["ts"])
            next_start = tag_events[index + 1]["ts"] if index + 1 < len(tag_events) else end
            if state_start >= end or state_start >= next_start:
                continue
            if not (event["good"] and not event["questionable"] and not event["substituted"]):
                continue
            if event["value_text"] is None and event["value_double"] is None and event["value_boolean"] is None:
                continue
            # State is usable only while the sample time remains in the same
            # continuously covered interval. Never carry across an uncovered gap.
            coverage_end = next((right for left, right in covered if left <= state_start < right), None)
            if coverage_end is None:
                continue
            state_end = min(next_start, end, coverage_end)
            if state_start >= state_end:
                continue
            output.append({
                "tag_id": tag_id,
                "start_ts": state_start.isoformat(),
                "end_ts": state_end.isoformat(),
                "value_double": event["value_double"],
                "value_text": event["value_text"],
                "value_boolean": event["value_boolean"],
            })
    return output


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def bind(params: dict[str, Any], name: str, value: Any) -> str:
    params[name] = value
    return f":{name}"


def numeric_condition(column: str, operator: str, value: Any, second: Any, params: dict[str, Any], prefix: str) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValidationError("Filtro REAL sem valor numérico válido.")
    first_ref = bind(params, f"{prefix}_value", float(value))
    if operator == "equal": return f"{column} = {first_ref}"
    if operator == "notEqual": return f"{column} <> {first_ref}"
    if operator == "greaterThan": return f"{column} > {first_ref}"
    if operator == "greaterThanOrEqual": return f"{column} >= {first_ref}"
    if operator == "lessThan": return f"{column} < {first_ref}"
    if operator == "lessThanOrEqual": return f"{column} <= {first_ref}"
    if operator in {"between", "outside"}:
        if not isinstance(second, (int, float)) or isinstance(second, bool) or not math.isfinite(float(second)) or float(value) > float(second):
            raise ValidationError("Intervalo REAL inválido: informe limites crescentes.")
        second_ref = bind(params, f"{prefix}_second", float(second))
        if operator == "between": return f"{column} BETWEEN {first_ref} AND {second_ref}"
        return f"({column} < {first_ref} OR {column} > {second_ref})"
    raise ValidationError(f"Operador REAL não suportado: {operator}.")


def generic_text_condition(column: str, operator: str, value: str, params: dict[str, Any], prefix: str, *, case_sensitive: bool) -> str:
    lhs = column if case_sensitive else f"LOWER({column})"
    if operator == "wildcard":
        clauses = []
        for index, part in enumerate(value.split(";")):
            part = part.strip()
            if not part: continue
            pattern = "%".join(escape_like(fragment) for fragment in part.split("*"))
            name = f"{prefix}_{index}"
            rhs = bind(params, name, pattern)
            clauses.append(f"{lhs} LIKE {rhs} ESCAPE '\\'" if case_sensitive else f"{lhs} LIKE LOWER({rhs}) ESCAPE '\\'")
        return f"{column} IS NOT NULL AND ({' OR '.join(clauses)})" if clauses else "FALSE"
    name = f"{prefix}_value"
    raw = value if case_sensitive else value.lower()
    rhs = bind(params, name, raw)
    if operator == "equal": expression = f"{lhs} = {rhs}"
    elif operator == "notEqual": expression = f"{lhs} <> {rhs}"
    elif operator in {"contains", "startsWith", "endsWith"}:
        escaped = escape_like(value)
        pattern = f"%{escaped}%" if operator == "contains" else f"{escaped}%" if operator == "startsWith" else f"%{escaped}"
        params[name] = pattern if case_sensitive else pattern.lower()
        expression = f"{lhs} LIKE {rhs} ESCAPE '\\'"
    else:
        raise ValidationError(f"Operador STRING não suportado: {operator}.")
    return f"{column} IS NOT NULL AND ({expression})"


def dynamic_string_condition(column: str, expression: str, params: dict[str, Any], prefix: str) -> str:
    try:
        tokens = parse_string_filter(expression)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    clauses: list[str] = []
    for index, token in enumerate(tokens):
        name = f"{prefix}_{index}"
        if isinstance(token, ExactMatch):
            clauses.append(f"LOWER({column}) = LOWER({bind(params, name, token.value)})")
        elif isinstance(token, WildcardMatch):
            pattern = bind(params, name, token.pattern)
            clauses.append(f"LOWER({column}) LIKE LOWER({pattern}) ESCAPE '\\'")
        elif isinstance(token, RangeMatch):
            if token.values is not None:
                refs = [bind(params, f"{name}_{i}", value.lower()) for i, value in enumerate(token.values)]
                clauses.append(f"LOWER({column}) IN ({', '.join(refs)})")
            else:
                parts = []
                if token.prefix:
                    prefix_ref = bind(params, f"{name}_prefix", escape_like(token.prefix) + "%")
                    parts.append(f"LOWER({column}) LIKE LOWER({prefix_ref}) ESCAPE '\\'")
                if token.padding > 0:
                    parts.append(f"LENGTH({column}) = {bind(params, f'{name}_length', len(token.prefix) + token.padding)}")
                position = bind(params, f"{name}_position", len(token.prefix) + 1)
                low = bind(params, f"{name}_start", token.start)
                high = bind(params, f"{name}_end", token.end)
                parts.append(f"CAST(SUBSTR({column}, {position}) AS INTEGER) BETWEEN {low} AND {high}")
                clauses.append(f"({' AND '.join(parts)})")
    return f"{column} IS NOT NULL AND ({' OR '.join(clauses)})" if clauses else "FALSE"
