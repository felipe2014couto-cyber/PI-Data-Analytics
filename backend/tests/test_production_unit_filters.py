from datetime import datetime, timezone
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError
from app.api.production_units import ProductionUnitAnalysisRequest
from app.models.pi_tag import PiTagDataType
from app.services.production_unit_filters import build_filter_state_intervals, merge_coverage
from app.services.production_unit_service import MAX_ANALYSIS_TAGS, MAX_FILTER_TAGS, MAX_PERIOD_DAYS, MAX_UM_SEGMENTS, ProductionUnitService
from app.schemas.pi import AnalysisFilterRequest
from app.schemas.production_unit import ProductionUnitFilterConfiguration, ProductionUnitFilterRule


def ts(minute: int):
    return datetime(2026, 10, 2, 10, minute, tzinfo=timezone.utc)


def state(minute: int, value: str, *, good=True, questionable=False, substituted=False):
    return {"tag_id": 90, "ts": ts(minute), "value_text": value, "value_double": None,
            "value_boolean": None, "good": good, "questionable": questionable, "substituted": substituted}


def test_state_seed_and_transition_form_half_open_intervals():
    events = [state(0, "A"), state(5, "B")]
    intervals = build_filter_state_intervals(
        events, {90: [(ts(3), ts(9))]}, ts(3), ts(9),
    )
    assert [(item["start_ts"], item["end_ts"], item["value_text"]) for item in intervals] == [
        (ts(3).isoformat(), ts(5).isoformat(), "A"),
        (ts(5).isoformat(), ts(9).isoformat(), "B"),
    ]


def test_empty_confirmed_coverage_allows_seed_state_until_transition():
    intervals = build_filter_state_intervals([state(0, "A")], {90: [(ts(3), ts(9))]}, ts(3), ts(9))
    assert len(intervals) == 1
    assert intervals[0]["value_text"] == "A"
    assert intervals[0]["end_ts"] == ts(9).isoformat()


def test_state_does_not_cross_uncovered_interval_or_resume_without_new_event():
    intervals = build_filter_state_intervals(
        [state(0, "A"), state(7, "B")], {90: [(ts(0), ts(4)), (ts(6), ts(9))]}, ts(0), ts(9),
    )
    assert [(item["start_ts"], item["end_ts"], item["value_text"]) for item in intervals] == [
        (ts(0).isoformat(), ts(4).isoformat(), "A"),
        (ts(7).isoformat(), ts(9).isoformat(), "B"),
    ]


def test_bad_questionable_substituted_and_null_states_break_asof_value():
    events = [state(0, "A"), state(2, "BAD", good=False), state(4, "Q", questionable=True),
              state(6, "S", substituted=True), {**state(8, ""), "value_text": None}]
    intervals = build_filter_state_intervals(events, {90: [(ts(0), ts(9))]}, ts(0), ts(9))
    assert [(item["start_ts"], item["end_ts"], item["value_text"]) for item in intervals] == [
        (ts(0).isoformat(), ts(2).isoformat(), "A"),
    ]


def test_coverage_rows_merge_adjacent_complete_and_empty_intervals():
    rows = [SimpleNamespace(tag_id=90, range_start=ts(0), range_end=ts(3)),
            SimpleNamespace(tag_id=90, range_start=ts(3), range_end=ts(8))]
    assert merge_coverage(rows, {90}) == {90: [(ts(0), ts(8))]}


def test_sql_compiler_preserves_numeric_bounds_zero_negative_and_multiple_rule_and_semantics():
    rules = [
        (ProductionUnitFilterRule(id="width", kind="numeric", tag_id=30, operator="between", value=0, second_value=1.25), 30),
        (ProductionUnitFilterRule(id="offset", kind="numeric", tag_id=30, operator="greaterThanOrEqual", value=-2.0), 30),
        (ProductionUnitFilterRule(id="steel", kind="text", tag_id=80, operator="wildcard", value="AISI304;P4*", case_sensitive=False), 80),
    ]
    sql, params = ProductionUnitService._compile_filters(
        SimpleNamespace(id=5), [], {30: "fs0", 80: "fs1"}, rules, [],
        ProductionUnitFilterConfiguration(filters_enabled=True),
    )
    assert "p.value_double BETWEEN" in sql
    assert "fs0.value_double BETWEEN" in sql
    assert "OR" in sql and "AND" in sql
    assert 0.0 in params.values() and 1.25 in params.values() and -2.0 in params.values()
    assert "p.good IS TRUE" in sql


