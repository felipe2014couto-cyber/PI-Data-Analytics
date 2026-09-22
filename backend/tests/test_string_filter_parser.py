"""Tests for string_filter_parser."""
import pytest

from app.core.exceptions import ValidationError
from app.services.string_filter_parser import (
    ExactMatch,
    RangeMatch,
    WildcardMatch,
    parse_string_filter,
)


def test_parse_exact():
    ast = parse_string_filter("P99")
    assert len(ast) == 1
    assert isinstance(ast[0], ExactMatch)
    assert ast[0].value == "P99"


def test_parse_exact_with_spaces():
    ast = parse_string_filter("  P99  ")
    assert len(ast) == 1
    assert ast[0] == ExactMatch(value="P99")


def test_parse_wildcard_suffix():
    ast = parse_string_filter("P*")
    assert len(ast) == 1
    assert isinstance(ast[0], WildcardMatch)
    assert ast[0].pattern == "P%"


def test_parse_wildcard_prefix():
    ast = parse_string_filter("*99")
    assert len(ast) == 1
    assert isinstance(ast[0], WildcardMatch)
    assert ast[0].pattern == "%99"


def test_parse_wildcard_both():
    ast = parse_string_filter("*99*")
    assert len(ast) == 1
    assert isinstance(ast[0], WildcardMatch)
    assert ast[0].pattern == "%99%"


def test_parse_multiple_values():
    ast = parse_string_filter("P99;P100")
    assert len(ast) == 2
    assert ast[0] == ExactMatch(value="P99")
    assert ast[1] == ExactMatch(value="P100")


def test_parse_multiple_wildcards():
    ast = parse_string_filter("ABC*;XYZ*")
    assert len(ast) == 2
    assert ast[0] == WildcardMatch(pattern="ABC%")
    assert ast[1] == WildcardMatch(pattern="XYZ%")


def test_parse_numeric_range():
    ast = parse_string_filter("P1:P100")
    assert len(ast) == 1
    assert isinstance(ast[0], RangeMatch)
    node = ast[0]
    assert node.prefix == "P"
    assert node.start == 1
    assert node.end == 100
    assert node.padding == 0
    assert node.count == 100
    assert node.values is None  # > 50 values, optimized for SQL BETWEEN


def test_parse_numeric_range_small():
    ast = parse_string_filter("P1:P5")
    assert len(ast) == 1
    node = ast[0]
    assert isinstance(node, RangeMatch)
    assert node.count == 5
    assert node.values == ["P1", "P2", "P3", "P4", "P5"]


def test_parse_range_plus_value():
    ast = parse_string_filter("P1:P100;P150")
    assert len(ast) == 2
    assert isinstance(ast[0], RangeMatch)
    assert ast[0].start == 1
    assert ast[0].end == 100
    assert ast[1] == ExactMatch(value="P150")


def test_parse_zero_padding_preservation():
    ast = parse_string_filter("ABC001:ABC010")
    assert len(ast) == 1
    node = ast[0]
    assert isinstance(node, RangeMatch)
    assert node.prefix == "ABC"
    assert node.start == 1
    assert node.end == 10
    assert node.padding == 3
    assert node.count == 10
    assert node.values == [
        "ABC001", "ABC002", "ABC003", "ABC004", "ABC005",
        "ABC006", "ABC007", "ABC008", "ABC009", "ABC010"
    ]


def test_parse_inverted_range_normalization():
    ast = parse_string_filter("P100:P1")
    assert len(ast) == 1
    node = ast[0]
    assert isinstance(node, RangeMatch)
    assert node.start == 1
    assert node.end == 100


def test_parse_prefix_mismatch_fails():
    with pytest.raises(ValidationError) as exc:
        parse_string_filter("P1:X100")
    assert "os prefixos das duas extremidades devem ser iguais" in str(exc.value)


def test_parse_incomplete_range_fails():
    with pytest.raises(ValidationError) as exc:
        parse_string_filter("P1:")
    assert "Intervalo incompleto" in str(exc.value)


def test_parse_only_colon_fails():
    with pytest.raises(ValidationError) as exc:
        parse_string_filter(":")
    assert "Intervalo incompleto" in str(exc.value)


def test_parse_empty_and_semicolons():
    assert parse_string_filter("") == []
    assert parse_string_filter("   ") == []
    assert parse_string_filter(";;") == []
    ast = parse_string_filter("P99;;P100;")
    assert len(ast) == 2
    assert ast[0] == ExactMatch(value="P99")
    assert ast[1] == ExactMatch(value="P100")


def test_parse_sql_injection_and_escapes():
    ast = parse_string_filter("100%_*")
    assert len(ast) == 1
    assert isinstance(ast[0], WildcardMatch)
    assert ast[0].pattern == r"100\%\_%"


def test_parse_range_limit_exceeded():
    with pytest.raises(ValidationError) as exc:
        parse_string_filter("P1:P20000")
    assert "Intervalo muito grande" in str(exc.value)
