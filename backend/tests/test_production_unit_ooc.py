from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api.production_units import ProductionUnitAnalysisRequest, analyze_production_units
from app.models import PiTag, PiTagDataType, VariableType, VariableFilterDataType
from app.services.production_unit_ooc import (
    ProductionUnitOocService, HistoricalLimitLookup, build_limit_state_intervals,
    classify_sample, eligible_recorded_sample, reliable_intervals,
)
from app.models.postgres import PiSample, PiIngestionCoverage
from tests.test_production_unit_service import make_um_scope

T = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)

def event(tag_id, minute, value, **quality):
    return dict(tag_id=tag_id, ts=T+timedelta(minutes=minute), value_double=value if isinstance(value, (int,float)) else None,
                value_text=value if isinstance(value, str) else None, value_boolean=None,
                good=quality.get('good',True), questionable=quality.get('questionable',False), substituted=quality.get('substituted',False))

@pytest.mark.parametrize('value,lower,upper,expected', [(0,0,10,True),(10,0,10,True),(11,0,10,False),(-1,-2,2,True),(None,0,10,None),('5',0,10,None),(True,0,10,None),(1,None,10,None),(1,0,None,None),(1,10,0,None),(float('nan'),0,10,None)])
def test_inclusive_bounds_and_ineligible_values(value, lower, upper, expected):
    assert classify_sample(value, lower, upper) is expected

@pytest.mark.parametrize('changes', [{'source_mode':'INTERPOLATED'},{'good':False},{'questionable':True},{'substituted':True},{'value_type':'string'},{'value_double':None},{'value_double':True},{'value_double':float('inf')}])
def test_ineligible_recorded_sample(changes):
    row = dict(source_mode='RECORDED',good=True,questionable=False,substituted=False,value_type='double',value_double=5)
    assert eligible_recorded_sample(row)
    assert not eligible_recorded_sample(dict(row, **changes))

def test_unreliable_seed_and_quality_transitions_are_not_carried_across_gaps():
    rows = [event(1,-5,0), event(1,3,0,good=False), event(1,4,0)]
    intervals = reliable_intervals(rows, {1:[(T-timedelta(minutes=6),T-timedelta(minutes=1)),(T,T+timedelta(minutes=10))]}, T,T+timedelta(minutes=10))
    assert [(row['start_ts'],row['end_ts']) for row in intervals] == [((T+timedelta(minutes=4)).isoformat(),(T+timedelta(minutes=10)).isoformat())]


def limit_lookup(events, *, coverage=None, start=T, end=T+timedelta(minutes=10)):
    if coverage is None:
        coverage = {1: [(T-timedelta(minutes=10), end)]}
    return HistoricalLimitLookup(build_limit_state_intervals(events, coverage, start, end))


def test_recorded_good_seed_is_loaded_before_window_and_retained_without_new_events(db_session):
    equipment, _ = make_um_scope(db_session)
    vt = VariableType(code='LIMITS', name='Limits', filter_data_type=VariableFilterDataType.REAL, active=True)
    db_session.add(vt)
    db_session.flush()
    tags = [PiTag(equipment_id=equipment.id, variable_type_id=vt.id, pi_server='PIMS',
                  pi_tag_name=name, display_name=name, data_type=PiTagDataType.NUMERIC, active=True)
            for name in ['OOC_LOWER', 'OOC_UPPER']]
    db_session.add_all(tags)
    db_session.flush()
    end = T+timedelta(minutes=10)
    for tag, value in zip(tags, [4, 10]):
        db_session.add(PiSample(tag_id=tag.id, ts=T-timedelta(minutes=5),
                                source_mode='RECORDED', value_type='double', value_double=value,
                                good=True, questionable=False, substituted=False))
        # A newer non-recorded value must never replace the recorded seed.
        db_session.add(PiSample(tag_id=tag.id, ts=T-timedelta(minutes=2),
                                source_mode='INTERPOLATED', value_type='double', value_double=900,
                                good=True, questionable=False, substituted=False))
        db_session.add_all([
            PiIngestionCoverage(tag_id=tag.id, range_start=T-timedelta(minutes=10), range_end=T,
                                mode='RECORDED', status='COMPLETE'),
            PiIngestionCoverage(tag_id=tag.id, range_start=T, range_end=end,
                                mode='RECORDED', status='EMPTY_CONFIRMED'),
        ])
    db_session.flush()
    ids = {tag.id for tag in tags}
    events, intervals = ProductionUnitOocService(db_session)._states(ids, T, end, ids)
    assert len(events) == 2
    lookups = [HistoricalLimitLookup([row for row in intervals if row['tag_id'] == tag.id]) for tag in tags]
    for minute in [0, 1, 3, 9]:
        values = [lookup.at(T+timedelta(minutes=minute))['value_double'] for lookup in lookups]
        assert values == [4, 10]
        assert classify_sample(7, *values) is True


