"""SIP reload persists complete periods and scalar tags require no timestamp."""
import asyncio
from datetime import datetime, timedelta, timezone

from app.models import Equipment, SipSource, VariableType
from app.schemas.pi import TimeSeriesRequest
from app.services.database_time_series_service import DatabaseTimeSeriesService
from app.services.sip_oracle_service import SipOracleService, period_sql
from app.services.sip_reload_service import enqueue, has_coverage, process_next, stored_rows


START = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def test_period_sql_replaces_fixed_sysdate_bound():
    sql = "SELECT DTH_FIM_PROCE AS TS, VALOR AS PV FROM T WHERE DTH_INIC_PROCE >= SYSDATE - 2"
    transformed = period_sql(sql)
    assert "DTH_INIC_PROCE >= :sip_start - NUMTODSINTERVAL(2, 'DAY')" in transformed
    assert "SYSDATE - 2" not in transformed


def test_sip_reload_persists_and_chart_reads_cache(db_session, monkeypatch):
    equipment = Equipment(code="SIP_CACHE", name="SIP Cache", active=True)
    variable = VariableType(code="SIP_CACHE_V", name="SIP Cache Value", active=True)
    db_session.add_all([equipment, variable]); db_session.commit()
    source = SipSource(equipment_id=equipment.id, variable_type_id=variable.id, section_id=None,
        name="SIP cache", sql_text="SELECT TS, PV FROM T", timestamp_column="TS",
        value_column="PV", active=True)
    db_session.add(source); db_session.commit()
    calls = []
    def fake_fetch(_service, sql, ts, value, start, end):
        calls.append((sql, start, end))
        return ([(START + timedelta(minutes=5), "Aço P49"), (START + timedelta(minutes=10), 12.5)], False)
    monkeypatch.setattr(SipOracleService, "fetch_rows", fake_fetch)
    job = enqueue(db_session, source.id, START, END)
    assert process_next(db_session)
    db_session.refresh(job)
    assert job.status == "COMPLETED" and job.rows_written == 2
    assert has_coverage(db_session, source, START, END)
    assert len(stored_rows(db_session, source.id, START, END)) == 2
    assert len(calls) == 1
    monkeypatch.setattr(SipOracleService, "fetch_rows", lambda *_args: (_ for _ in ()).throw(AssertionError("Oracle called")))
    request = TimeSeriesRequest(tag_ids=[-source.id], start_time=START, end_time=END, mode="recorded")
    chart = asyncio.run(DatabaseTimeSeriesService(db_session).fetch_time_series(request))
    assert [point.value for point in chart.series[0].points] == ["Aço P49", 12.5]

    # A later full reload with no rows must clear the old samples in that chunk.
    monkeypatch.setattr(SipOracleService, "fetch_rows", lambda *_args: ([], False))
    second = enqueue(db_session, source.id, START, END)
    assert process_next(db_session)
    db_session.refresh(second)
    assert second.status == "COMPLETED" and second.rows_written == 0
    assert has_coverage(db_session, source, START, END)
    assert stored_rows(db_session, source.id, START, END) == []


def test_scalar_database_tag_has_no_timestamp(client, db_session, monkeypatch):
    import app.api.sip as sip_api
    equipment = Equipment(code="SIP_SCALAR", name="SIP Scalar", active=True)
    variable = VariableType(code="SIP_SCALAR_V", name="SIP Scalar Value", active=True)
    db_session.add_all([equipment, variable]); db_session.commit()
    monkeypatch.setattr(sip_api.SipOracleService, "inspect_columns", lambda _service, _sql: ["VALUE"])
    monkeypatch.setattr(sip_api.SipOracleService, "fetch_value", lambda _service, _sql, _column: 42)
    payload = {"equipment_id": equipment.id, "section_id": None, "variable_type_id": variable.id,
        "name": "Último lote", "sql_text": "SELECT 42 AS VALUE FROM DUAL",
        "value_column": "VALUE", "active": True}
    response = client.post("/api/sip/database-tags", json=payload)
    assert response.status_code == 201, response.text
    assert "timestamp_column" not in response.json()
    tag_id = response.json()["id"]
    assert client.get(f"/api/sip/database-tags/{tag_id}/value").json()["value"] == 42


def test_sip_reload_api_contract(client, db_session):
    equipment = Equipment(code="SIP_RELOAD_API", name="SIP Reload API", active=True)
    variable = VariableType(code="SIP_RELOAD_API_V", name="SIP Reload API Value", active=True)
    db_session.add_all([equipment, variable]); db_session.commit()
    source = SipSource(equipment_id=equipment.id, variable_type_id=variable.id, section_id=None,
        name="SIP API", sql_text="SELECT TS, PV FROM T", timestamp_column="TS",
        value_column="PV", active=True)
    db_session.add(source); db_session.commit()
    response = client.post("/api/admin/sip-reloads", json={
        "source_id": source.id, "start_time": START.isoformat(), "end_time": END.isoformat(),
    })
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    assert response.json()["status"] == "PENDING"
    assert any(item["id"] == job_id for item in client.get("/api/admin/sip-reloads").json())
    cancelled = client.post(f"/api/admin/sip-reloads/{job_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
