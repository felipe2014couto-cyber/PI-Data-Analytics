"""SIP SELECT validation, Oracle transaction guard, and chart integration."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models import Equipment, VariableType
from app.services.sip_oracle_service import SipOracleService, validated_select


@pytest.mark.parametrize("sql", [
    "DELETE FROM MEDICOES",
    "UPDATE MEDICOES SET VALUE = 1",
    "INSERT INTO MEDICOES VALUES (1)",
    "DROP TABLE MEDICOES",
    "SELECT * FROM MEDICOES FOR UPDATE",
    "SELECT * FROM MEDICOES; DELETE FROM MEDICOES",
    "SELECT DBMS_LOCK.SLEEP(5) FROM DUAL",
    "SELECT MY_PACKAGE.MY_FUNCTION() FROM DUAL",
    "SELECT SEQ.NEXTVAL FROM DUAL",
    "SELECT * FROM HISTORICOS_UM@REMOTE",
])
def test_sip_rejects_write_or_external_calls(sql):
    with pytest.raises(ValidationError):
        validated_select(sql)


def test_sip_accepts_single_select():
    assert validated_select("SELECT DATA_HORA AS TS, VALOR AS PV FROM MEDICOES")


@pytest.mark.parametrize("function", [
    "TRUNC(SYSDATE)",
    "TO_TIMESTAMP('2026-09-23', 'YYYY-MM-DD')",
    "REGEXP_SUBSTR(CODIGO, '[A-Z]+')",
    "NUMTODSINTERVAL(14, 'MINUTE')",
])
def test_sip_accepts_safe_oracle_read_functions(function):
    assert validated_select(f"SELECT {function} AS VALUE FROM DUAL")


def test_sip_accepts_literal_at_sign_in_value():
    sql = "SELECT SYSDATE AS TS, CODIGO || '@' || VALOR AS PI_VALUE FROM HISTORICOS_UM"
    assert "'@'" in validated_select(sql)


def test_sip_accepts_historicos_um_query_with_interval_and_literal_at():
    sql = """SELECT
        (DTH_FIM_PROCE - NUMTODSINTERVAL(14, 'MINUTE')) + NUMTODSINTERVAL(
            (ROW_NUMBER() OVER (PARTITION BY DTH_FIM_PROCE ORDER BY COD_IDENT_UNMET ASC) - 1) * 14,
            'MINUTE'
        ) AS TS,
        COD_IDENT_UNMET || '@' || COM_REAL_UNMET AS PI_VALUE,
        0 AS STATUS
    FROM ACECPGER_ACI.HISTORICOS_UM
    WHERE DTH_INIC_PROCE >= SYSDATE - 2
      AND COD_EQPMT_PRODC = 'LC1'
    ORDER BY TS DESC, COD_IDENT_UNMET DESC;"""
    normalized = validated_select(sql)
    assert "NUMTODSINTERVAL" in normalized
    assert "'@'" in normalized
    assert "ACECPGER_ACI.HISTORICOS_UM" in normalized


def test_sip_rejects_unrecognized_function():
    with pytest.raises(ValidationError, match="MALICIOUS_FUNCTION"):
        validated_select("SELECT MALICIOUS_FUNCTION() FROM DUAL")


class FakeCursor:
    description = [("TS",), ("PV",)]

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return [(datetime(2026, 1, 1, 9), Decimal("12.5"))]


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.autocommit = True
        self.call_timeout = None
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_sip_read_only_transaction_and_bounded_period():
    connection = FakeConnection()
    config = settings.model_copy(update={
        "sip_oracle_username": "readonly",
        "sip_oracle_password": SecretStr("test"),
        "sip_oracle_max_rows": 10,
    })
    service = SipOracleService(config=config, connection_factory=lambda: connection)
    rows, truncated = service.fetch_rows(
        "SELECT DATA_HORA AS TS, VALOR AS PV FROM MEDICOES",
        "TS", "PV",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert connection.autocommit is False
    assert connection.cursor_instance.calls[0][0] == "SET TRANSACTION READ ONLY"
    assert ":sip_start" in connection.cursor_instance.calls[2][0]
    assert connection.cursor_instance.calls[2][1]["sip_limit"] == 11
    assert rows[0][1] == 12.5
    assert rows[0][0] == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert not truncated
    assert connection.rolled_back and connection.closed


def test_sip_catalog_and_chart_endpoint(client, db_session, monkeypatch):
    import app.api.sip as sip_api
    import app.services.database_time_series_service as time_series_module

    equipment = Equipment(code="SIP1", name="SIP Equipment", active=True)
    variable_type = VariableType(code="SIP_TEMP", name="SIP Temperature", active=True)
    db_session.add_all([equipment, variable_type])
    db_session.commit()
    monkeypatch.setattr(sip_api.SipOracleService, "inspect_columns", lambda _self, _sql: ["TS", "PV"])
    response = client.post("/api/sip/sources", json={
        "equipment_id": equipment.id,
        "section_id": None,
        "variable_type_id": variable_type.id,
        "name": "Temperatura SIP",
        "sql_text": "SELECT DATA_HORA AS TS, VALOR AS PV FROM MEDICOES",
        "timestamp_column": "TS",
        "value_column": "PV",
        "active": True,
    })
    assert response.status_code == 201, response.text
    source_id = response.json()["id"]
    assert client.get("/api/sip/sources").json()[0]["id"] == source_id

    monkeypatch.setattr(time_series_module, "SipOracleService", lambda: SimpleNamespace(
        fetch_rows=lambda *_args: ([(datetime(2026, 1, 1, 12, tzinfo=timezone.utc), 12.5)], False)
    ))
    result = client.get("/api/time-series", params={
        "tag_ids": -source_id,
        "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-02T00:00:00Z",
        "mode": "recorded",
    })
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["series"][0]["tag_id"] == -source_id
    assert body["series"][0]["points"][0]["value"] == 12.5
    assert body["query_execution"]["source"] == "sip"

    write = client.post("/api/sip/columns", json={"sql_text": "DELETE FROM MEDICOES"})
    assert write.status_code == 422