def test_many_samples_between_limit_changes_retain_same_historical_value():
    lookup = limit_lookup([event(1, -1, 2), event(1, 5, 4)])
    for minute in [0, 1, 2, 3, 4, 4.99]:
        assert lookup.at(T+timedelta(minutes=minute))['value_double'] == 2


def test_new_limit_replaces_previous_value_at_its_exact_timestamp():
    lookup = limit_lookup([event(1, -1, 2), event(1, 5, 4)])
    assert lookup.at(T+timedelta(minutes=4.99))['value_double'] == 2
    for minute in [5, 6, 9]:
        assert lookup.at(T+timedelta(minutes=minute))['value_double'] == 4
    assert classify_sample(3, lookup.at(T+timedelta(minutes=6))['value_double'], 10) is False


@pytest.mark.parametrize('invalid', [event(1, 3, 4, good=False), event(1, 3, 'Timeout'),
                                   event(1, 3, None), event(1, 3, float('nan'))])
def test_invalid_limit_interrupts_eligibility_until_new_good(invalid):
    lookup = limit_lookup([event(1, -1, 2), invalid, event(1, 6, 4)])
    assert lookup.at(T+timedelta(minutes=2))['value_double'] == 2
    for minute in [3, 4, 5.99]:
        assert lookup.at(T+timedelta(minutes=minute)) is None
        assert classify_sample(7, None, 10) is None
    assert lookup.at(T+timedelta(minutes=6))['value_double'] == 4


def test_real_coverage_gap_does_not_reactivate_previous_limit_without_new_good():
    coverage = {1: [(T-timedelta(minutes=10), T+timedelta(minutes=3)),
                    (T+timedelta(minutes=5), T+timedelta(minutes=10))]}
    lookup = limit_lookup([event(1, -1, 2), event(1, 7, 4)], coverage=coverage)
    assert lookup.at(T+timedelta(minutes=2))['value_double'] == 2
    for minute in [3, 4, 5, 6]:
        assert lookup.at(T+timedelta(minutes=minute)) is None
    assert lookup.at(T+timedelta(minutes=7))['value_double'] == 4
    seeded_after_gap = limit_lookup([event(1, -1, 2)], coverage=coverage, start=T+timedelta(minutes=5))
    assert seeded_after_gap.at(T+timedelta(minutes=6)) is None


def test_no_previous_good_limit_remains_ineligible_until_first_good():
    lookup = limit_lookup([event(1, 3, 4)])
    assert lookup.at(T) is None
    assert lookup.at(T+timedelta(minutes=3))['value_double'] == 4


def test_limit_lookup_orders_mixed_offsets_by_instant_not_iso_text():
    offset = timezone(timedelta(hours=-3))
    lookup = HistoricalLimitLookup([
        dict(start_ts=T.isoformat(), end_ts=(T+timedelta(minutes=5)).isoformat(), value_double=2),
        dict(start_ts=(T+timedelta(minutes=5)).astimezone(offset).isoformat(), end_ts=(T+timedelta(minutes=10)).isoformat(), value_double=4),
    ])
    assert lookup.at(T+timedelta(minutes=1))['value_double'] == 2
    assert lookup.at(T+timedelta(minutes=6))['value_double'] == 4

