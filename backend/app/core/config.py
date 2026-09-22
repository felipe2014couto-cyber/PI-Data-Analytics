"""Core configuration module."""
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="PI Analytics Data")
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    # Production connects to the dedicated TimescaleDB service. Tests and
    # local migration fixtures may override this explicitly with SQLite.
    database_url: str = Field(default="postgresql+psycopg://pi_app@localhost:6543/pi_analytics")
    database_password: SecretStr | None = Field(default=None)
    frontend_origin: str = Field(default="http://localhost:5173")
    auth_jwt_secret: SecretStr | None = Field(default=None)
    auth_jwt_expire_minutes: int = Field(default=60, ge=5, le=1440)
    auth_cookie_secure: bool = Field(default=False)
    auth_cookie_name: str = Field(default="pads_session", min_length=3, max_length=64)
    auth_csrf_cookie_name: str = Field(default="pads_csrf", min_length=3, max_length=64)

    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default_factory=list)

    pi_web_api_base_url: str | None = Field(
        default=None,
        description="URL base do PI Web API (ex.: https://servidor/piwebapi).",
    )
    pi_web_api_auth_mode: Literal["none", "basic"] = Field(
        default="none",
        description="Modo de autenticacao do PI Web API. Apenas 'none' ou 'basic' sao suportados.",
    )
    pi_web_api_username: str | None = Field(
        default=None,
        description="Usuario para autenticacao basica no PI Web API.",
    )
    pi_web_api_password: SecretStr | None = Field(
        default=None,
        description="Senha para autenticacao basica no PI Web API (SecretStr).",
    )
    pi_web_api_verify_ssl: bool = Field(
        default=True,
        description="Define se a verificacao SSL/TLS do PI Web API deve ser realizada.",
    )
    pi_data_server_name: str | None = Field(
        default=None,
        description="Nome do PI Data Archive usado na construcao do caminho da tag.",
    )
    pi_request_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=600.0,
        description="Timeout das chamadas HTTP ao PI Web API em segundos.",
    )
    pi_request_max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Numero maximo de tentativas em operacoes GET idempotentes.",
    )
    pi_query_max_tags: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Quantidade maxima de tags por consulta de serie temporal.",
    )
    pi_query_max_points_per_tag: int = Field(
        default=20000,
        ge=1,
        le=1_000_000,
        description="Quantidade maxima de pontos por tag em uma consulta.",
    )
    pi_query_concurrency: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Concorrencia global maxima de chamadas ao PI Web API.",
    )
    pi_query_global_lock_key: int = Field(
        default=2147483003,
        description="Advisory lock PostgreSQL que serializa consultas PI entre processos.",
    )
    pi_query_initial_chunk_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Tamanho inicial do bloco temporal em dias.",
    )
    pi_query_chunk_max_points: int = Field(
        default=20000,
        ge=1,
        le=100000,
        description="Limite de pontos por chamada ao PI Web API.",
    )
    pi_query_visual_default_points_per_tag: int = Field(
        default=1200,
        ge=100,
        le=5000,
        description="Alvo visual padrao de pontos por tag baseado na largura tipica de tela.",
    )
    pi_query_visual_max_points_per_tag: int = Field(
        default=2500,
        ge=100,
        le=5000,
        description="Limite maximo tecnico de protecao server-side por tag.",
    )
    pi_query_visual_max_total_points: int = Field(
        default=200000,
        ge=1000,
        le=1_000_000,
        description="Limite global de pontos na resposta visual.",
    )
    timescaledb_dynamic_raw_point_limit: int = Field(
        default=5000,
        ge=1,
        le=100000,
        description="Maximo de RecordedValues qualificados para leitura visual direta.",
    )
    timescaledb_query_cache_ttl_seconds: int = Field(
        default=45,
        ge=1,
        le=300,
        description="TTL do cache em memoria para consultas visuais dinamicas.",
    )
    timescaledb_query_cache_max_entries: int = Field(
        default=64,
        ge=1,
        le=512,
        description="Quantidade maxima de consultas TimescaleDB no cache em memoria.",
    )
    pi_query_max_period_days: int = Field(
        default=366,
        ge=1,
        le=3660,
        description="Periodo maximo permitido em dias.",
    )
    pi_query_max_split_depth: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Profundidade maxima de subdivisao de blocos recorded.",
    )
    pi_query_max_chunks: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Numero maximo de blocos por consulta.",
    )

    # Fase 5.4.2 – Otimizacao de consultas

    pi_query_streamset_batch_size: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Numero maximo de tags por lote StreamSet.",
    )

    pi_streamset_recorded_max_webids: int = Field(default=10, ge=1, le=20)
    pi_batch_max_requests: int = Field(default=10, ge=1, le=20)
    pi_batch_max_concurrent: int = Field(default=2, ge=1, le=4)
    pi_recorded_window_max_points: int = Field(default=10000, ge=1, le=100000)
    pi_recorded_window_min_seconds: int = Field(default=60, ge=1, le=86400)
    pi_batch_resource_max_chars: int = Field(default=1800, ge=512, le=16000)

    pi_cache_webid_max_entries: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Numero maximo de entradas no cache de WebId.",
    )
    pi_cache_webid_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="TTL padrao do cache de WebId em segundos (24h).",
    )

    pi_cache_visual_max_entries: int = Field(
        default=32,
        ge=1,
        le=256,
        description="Numero maximo de entradas no cache visual.",
    )
    pi_cache_visual_max_total_points: int = Field(
        default=500000,
        ge=10000,
        le=5_000_000,
        description="Maximo total de pontos armazenados no cache visual.",
    )
    pi_cache_visual_max_points_per_entry: int = Field(
        default=100000,
        ge=1000,
        le=500000,
        description="Maximo de pontos por entrada no cache visual.",
    )
    pi_cache_visual_recent_ttl_seconds: int = Field(
        default=15,
        ge=1,
        le=300,
        description="TTL do cache visual para janela recente (segundos).",
    )
    pi_cache_visual_historical_ttl_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="TTL do cache visual para janela historica (segundos).",
    )
    pi_cache_visual_recent_window_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Janela considerada recente para o cache visual (segundos).",
    )

    pi_visual_max_requests_per_query: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Limite maximo de requisicoes PI por consulta visual.",
    )

    pi_http_max_connections: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Maximo de conexoes HTTP no pool (0 = concurrency + 2).",
    )
    pi_http_max_keepalive: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Maximo de conexoes keep-alive (0 = concurrency).",
    )
    pi_http_keepalive_expiry_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Tempo de vida de conexoes keep-alive.",
    )

    # CEP Analysis
    pi_cep_max_variables: int = Field(default=24)
    pi_cep_result_ttl_seconds: int = Field(default=3600)
    pi_cep_operation_timeout_seconds: int = Field(default=1800)
    pi_cep_cleanup_interval_seconds: int = Field(default=60)
    pi_cep_recorded_max_points_per_tag: int = Field(default=10000)
    pi_cep_recorded_max_total_points: int = Field(default=100000)

    # TimescaleDB & Workers
    timescaledb_capacity_limit_gb: float = Field(
        default=50.0,
        description="Capacidade maxima de disco para TimescaleDB em GB antes de bloqueio e descarte de emergencia.",
    )
    timescaledb_warning_limit_gb: float = Field(
        default=40.0,
        description="Limite de alerta de capacidade em GB para pausar backfill.",
    )
    ingestion_cycle_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        description="Intervalo em segundos entre ciclos do worker de ingestao live.",
    )
    ingestion_recorded_cycle_seconds: float = Field(
        default=60.0,
        ge=10.0,
        le=300.0,
        description="Intervalo entre ciclos de captura RecordedValues.",
    )
    ingestion_recorded_window_seconds: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Janela nominal consultada no endpoint RecordedValues.",
    )
    ingestion_recorded_max_points: int = Field(
        default=20_000,
        ge=100,
        le=1_000_000,
        description="Limite por chamada RecordedValues antes de subdividir a janela.",
    )
    ingestion_overlap_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Janela de sobreposicao retroativa para compensar latencia de gravacao no PI Web API.",
    )
    ingestion_freshness_tolerance_seconds: int = Field(
        default=300,
        ge=30,
        le=86400,
        description="Atraso máximo aceito para períodos relativos antes de sinalizar dados obsoletos.",
    )
    ingestion_interpolated_10s_window_hours: float = Field(default=12.0, ge=0.25, le=24.0)
    ingestion_interpolated_300s_window_days: int = Field(default=14, ge=1, le=60)
    ingestion_tag_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Numero maximo de tags ingeridas simultaneamente por ciclo.",
    )
    ingestion_tag_budget_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Maximo de minutos pendentes processados por tag por turno.",
    )
    ingestion_tag_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        le=1800.0,
        description="Timeout total de um turno de ingestao por tag (independente do "
        "timeout HTTP por requisicao). Ao expirar, a tag recebe backoff TAG_TIMEOUT.",
    )
    ingestion_tag_request_budget: int = Field(
        default=8,
        ge=1,
        le=256,
        description="Maximo de chamadas RecordedValues por tag por turno (paginacao incluida)."
        " O tag volta para a fila no proximo ciclo sem avancar o watermark indevidamente.",
    )
    ingestion_no_watermark_minutes: int = Field(
        default=1,
        ge=1,
        le=60,
        description="Minutos concluidos iniciais para tags sem watermark (politica conservadora).",
    )
    ingestion_page_depth_limit: int = Field(
        default=20,
        ge=2,
        le=64,
        description="Profundidade maxima de subdivisao do intervalo RecordedValues.",
    )
    # Worker integration
    workers_enabled: bool = Field(
        default=True,
        description="Ativa workers integrados ao lifespan. False para testes ou manutencao.",
    )
    worker_ingestion_enabled: bool = Field(
        default=True,
        description="Ativa worker de ingestao integrado ao backend.",
    )
    worker_backfill_enabled: bool = Field(
        default=True,
        description="Ativa worker de backfill integrado ao backend.",
    )
    ingestion_catchup_concurrency: int = Field(
        default=2,
        ge=1,
        le=16,
        description="Minutos processados em paralelo no catch-up pos-desligamento.",
    )
    ingestion_catchup_budget_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        description="Maximo de minutos recuperados por ciclo de catch-up.",
    )
    ingestion_reconciliation_minutes: int = Field(
        default=3,
        ge=0,
        le=30,
        description="Quantos minutos recentes re-consultar para capturar eventos atrasados no PI Archive.",
    )
    backfill_legacy_stale_seconds: int = Field(
        default=1800,
        ge=300,
        le=86400,
        description="Tempo em segundos apos o qual um RUNNING sem lease e considerado obsoleto.",
    )
    backfill_chunk_days: int = Field(
        default=1,
        ge=1,
        le=30,
        description="Tamanho em dias de cada bloco processado no backfill historico.",
    )
    backfill_recorded_window_hours: float = Field(
        default=12.0,
        ge=0.25,
        le=48.0,
        description="Janela inicial do backfill RECORDED em horas; janelas podem ser divididas adaptativamente.",
    )
    backfill_recorded_max_points: int = Field(
        default=10000,
        ge=100,
        le=1_000_000,
        description="maxCount conservador usado pelo backfill RECORDED.",
    )
    backfill_admin_concurrency: int = Field(
        default=2,
        ge=1,
        le=8,
        description="Chamadas simultaneas para recargas administrativas.",
    )
    backfill_lease_seconds: int = Field(default=900, ge=60, le=7200)
    backfill_heartbeat_seconds: int = Field(default=30, ge=5, le=300)
    backfill_retry_base_seconds: float = Field(default=5.0, ge=0.1, le=300.0)
    backfill_retry_max_seconds: float = Field(default=300.0, ge=1.0, le=3600.0)
    backfill_max_days: int = Field(
        default=370,
        ge=1,
        le=3650,
        description="Periodo maximo permitido para carga historica (politica de retencao).",
    )
    backfill_auto_rounds_enabled: bool = Field(
        default=False,
        description="Ativa ciclos automaticos em lote (R1..R4) no worker de backfill. Quando False, apenas recargas manuais/administrativas sao executadas.",
    )
    deletion_batch_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Tamanho em dias dos blocos de purga assincrona de tags.",
    )

    def get_cors_origins(self) -> list[str]:
        if self.cors_origins:
            return self.cors_origins
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]

    def is_pi_configured(self) -> bool:
        return bool(self.pi_web_api_base_url and self.pi_data_server_name)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    return settings


settings = get_settings()
