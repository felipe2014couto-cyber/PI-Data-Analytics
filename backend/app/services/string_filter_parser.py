"""String filter expression parser for PI data analysis.

Parses filter expressions into an Abstract Syntax Tree (AST) representing
disjunctive (OR) conditions. Supports:
- Exact matches: "P99"
- Wildcards: "P*", "*99", "*99*", "ABC*XYZ"
- Disjunctions: "P99;P100;ABC*"
- Embedded numeric ranges: "P1:P100", "ABC001:ABC050", "P100:P1"
- Range + values: "P1:P100;P150"

All matches are conceptually case-insensitive.
This module only produces AST and validation errors; SQL generation is
delegated to the query service.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Union

from app.core.exceptions import ValidationError

MAX_RANGE_COUNT = 10_000
SMALL_RANGE_THRESHOLD = 50


@dataclass(frozen=True)
class ExactMatch:
    value: str


@dataclass(frozen=True)
class WildcardMatch:
    pattern: str  # Pattern with SQL-like wildcards (%) and escaped characters


@dataclass(frozen=True)
class RangeMatch:
    prefix: str
    start: int
    end: int
    padding: int
    count: int
    values: Optional[List[str]] = None


ASTNode = Union[ExactMatch, WildcardMatch, RangeMatch]


_DIGIT_SUFFIX_REGEX = re.compile(r"^(.*?)(\d+)$")


def _escape_sql_like(text: str) -> str:
    """Escape SQL LIKE special characters %, _ and \\ before converting * to %."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%")


def _parse_range_token(token: str) -> RangeMatch:
    """Parse a range token like P1:P100 or ABC001:ABC050."""
    parts = token.split(":")
    if len(parts) != 2:
        raise ValidationError("Intervalo inválido.")

    left, right = parts[0].strip(), parts[1].strip()
    if not left or not right:
        raise ValidationError("Intervalo incompleto.")

    left_match = _DIGIT_SUFFIX_REGEX.match(left)
    right_match = _DIGIT_SUFFIX_REGEX.match(right)

    if not left_match or not right_match:
        raise ValidationError("Intervalo inválido: ambas as extremidades devem conter parte numérica.")

    left_prefix, left_digits = left_match.group(1), left_match.group(2)
    right_prefix, right_digits = right_match.group(1), right_match.group(2)

    # Prefixes must be identical (case-insensitive comparison, preserve left prefix casing)
    if left_prefix.upper() != right_prefix.upper():
        raise ValidationError(
            "Intervalo inválido: os prefixos das duas extremidades devem ser iguais."
        )

    n1 = int(left_digits)
    n2 = int(right_digits)

    # Normalize inverted ranges (e.g. P100:P1 -> P1:P100)
    start = min(n1, n2)
    end = max(n1, n2)
    count = end - start + 1

    if count > MAX_RANGE_COUNT:
        raise ValidationError(
            f"Intervalo muito grande ({count} valores). O limite máximo é de {MAX_RANGE_COUNT} valores por intervalo."
        )

    # Zero-padding preservation: if either end had leading zeros (e.g. "001"),
    # preserve formatting width
    padding = 0
    if left_digits.startswith("0") or right_digits.startswith("0"):
        padding = max(len(left_digits), len(right_digits))

    prefix = left_prefix
    values: Optional[List[str]] = None
    if count <= SMALL_RANGE_THRESHOLD:
        if padding > 0:
            values = [f"{prefix}{i:0{padding}d}" for i in range(start, end + 1)]
        else:
            values = [f"{prefix}{i}" for i in range(start, end + 1)]

    return RangeMatch(
        prefix=prefix,
        start=start,
        end=end,
        padding=padding,
        count=count,
        values=values,
    )


def parse_string_filter(expression: str) -> List[ASTNode]:
    """Parse a string filter expression into an AST of match nodes.

    Multiple values separated by ';' are treated as OR conditions.
    Whitespace around tokens is stripped. Empty tokens are ignored.
    """
    if not expression or not expression.strip():
        return []

    # Split by semicolon (OR disjunction)
    raw_tokens = [tok.strip() for tok in expression.split(";")]
    tokens = [tok for tok in raw_tokens if tok]

    if not tokens:
        return []

    ast: List[ASTNode] = []
    for token in tokens:
        if ":" in token:
            ast.append(_parse_range_token(token))
        elif "*" in token:
            pattern = _escape_sql_like(token)
            ast.append(WildcardMatch(pattern=pattern))
        else:
            ast.append(ExactMatch(value=token))

    return ast