def test_existing_unit_endpoint_ooc_historical_bounds_occurrences_and_null(db_session, monkeypatch):
    equipment, add_um = make_um_scope(db_session)
    um = add_um('UM_OOC')
    vt = VariableType(code='NUM',name='Numeric',filter_data_type=VariableFilterDataType.REAL,active=True)
    db_session.add(vt); db_session.flush()
    def tag(name):
        obj = PiTag(equipment_id=equipment.id,variable_type_id=vt.id,pi_server='PIMS',pi_tag_name=name,display_name=name,data_type=PiTagDataType.NUMERIC,active=True)
        db_session.add(obj); db_session.flush(); return obj
    lower, upper, process = tag('LOWER'),tag('UPPER'),tag('SPEED')
    process.lower_limit_tag, process.upper_limit_tag = lower.pi_tag_name, upper.pi_tag_name
    db_session.flush()
    events = [event(um.id,0,'600515A3000B'),event(um.id,5,'600436J8000B'),event(um.id,10,'600515A3000B'),event(lower.id,0,0),event(upper.id,0,10),event(lower.id,2,5),event(upper.id,4,10,good=False),event(upper.id,5,20),event(upper.id,10,20,questionable=True)]
    end = T+timedelta(minutes=15)
    coverage = {id:[(T,end)] for id in [um.id,lower.id,upper.id]}
    intervals = reliable_intervals(events, coverage,T,end)
    monkeypatch.setattr(ProductionUnitOocService,'_states',lambda *args:(events,intervals))
    def sample(minute,value,**changes):
        return dict(dict(tag_id=process.id,ts=T+timedelta(minutes=minute),value_double=value,source_mode='RECORDED',value_type='double',good=True,questionable=False,substituted=False),**changes)
    rows = [sample(0,0),sample(1,10),sample(2,4),sample(3,5),sample(4,5),sample(5,20),sample(6,21),sample(7,None),sample(8,5,good=False),sample(9,10,substituted=True),sample(10,10),sample(15,10)]
    # Mock only the PostgreSQL streaming query; ORM metadata still comes from
    # the isolated fixture DB. Assert production SQL enforces the raw source.
    original = db_session.execute
    def execute(statement,*args,**kwargs):
        if str(statement).lstrip().startswith('WITH tags AS'):
            sql = str(statement)
            assert "p.source_mode='RECORDED'" in sql
            assert 'AND p.good AND NOT p.questionable AND NOT p.substituted' in sql
            assert 'p.ts < :end' in sql
            return SimpleNamespace(mappings=lambda: iter(rows))
        return original(statement,*args,**kwargs)
    monkeypatch.setattr(db_session,'execute',execute)
    request = ProductionUnitAnalysisRequest(equipment_id=equipment.id,tag_ids=[process.id,um.id],start_time=T,end_time=end,analysis_rule='OOC')
    response = analyze_production_units(request,db_session)
    assert response.strategy == 'production_unit_ooc_recorded_runtime'
    assert [s.um_value for s in response.segments] == ['600515A3000B','600436J8000B','600515A3000B']
    assert [(s.variables[0].attended_sample_count,s.variables[0].eligible_sample_count,s.variables[0].attended_percent) for s in response.segments] == [(3,4,75),(1,2,50),(0,0,None)]
    assert response.segments[0].segment_id != response.segments[2].segment_id
    assert all(len(s.variables)==1 for s in response.segments)

@pytest.mark.parametrize('rule',[None,'MEDIA','MIN','MAXIMO'])
def test_other_unit_metrics_keep_existing_service_path(rule, monkeypatch):
    old = Mock(return_value='existing result')
    monkeypatch.setattr('app.api.production_units.ProductionUnitService.analyze',old)
    request = ProductionUnitAnalysisRequest(equipment_id=1,tag_ids=[2],start_time=T,end_time=T+timedelta(minutes=5),analysis_rule=rule)
    assert analyze_production_units(request,Mock()) == 'existing result'
    old.assert_called_once()
