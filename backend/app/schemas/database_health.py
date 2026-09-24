"""Schemas for Database Health (Saúde do Banco) monitoring."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DatabaseHealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNAVAILABLE = "unavailable"


class DatabaseConnectionInfo(BaseModel):
    reachable: bool = Field(description="Indica se o banco respondeu a query basica de conexao.")
    latency_ms: Optional[float] = Field(default=None, description="Latencia da consulta basica em milissegundos.")
    name: Optional[str] = Field(default=None, description="Nome do banco de dados conectado.")
    postgresql_version: Optional[str] = Field(default=None, description="Versao do PostgreSQL reportada pelo servidor.")
    timescaledb_version: Optional[str] = Field(default=None, description="Versao da extensao TimescaleDB instalada, se disponivel.")
    uptime_seconds: Optional[float] = Field(default=None, description="Tempo em segundos desde a inicializacao do servidor (postmaster).")
    alembic_revision: Optional[str] = Field(default=None, description="Revisao Alembic atualmente aplicada no banco.")


class StorageRelationInfo(BaseModel):
    schema_name: str
    relation_name: str
    relation_type: str
    data_bytes: int
    index_bytes: int
    total_bytes: int
    data_human: str
    index_human: str
    total_human: str


class StorageInfo(BaseModel):
    database_bytes: int = Field(default=0, description="Tamanho logico total do banco de dados.")
    database_human: str = Field(default="0 B", description="Tamanho logico do banco em formato legivel.")
    tables_bytes: int = Field(default=0, description="Tamanho total das tabelas do banco.")
    tables_human: str = Field(default="0 B", description="Tamanho total das tabelas em formato legivel.")
    tables_heap_bytes: int = Field(default=0, description="Tamanho do heap de dados de tabelas (excluindo TOAST para não gerar dupla contagem).")
    tables_heap_human: str = Field(default="0 B", description="Tamanho do heap de tabelas em formato legivel.")
    indexes_bytes: int = Field(default=0, description="Tamanho total dos indices do banco.")
    indexes_human: str = Field(default="0 B", description="Tamanho total dos indices em formato legivel.")
    toast_bytes: int = Field(default=0, description="Tamanho total de tabelas TOAST.")
    toast_human: str = Field(default="0 B", description="Tamanho total TOAST em formato legivel.")
    pi_samples_bytes: Optional[int] = Field(default=None, description="Tamanho total da hypertable pi_samples_timescale.")
    pi_samples_human: Optional[str] = Field(default=None, description="Tamanho da hypertable pi_samples_timescale em formato legivel.")
    recent_rowstore_bytes: Optional[int] = Field(default=None, description="Tamanho dos chunks recentes não comprimidos (janela ativa).")
    recent_rowstore_human: Optional[str] = Field(default=None, description="Tamanho legivel dos chunks recentes.")
    historical_delta_rowstore_bytes: Optional[int] = Field(default=None, description="Tamanho de dados rowstore acumulados em chunks históricos columnstore.")
    historical_delta_rowstore_human: Optional[str] = Field(default=None, description="Tamanho legivel dos deltas rowstore históricos.")
    columnstore_bytes: Optional[int] = Field(default=None, description="Espaço físico atual das estruturas colunares comprimidas.")
    columnstore_human: Optional[str] = Field(default=None, description="Tamanho legivel do columnstore atual.")
    rowstore_indexes_bytes: Optional[int] = Field(default=None, description="Espaço ocupado por índices B-Tree na hypertable.")
    rowstore_indexes_human: Optional[str] = Field(default=None, description="Tamanho legivel dos índices da hypertable.")
    continuous_aggregates_bytes: Optional[int] = Field(default=None, description="Tamanho total das tabelas materializadas de continuous aggregates.")
    continuous_aggregates_human: Optional[str] = Field(default=None, description="Tamanho legivel dos continuous aggregates.")
    compression_before_bytes: Optional[int] = Field(default=None, description="Estatística histórica: tamanho antes da conversão inicial.")
    compression_before_human: Optional[str] = Field(default=None, description="Tamanho antes da compressão.")
    compression_after_bytes: Optional[int] = Field(default=None, description="Estatística histórica: tamanho após a conversão inicial.")
    compression_after_human: Optional[str] = Field(default=None, description="Tamanho após a compressão.")
    compression_ratio_pct: Optional[float] = Field(default=None, description="Taxa de compressão histórica percentual.")
    pi_backfill_bytes: Optional[int] = Field(default=None, description="Tamanho total da tabela pi_backfill_jobs.")
    pi_backfill_human: Optional[str] = Field(default=None, description="Tamanho de pi_backfill_jobs em formato legivel.")
    pi_ingestion_bytes: Optional[int] = Field(default=None, description="Tamanho total da tabela pi_ingestion_state.")
    pi_ingestion_human: Optional[str] = Field(default=None, description="Tamanho de pi_ingestion_state em formato legivel.")
    filesystem_available: bool = Field(default=False, description="Indica se espaco livre em disco esta disponivel via DB.")
    filesystem_reason: Optional[str] = Field(
        default="Métrica do sistema operacional não disponível para o usuário da aplicação",
        description="Justificativa da indisponibilidade de espaco em disco via banco.",
    )
    largest_relations: List[StorageRelationInfo] = Field(default_factory=list, description="Top 10 maiores relacoes do banco.")


class ConnectionsInfo(BaseModel):
    current: int = Field(default=0, description="Total de conexoes estabelecidas com o banco.")
    maximum: int = Field(default=0, description="Limite max_connections configurado no PostgreSQL.")
    usage_percent: float = Field(default=0.0, description="Percentual de utilizacao de conexoes.")
    active: int = Field(default=0, description="Conexoes em execucao ativa.")
    idle: int = Field(default=0, description="Conexoes ociosas aguardando comando.")
    idle_in_transaction: int = Field(default=0, description="Conexoes ociosas dentro de transacao aberta.")
    waiting: int = Field(default=0, description="Conexoes aguardando evento ou lock.")
    worker_leader_connections: int = Field(default=0, description="Conexoes dedicadas a advisory locks dos workers.")
    long_transactions_count: int = Field(default=0, description="Quantidade de transacoes com duracao acima do limiar configurado.")
    oldest_transaction_seconds: Optional[float] = Field(default=None, description="Duracao da transacao aberta mais antiga.")
    long_queries_count: int = Field(default=0, description="Quantidade de consultas em execucao acima do limiar configurado.")
    oldest_query_seconds: Optional[float] = Field(default=None, description="Duracao da consulta ativa mais antiga.")
    commits: Optional[int] = Field(default=None, description="Total de commits acumulados.")
    rollbacks: Optional[int] = Field(default=None, description="Total de rollbacks acumulados.")
    deadlocks: Optional[int] = Field(default=None, description="Total de deadlocks detectados desde o reset.")
    temp_files: Optional[int] = Field(default=None, description="Quantidade de arquivos temporarios criados por queries.")
    temp_bytes: Optional[int] = Field(default=None, description="Bytes temporarios criados por queries.")
    temp_human: Optional[str] = Field(default=None, description="Tamanho de arquivos temporarios em formato legivel.")
    stats_reset: Optional[datetime] = Field(default=None, description="Data/hora do ultimo reset de estatisticas do banco.")


class LocksInfo(BaseModel):
    total: int = Field(default=0, description="Total de locks registrados no pg_locks.")
    granted: int = Field(default=0, description="Locks concedidos.")
    waiting: int = Field(default=0, description="Locks aguardando concessao.")
    advisory_locks: int = Field(default=0, description="Advisory locks ativos (inclui lideres de workers).")
    blocked_sessions: int = Field(default=0, description="Sessoes efetivamente bloqueadas por outra sessao.")
    oldest_wait_seconds: Optional[float] = Field(default=None, description="Duracao do bloqueio mais antigo em segundos.")


class TimescaleInfo(BaseModel):
    available: bool = Field(default=False, description="Extensao TimescaleDB disponivel e operacional.")
    version: Optional[str] = Field(default=None, description="Versao da extensao TimescaleDB.")
    hypertables: int = Field(default=0, description="Quantidade de hypertables cadastradas.")
    chunks: int = Field(default=0, description="Quantidade de chunks alocados.")
    continuous_aggregates: int = Field(default=0, description="Quantidade de continuous aggregates configurados.")
    total_jobs: int = Field(default=0, description="Total de jobs internos do TimescaleDB.")
    failed_jobs: int = Field(default=0, description="Jobs com falha no ultimo ciclo (inclui telemetria).")
    operational_failed_jobs: int = Field(default=0, description="Jobs operacionais com falha (exclui telemetria externa).")
    telemetry_failed: bool = Field(default=False, description="Indica se o job nativo de telemetria externa falhou.")
    last_run_status: Optional[str] = Field(default=None, description="Status da ultima execucao de jobs.")
    last_successful_finish: Optional[datetime] = Field(default=None, description="Instante do ultimo job concluido com sucesso.")
    compression_enabled: Optional[bool] = Field(default=None, description="Compressao ativada em hypertables.")
    retention_configured: Optional[bool] = Field(default=None, description="Politicas de retencao configuradas.")
    columnstore_maintenance: Optional[Dict[str, Any]] = Field(default=None, description="Status da manutencao de columnstore.")


class FreshnessInfo(BaseModel):
    latest_sample_at: Optional[datetime] = Field(default=None, description="Timestamp da amostra mais recente em pi_samples_timescale.")
    latest_recorded_sample_at: Optional[datetime] = Field(default=None, description="Timestamp da amostra RECORDED mais recente.")
    lag_seconds: Optional[float] = Field(default=None, description="Diferenca em segundos entre o horario atual e o dado mais recente.")
    oldest_watermark: Optional[datetime] = Field(default=None, description="Watermark mais antigo entre os estados de ingestao.")
    newest_watermark: Optional[datetime] = Field(default=None, description="Watermark mais recente entre os estados de ingestao.")
    ingestion_states: int = Field(default=0, description="Quantidade de estados de ingestao persistidos.")
    tags_in_backoff: int = Field(default=0, description="Tags atualmente em backoff de ingestao.")
    tags_with_failures: int = Field(default=0, description="Tags com contagem de falhas consecutivas maior que zero.")
    backfill_jobs_by_status: Dict[str, int] = Field(default_factory=dict, description="Quantidade de jobs de backfill por status.")
    expired_backfill_leases: int = Field(default=0, description="Jobs RUNNING cujo lease expirou.")
    consecutive_backfill_failures: int = Field(default=0, description="Jobs de backfill com falhas consecutivas.")
    last_success_at: Optional[datetime] = Field(default=None, description="Data/hora do ultimo sucesso de ingestao registrado.")


class HealthCheckItem(BaseModel):
    name: str = Field(description="Identificador do check (ex: conectividade, conexoes, latencia).")
    status: DatabaseHealthStatus = Field(description="Status do check individual.")
    message: str = Field(description="Mensagem resumida do check.")


class DatabaseHealthResponse(BaseModel):
    status: DatabaseHealthStatus = Field(description="Status consolidado: healthy, warning, critical, unavailable.")
    checked_at: datetime = Field(description="Instante UTC em que as metricas foram coletadas.")
    duration_ms: float = Field(description="Tempo total gasto na coleta em milissegundos.")
    cached: bool = Field(default=False, description="Indica se a resposta foi retornada do cache em memoria.")
    database: DatabaseConnectionInfo
    storage: StorageInfo
    connections: ConnectionsInfo
    locks: LocksInfo
    timescale: TimescaleInfo
    freshness: FreshnessInfo
    checks: List[HealthCheckItem] = Field(default_factory=list, description="Lista dos checks avaliados.")
    unavailable_metrics: List[str] = Field(default_factory=list, description="Metricas nao disponiveis no ambiente atual.")
