"""Acquisition then HTTP graph reads: PI is forbidden after materialization.

Uses the canonical TimescaleDB ORM tables on the official isolated SQLite test
database. Real TimescaleDB requests are separately audited in read-only mode.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.api import deps
from app.integrations.pi import manager
from app.integrations.pi.webapi_provider import PiWebApiDataProvider
from app.models.postgres import PiIngestionCoverage, PiSample
from app.services.coverage_service import CoverageService
from app.services.pi_norm_limits_service import PiNormLimitsService
from app.services import norm_limit_reload_service as reload_service
from tests.conftest import TestingSessionLocal
from tests.test_norm_limit_reload_service import START, Provider, _point, _source


def test_materialized_graph_and_overlay_routes_never_resolve_or_call_pi(client, db_session, monkeypatch):
    end = START + timedelta(days=7)
    source = _source(db_session, 'MATERIALIZED-HTTP', 'HTTP-LOW', 'HTTP-UP')
    source.pi_web_id = 'step-must-not-be-fetched'
    db_session.commit()
    db_session.add_all([
        PiSample(tag_id=source.id, ts=START + timedelta(minutes=1), source_mode='RECORDED', value_type='double', value_double=30),
        PiSample(tag_id=source.id, ts=START + timedelta(minutes=2), source_mode='RECORDED', value_type='double', value_double=31),
    ])
    CoverageService.record_coverage(db_session, source.id, START, end)
    db_session.commit()
    monkeypatch.setattr(reload_service, 'SessionLocal', TestingSessionLocal)
    acquisition = Provider({
        'HTTP-LOW': [_point(-1,25), _point(10,26,substituted=True)],
        'HTTP-UP': [_point(-1,35)],
    })
    loaded = asyncio.run(reload_service.reload_norm_limits(provider=acquisition, now=end))
    assert all(row.status == 'COMPLETE' for row in loaded if row.tag_name in {'HTTP-LOW','HTTP-UP'})

    forbidden = Mock(side_effect=AssertionError('PI forbidden during graph read'))
    monkeypatch.setattr(deps, 'get_pi_data_provider', forbidden)
    monkeypatch.setattr(manager, 'get_pi_data_provider', forbidden)
    monkeypatch.setattr(manager.PiDataProviderManager, 'get', forbidden)
    # The graph route must not resolve the PI provider at all. Remove the
    # fixture's provider override so a reintroduced dependency fails here.
    client.app.dependency_overrides.pop(deps.get_pi_provider, None)
    for method in ('resolve_point','get_point_step','get_recorded_values','get_recorded_values_boundary','get_interpolated_values','_request'):
        if hasattr(PiWebApiDataProvider, method):
            monkeypatch.setattr(PiWebApiDataProvider, method, forbidden)
    # Exercise the production dependency without the fixture's provider wiring.
    client.app.dependency_overrides[deps.get_norm_limits_service] = lambda: PiNormLimitsService(session_factory=TestingSessionLocal)
    params={'start_time':START.isoformat(),'end_time':end.isoformat(),'mode':'recorded'}
    principal = client.get('/api/time-series', params={**params,'tag_ids':[source.id],'refresh':True})
    assert principal.status_code == 200, principal.text
    assert principal.json()['query_execution']['source'] == 'timescaledb'
    assert principal.json()['series'][0]['data_type'] == 'REAL'
    assert [p['value'] for p in principal.json()['series'][0]['points']] == [30,31]
    overlay = client.get(f'/api/pi-tags/{source.id}/norm-limits', params=params)
    assert overlay.status_code == 200, overlay.text
    assert [p['value'] for p in overlay.json()['lower']['points']] == [25,26]
    assert [p['value'] for p in overlay.json()['upper']['points']] == [35]
    assert overlay.json()['lower']['points'][1]['substituted'] is True
    assert overlay.json()['errors'] == []
    assert overlay.json()['lower']['coverage_gaps'] == []
    forbidden.assert_not_called()
    assert client.fake_provider.recorded_calls == []

    # Editing a configured reference cannot fetch or materialize the new tag.
    source.lower_limit_tag='HTTP-NOT-MATERIALIZED'
    db_session.commit()
    missing = client.get(f'/api/pi-tags/{source.id}/norm-limits', params=params)
    assert missing.status_code == 200
    assert missing.json()['lower']['points'] == []
    assert 'aguardando a próxima recarga histórica' in missing.json()['lower']['error']
    assert 'Não foi possível consultar os limites de norma' not in missing.text
    assert [p['value'] for p in missing.json()['upper']['points']] == [35]
    principal = client.get('/api/time-series', params={**params,'tag_ids':[source.id],'refresh':True})
    assert principal.status_code == 200
    forbidden.assert_not_called()


def test_incremental_tail_is_immediately_visible_from_timescaledb_without_pi(client, db_session, monkeypatch):
    source = _source(db_session, 'INCREMENTAL-HTTP', 'INCREMENTAL-HTTP-LOW')
    limit_id = reload_service._register_dependency(
        db_session,
        {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
        "INCREMENTAL-HTTP-LOW", "web-INCREMENTAL-HTTP-LOW",
    )
    db_session.add(PiSample(
        tag_id=limit_id, ts=START + timedelta(minutes=1), source_mode='RECORDED',
        value_type='double', value_double=40, good=True,
    ))
    CoverageService.record_coverage(db_session, limit_id, START, START + timedelta(minutes=2))
    db_session.commit()
    monkeypatch.setattr(reload_service, 'SessionLocal', TestingSessionLocal)

    now = START + timedelta(minutes=3, seconds=15)
    acquisition = Provider({'INCREMENTAL-HTTP-LOW': [_point(1, 40), _point(2, 41)]})
    result = asyncio.run(reload_service.reload_norm_limits_incremental(provider=acquisition, now=now))
    assert len(result) == 1 and result[0].status == 'COMPLETE'
    assert result[0].start == START + timedelta(minutes=2)
    assert result[0].end == START + timedelta(minutes=3)
    assert result[0].pi_calls == 1

    forbidden = Mock(side_effect=AssertionError('PI forbidden during graph read'))
    monkeypatch.setattr(deps, 'get_pi_data_provider', forbidden)
    client.app.dependency_overrides.pop(deps.get_pi_provider, None)
    client.app.dependency_overrides[
        deps.get_norm_limits_service
    ] = lambda: PiNormLimitsService(session_factory=TestingSessionLocal)
    params = {
        'start_time': (START + timedelta(minutes=2)).isoformat(),
        'end_time': (START + timedelta(minutes=3)).isoformat(),
        'mode': 'recorded',
    }
    response = client.get(f'/api/pi-tags/{source.id}/norm-limits', params=params)
    assert response.status_code == 200, response.text
    assert [point['value'] for point in response.json()['lower']['points']] == [40, 41]
    assert response.json()['lower']['points'][-1]['good'] is True
    forbidden.assert_not_called()


def test_incremental_repairs_sampled_coverage_gap_and_overlay_warning_disappears(client, db_session, monkeypatch):
    source = _source(db_session, 'GAP-HTTP', 'GAP-HTTP-LOW')
    limit_id = reload_service._register_dependency(
        db_session,
        {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
        "GAP-HTTP-LOW", "web-GAP-HTTP-LOW",
    )
    db_session.add(PiSample(
        tag_id=limit_id, ts=START + timedelta(minutes=1, seconds=30), source_mode='RECORDED',
        value_type='double', value_double=55, good=True,
    ))
    CoverageService.record_coverage(db_session, limit_id, START, START + timedelta(minutes=1))
    CoverageService.record_coverage(db_session, limit_id, START + timedelta(minutes=2), START + timedelta(minutes=3))
    from app.models.postgres import PiIngestionState
    db_session.add(PiIngestionState(
        tag_id=limit_id, source_mode='NORM_LIMIT', watermark_ts=START + timedelta(minutes=3),
    ))
    db_session.commit()
    monkeypatch.setattr(reload_service, 'SessionLocal', TestingSessionLocal)

    forbidden = Mock(side_effect=AssertionError('PI forbidden during graph read'))
    monkeypatch.setattr(deps, 'get_pi_data_provider', forbidden)
    monkeypatch.setattr(manager, 'get_pi_data_provider', forbidden)
    monkeypatch.setattr(manager.PiDataProviderManager, 'get', forbidden)
    client.app.dependency_overrides.pop(deps.get_pi_provider, None)
    client.app.dependency_overrides[
        deps.get_norm_limits_service
    ] = lambda: PiNormLimitsService(session_factory=TestingSessionLocal)
    params = {
        'start_time': START.isoformat(),
        'end_time': (START + timedelta(minutes=3)).isoformat(),
        'mode': 'recorded',
    }

    before = client.get(f'/api/pi-tags/{source.id}/norm-limits', params=params)
    assert before.status_code == 200, before.text
    assert len(before.json()['lower']['coverage_gaps']) == 1
    assert any('Cobertura RECORDED pendente' in error for error in before.json()['errors'])
    forbidden.assert_not_called()

    acquisition = Provider({'GAP-HTTP-LOW': [_point(1.5, 55)]})
    result = asyncio.run(reload_service.reload_norm_limits_incremental(
        provider=acquisition, now=START + timedelta(minutes=3, seconds=20),
    ))
    assert result[0].status == 'COMPLETE'
    assert result[0].pi_calls == 1
    assert acquisition.ranges == [(
        'Inside', START + timedelta(minutes=1), START + timedelta(minutes=2),
    )]
    with TestingSessionLocal() as db:
        assert db.query(PiSample).filter_by(tag_id=limit_id).count() == 1
        coverage = db.query(PiIngestionCoverage).filter_by(tag_id=limit_id).one()
        assert coverage.range_start.replace(tzinfo=START.tzinfo) == START
        assert coverage.range_end.replace(tzinfo=START.tzinfo) == START + timedelta(minutes=3)
        assert coverage.status == 'COMPLETE'

    response = client.get(f'/api/pi-tags/{source.id}/norm-limits', params=params)
    assert response.status_code == 200, response.text
    assert response.json()['errors'] == []
    assert response.json()['lower']['coverage_gaps'] == []
    forbidden.assert_not_called()


def test_old_unmaterialized_history_is_diagnostic_only_when_requested(client, db_session, monkeypatch):
    source = _source(db_session, 'OLD-HISTORY-HTTP', 'OLD-HISTORY-LOW')
    limit_id = reload_service._register_dependency(
        db_session,
        {"equipment_id": source.equipment_id, "variable_type_id": source.variable_type_id, "pi_server": "PIMS"},
        'OLD-HISTORY-LOW', 'web-OLD-HISTORY-LOW',
    )
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    recent_start = now - timedelta(hours=2)
    db_session.add(PiSample(
        tag_id=limit_id, ts=now - timedelta(hours=1), source_mode='RECORDED',
        value_type='double', value_double=-999, good=True,
    ))
    CoverageService.record_coverage(db_session, limit_id, recent_start, now)
    db_session.commit()
    monkeypatch.setattr(reload_service, 'SessionLocal', TestingSessionLocal)
    client.app.dependency_overrides[
        deps.get_norm_limits_service
    ] = lambda: PiNormLimitsService(session_factory=TestingSessionLocal)

    recent = client.get(
        f'/api/pi-tags/{source.id}/norm-limits',
        params={
            'start_time': recent_start.isoformat(),
            'end_time': now.isoformat(),
            'mode': 'recorded',
        },
    )
    assert recent.status_code == 200, recent.text
    assert recent.json()['lower']['coverage_gaps'] == []
    assert not any('backfill manual necessário' in error for error in recent.json()['errors'])
    assert [point['value'] for point in recent.json()['lower']['points']] == [-999]

    old_start = now - timedelta(days=30)
    old_end = now - timedelta(days=29)
    historical = client.get(
        f'/api/pi-tags/{source.id}/norm-limits',
        params={
            'start_time': old_start.isoformat(),
            'end_time': old_end.isoformat(),
            'mode': 'recorded',
        },
    )
    assert historical.status_code == 200, historical.text
    assert historical.json()['lower']['coverage_gaps']
    assert any('histórico' in error.lower() and 'backfill manual necessário' in error.lower()
               for error in historical.json()['errors'])
    assert not any('aguardando a próxima recarga histórica' in error.lower()
                   for error in historical.json()['errors'])
    assert 'Não foi possível consultar os limites de norma' not in historical.text
