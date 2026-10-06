"""Acquisition then HTTP graph reads: PI is forbidden after materialization.

Uses the canonical TimescaleDB ORM tables on the official isolated SQLite test
database. Real TimescaleDB requests are separately audited in read-only mode.
"""
import asyncio
from datetime import timedelta
from unittest.mock import Mock

from app.api import deps
from app.integrations.pi import manager
from app.integrations.pi.webapi_provider import PiWebApiDataProvider
from app.models.postgres import PiSample
from app.services.coverage_service import CoverageService
from app.services.pi_norm_limits_service import PiNormLimitsService
from app.services import norm_limit_reload_service as reload_service
from tests.conftest import TestingSessionLocal
from tests.test_norm_limit_reload_service import START, Provider, _point, _source


def test_materialized_graph_and_overlay_http_routes_never_resolve_or_call_pi(client, db_session, monkeypatch):
    end = START + timedelta(days=7)
    source = _source(db_session, 'MATERIALIZED-HTTP', 'HTTP-LOW', 'HTTP-UP')
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
    for method in ('resolve_point','get_recorded_values','get_recorded_values_boundary','get_interpolated_values','_request'):
        if hasattr(PiWebApiDataProvider, method):
            monkeypatch.setattr(PiWebApiDataProvider, method, forbidden)
    # Exercise the production dependency without the fixture's provider wiring.
    client.app.dependency_overrides[deps.get_norm_limits_service] = lambda: PiNormLimitsService(session_factory=TestingSessionLocal)
    params={'start_time':START.isoformat(),'end_time':end.isoformat(),'mode':'recorded'}
    principal = client.get('/api/time-series', params={**params,'tag_ids':[source.id],'refresh':True})
    assert principal.status_code == 200, principal.text
    assert principal.json()['query_execution']['source'] == 'timescaledb'
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