def test_dynamic_string_and_digital_sql_reuse_existing_expression_semantics():
    sql, params = ProductionUnitService._compile_filters(
        SimpleNamespace(id=5), [], {80: "fs0", 81: "fs1", 82: "fs2"}, [],
        [(AnalysisFilterRequest(variable_type_id=7, expression="P409A;P4*"), 80, "STRING"),
         (AnalysisFilterRequest(variable_type_id=8, value="OFF"), 81, "DIGITAL"),
         (AnalysisFilterRequest(variable_type_id=9, expression="ON"), 82, "DIGITAL")],
        ProductionUnitFilterConfiguration(filters_enabled=True),
    )
    assert "LOWER(COALESCE(fs0.value_text" in sql
    assert "fs1.value_boolean IS FALSE" in sql
    assert "fs2.value_boolean IS TRUE" in sql
    assert "P409A" in params.values()
    assert "P4%" in params.values()


def test_filter_on_only_selected_series_uses_its_samples_without_asof_state_join():
    sql, params = ProductionUnitService._compile_filters(
        SimpleNamespace(id=5), [SimpleNamespace(id=20)], {},
        [(ProductionUnitFilterRule(id="speed", kind="numeric", tag_id=20,
                                   operator="greaterThanOrEqual", value=0), 20)], [],
        ProductionUnitFilterConfiguration(filters_enabled=True),
    )
    assert "p.value_double >=" in sql
    assert "filter_states" not in sql
    assert 0.0 in params.values()


def test_endpoint_contract_accepts_current_filter_configuration_and_dynamic_filters():
    request = ProductionUnitAnalysisRequest.model_validate({
        "section_id": 5,
        "tag_ids": [20],
        "start_time": "2026-10-02T09:11:57Z",
        "end_time": "2026-10-02T09:59:21Z",
        "filterConfiguration": {"filtersEnabled": True, "rules": [{
            "id": "width", "kind": "numeric", "tagId": 30,
            "operator": "between", "value": 0, "secondValue": 1.25,
        }]},
        "analysisFilters": [{"variable_type_id": 2, "min": 1.1, "max": 1.3}],
    })
    assert request.filter_configuration.filters_enabled is True
    assert request.filter_configuration.rules[0].value == 0
    assert request.analysis_filters[0].variable_type_id == 2
    with pytest.raises(PydanticValidationError):
        ProductionUnitAnalysisRequest.model_validate({
            "section_id": 5, "tag_ids": list(range(1, MAX_ANALYSIS_TAGS + 2)),
            "start_time": "2026-10-02T09:11:57Z", "end_time": "2026-10-02T09:59:21Z",
        })


def test_service_enforces_period_and_filter_tag_limits_before_querying_samples():
    service = ProductionUnitService(None)
    start = ts(0)
    with pytest.raises(ValidationError, match="31 dias"):
        service.analyze(5, [20], start, start + timedelta(days=MAX_PERIOD_DAYS, seconds=1))

    rules = [ProductionUnitFilterRule(id=f"f-{tag_id}", kind="numeric", tag_id=tag_id,
                                      operator="greaterThanOrEqual", value=0)
             for tag_id in range(1, MAX_FILTER_TAGS + 2)]
    with pytest.raises(ValidationError, match="50 tags"):
        service._resolve_filter_plan(
            SimpleNamespace(id=5, equipment_id=1), [],
            ProductionUnitFilterConfiguration(filters_enabled=True, rules=rules), [],
        )


def test_service_enforces_500_um_segment_limit():
    from app.models.section import Section

    class FakeQuery:
        def __init__(self, rows): self.rows = rows
        def filter(self, *_args): return self
        def all(self): return self.rows

    class FakeResult:
        def mappings(self): return self
        def all(self): return events

    start = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(seconds=MAX_UM_SEGMENTS + 1)
    um_tag = SimpleNamespace(id=29, active=True, data_type=PiTagDataType.NON_NUMERIC)
    process_tag = SimpleNamespace(id=20, active=True, equipment_id=1, section_id=None,
                                  data_type=PiTagDataType.NUMERIC, pi_tag_name="speed",
                                  display_name="Speed", engineering_unit=None)
    events = [{"ts": start + timedelta(seconds=i), "value_text": f"UM-{i}",
               "value_double": None, "value_boolean": None, "good": True,
               "questionable": False, "substituted": False}
              for i in range(MAX_UM_SEGMENTS + 1)]

    class FakeDb:
        def get(self, model, _id):
            return SimpleNamespace(id=5, active=True, equipment_id=1, um_tag_id=29) if model is Section else um_tag
        def query(self, _model): return FakeQuery([process_tag])
        def execute(self, *_args, **_kwargs): return FakeResult()

    with pytest.raises(ValidationError, match="500 intervalos"):
        ProductionUnitService(FakeDb()).analyze(5, [20], start, end)
