"""Bounded, read-only access to the SIP Oracle database."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlglot
from sqlglot import exp

from app.core.config import Settings, settings
from app.core.exceptions import AppError, ValidationError


class SipUnavailableError(AppError):
    status_code = 503
    code = "SIP_UNAVAILABLE"


_UNSAFE_NODES = (exp.DML, exp.DDL, exp.Lock, exp.Into, exp.Command, exp.Transaction, exp.Dot)
# sqlglot represents some built-in Oracle read functions as Anonymous. Permit
# only known unqualified functions; package/user-defined calls stay blocked.
_SAFE_ORACLE_FUNCTIONS = frozenset({
    "ADD_MONTHS", "INSTR", "LAST_DAY", "LISTAGG", "LPAD", "LTRIM",
    "MONTHS_BETWEEN", "NUMTODSINTERVAL", "NVL2", "REGEXP_REPLACE", "REGEXP_SUBSTR",
    "REPLACE", "RPAD", "RTRIM", "SUBSTR", "TO_TIMESTAMP",
    "TO_TIMESTAMP_TZ", "TRUNC",
})


def validated_select(sql: str) -> str:
    """Return parser-generated Oracle SELECT, rejecting other statements and calls."""
    if not sql or len(sql) > 20000:
        raise ValidationError("Informe um SELECT com no máximo 20.000 caracteres.")
    try:
        statements = [item for item in sqlglot.parse(sql, read="oracle") if item is not None]
    except sqlglot.errors.SqlglotError as exc:
        raise ValidationError("SQL SIP inválido.") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise ValidationError("A consulta SIP deve conter apenas um SELECT.")
    tree = statements[0]
    if any(isinstance(node, _UNSAFE_NODES) for node in tree.walk()):
        raise ValidationError("A consulta SIP permite somente leitura, sem funções externas ou bloqueios.")
    for node in tree.walk():
        if isinstance(node, exp.Anonymous) and node.name.upper() not in _SAFE_ORACLE_FUNCTIONS:
            raise ValidationError(f"Função SQL não permitida na consulta SIP: {node.name}.")
    if any(isinstance(node, exp.Placeholder) and str(node.this).lower() not in {"sip_start", "sip_end"} for node in tree.walk()):
        raise ValidationError("Use apenas os parâmetros :sip_start e :sip_end para períodos SIP.")
    for node in tree.walk():
        if isinstance(node, exp.Identifier) and "@" in node.name:
            raise ValidationError("Links de banco Oracle não são permitidos.")
        if isinstance(node, exp.Column) and (
            node.name.upper() in {"NEXTVAL", "CURRVAL"} or node.table.upper() == "SYS"
        ):
            raise ValidationError("A consulta SIP usa um recurso não permitido.")
        if isinstance(node, exp.Table) and node.db.upper() == "SYS":
            raise ValidationError("A consulta SIP usa um recurso não permitido.")
    return tree.sql(dialect="oracle")


def period_sql(sql: str) -> str:
    """Replace a fixed SYSDATE lower bound with the selected period start."""
    tree = sqlglot.parse_one(validated_select(sql), read="oracle")
    for node in tree.walk():
        if isinstance(node, (exp.GTE, exp.GT)) and isinstance(node.expression, exp.Sub):
            offset = node.expression.expression
            if isinstance(node.expression.this, exp.CurrentTimestamp) and isinstance(offset, exp.Literal) and not offset.is_string:
                # Keep the original N-day lookback relative to the selected
                # period; the output TS may follow the process start.
                node.set("expression", sqlglot.parse_one(
                    f":sip_start - NUMTODSINTERVAL({offset.sql(dialect='oracle')}, 'DAY')", read="oracle"))
        elif isinstance(node, (exp.GTE, exp.GT)) and isinstance(node.expression, exp.CurrentTimestamp):
            node.set("expression", exp.Placeholder(this="sip_start"))
    return validated_select(tree.sql(dialect="oracle"))


class SipOracleService:
    def __init__(self, config: Settings = settings, connection_factory=None) -> None:
        self.config = config
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.config.is_sip_configured():
            raise SipUnavailableError("Configure SIP_ORACLE_USERNAME e SIP_ORACLE_PASSWORD no backend.")
        if self.connection_factory is not None:
            connection = self.connection_factory()
        else:
            import oracledb
            if self.config.sip_oracle_thick_mode:
                try:
                    oracledb.init_oracle_client()
                except oracledb.Error as exc:
                    raise SipUnavailableError("Oracle Client não está disponível para o modo Thick.") from exc
            dsn = oracledb.makedsn(
                self.config.sip_oracle_host,
                self.config.sip_oracle_port,
                service_name=self.config.sip_oracle_service_name,
            )
            try:
                connection = oracledb.connect(
                    user=self.config.sip_oracle_username,
                    password=self.config.sip_oracle_password.get_secret_value(),
                    dsn=dsn,
                    tcp_connect_timeout=5,
                )
            except oracledb.Error as exc:
                raise SipUnavailableError("Não foi possível conectar ao SIP.") from exc
        connection.autocommit = False
        connection.call_timeout = self.config.sip_oracle_timeout_seconds * 1000
        return connection

    def inspect_columns(self, sql: str) -> list[str]:
        safe_sql = validated_select(sql)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                probe_binds = {name: datetime.now() for name in ("sip_start", "sip_end") if f":{name}" in safe_sql.lower()}
                cursor.execute(f"SELECT * FROM ({safe_sql}) WHERE 1 = 0", probe_binds)
                return [item[0] for item in cursor.description]
        except SipUnavailableError:
            raise
        except Exception as exc:
            raise ValidationError("Não foi possível consultar as colunas no SIP.") from exc
        finally:
            connection.rollback()
            connection.close()

    def fetch_value(self, sql: str, value_column: str):
        safe_sql = validated_select(sql)
        if any(isinstance(node, exp.Placeholder) for node in sqlglot.parse_one(safe_sql, read="oracle").walk()):
            raise ValidationError("Tag de Banco não usa parâmetros de período.")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(f"SELECT * FROM ({safe_sql}) WHERE 1 = 0")
                available = {item[0].upper(): item[0] for item in cursor.description}
                column = available.get(value_column.upper())
                if column is None:
                    raise ValidationError("Selecione uma coluna Value retornada pelo SQL.")
                quoted = '"' + column.replace('"', '""') + '"'
                cursor.execute(f"SELECT src.{quoted} FROM ({safe_sql}) src WHERE ROWNUM <= 2")
                rows = cursor.fetchall()
                if len(rows) > 1:
                    raise ValidationError("A Tag de Banco deve retornar um único valor.")
                value = rows[0][0] if rows else None
                return float(value) if isinstance(value, Decimal) else value
        except (ValidationError, SipUnavailableError):
            raise
        except Exception as exc:
            raise SipUnavailableError("Falha na leitura da Tag de Banco SIP.") from exc
        finally:
            connection.rollback()
            connection.close()

    def fetch_rows(
        self,
        sql: str,
        timestamp_column: str,
        value_column: str,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[list[tuple[datetime, float | int | str | bool | None]], bool]:
        safe_sql = validated_select(sql)
        if start_time >= end_time:
            raise ValidationError("O início deve ser anterior ao fim.")
        local_timezone = ZoneInfo(self.config.sip_oracle_timezone)
        start_local = start_time.astimezone(local_timezone).replace(tzinfo=None)
        end_local = end_time.astimezone(local_timezone).replace(tzinfo=None)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                probe_binds = {name: value for name, value in (("sip_start", start_local), ("sip_end", end_local)) if f":{name}" in safe_sql.lower()}
                cursor.execute(f"SELECT * FROM ({safe_sql}) WHERE 1 = 0", probe_binds)
                available = {item[0].upper(): item[0] for item in cursor.description}
                timestamp_name = available.get(timestamp_column.upper())
                value_name = available.get(value_column.upper())
                if not timestamp_name or not value_name or timestamp_name == value_name:
                    raise ValidationError("Selecione colunas distintas de Timestamp e Value retornadas pelo SQL.")
                quote = lambda name: '"' + name.replace('"', '""') + '"'
                ts_col = quote(timestamp_name)
                val_col = quote(value_name)
                query = (
                    f"SELECT sip_ts, sip_value FROM ("
                    f"SELECT src.{ts_col} AS sip_ts, src.{val_col} AS sip_value "
                    f"FROM ({safe_sql}) src "
                    f"WHERE src.{ts_col} >= :sip_start AND src.{ts_col} < :sip_end "
                    f"ORDER BY src.{ts_col}) WHERE ROWNUM <= :sip_limit"
                )
                cursor.execute(query, {
                    "sip_start": start_local,
                    "sip_end": end_local,
                    "sip_limit": self.config.sip_oracle_max_rows + 1,
                })
                raw_rows = cursor.fetchall()
                truncated = len(raw_rows) > self.config.sip_oracle_max_rows
                rows = []
                for ts, value in raw_rows[:self.config.sip_oracle_max_rows]:
                    if not isinstance(ts, datetime):
                        raise ValidationError("A coluna Timestamp deve ser Oracle DATE ou TIMESTAMP.")
                    timestamp = ts.replace(tzinfo=local_timezone) if ts.tzinfo is None else ts
                    if isinstance(value, Decimal):
                        value = float(value)
                    elif value is not None and not isinstance(value, (float, int, str, bool)):
                        raise ValidationError("A coluna Value deve conter número ou texto.")
                    rows.append((timestamp.astimezone(timezone.utc), value))
                return rows, truncated
        except (ValidationError, SipUnavailableError):
            raise
        except Exception as exc:
            raise SipUnavailableError("Falha na leitura do SIP; confirme SQL, acesso e período.") from exc
        finally:
            connection.rollback()
            connection.close()
