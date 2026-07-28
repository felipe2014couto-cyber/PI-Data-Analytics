"""Core configuration module."""
from functools import lru_cache
from typing import List, Literal, Optional

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
    database_url: str = Field(default="sqlite:///./pi_analytics_data.db")
    frontend_origin: str = Field(default="http://localhost:5173")
    auth_jwt_secret: Optional[SecretStr] = Field(default=None)
    auth_jwt_expire_minutes: int = Field(default=60, ge=5, le=1440)
    auth_cookie_secure: bool = Field(default=False)
    auth_cookie_name: str = Field(default="pads_session", min_length=3, max_length=64)
    auth_csrf_cookie_name: str = Field(default="pads_csrf", min_length=3, max_length=64)

    api_prefix: str = "/api"
    cors_origins: List[str] = Field(default_factory=list)

    pi_web_api_base_url: Optional[str] = Field(
        default=None,
        description="URL base do PI Web API (ex.: https://servidor/piwebapi).",
    )
    pi_web_api_auth_mode: Literal["none", "basic"] = Field(
        default="none",
        description="Modo de autenticacao do PI Web API. Apenas 'none' ou 'basic' sao suportados.",
    )
    pi_web_api_username: Optional[str] = Field(
        default=None,
        description="Usuario para autenticacao basica no PI Web API.",
    )
    pi_web_api_password: Optional[SecretStr] = Field(
        default=None,
        description="Senha para autenticacao basica no PI Web API (SecretStr).",
    )
    pi_web_api_verify_ssl: bool = Field(
        default=True,
        description="Define se a verificacao SSL/TLS do PI Web API deve ser realizada.",
    )
    pi_data_server_name: Optional[str] = Field(
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
        default=4,
        ge=1,
        le=20,
        description="Concorrencia global maxima de chamadas ao PI Web API.",
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
        default=10000,
        ge=1000,
        le=50000,
        description="Alvo visual padrao de pontos exibidos por tag.",
    )
    pi_query_visual_max_points_per_tag: int = Field(
        default=50000,
        ge=1000,
        le=100000,
        description="Alvo visual maximo de pontos exibidos por tag.",
    )
    pi_query_visual_max_total_points: int = Field(
        default=200000,
        ge=1000,
        le=1_000_000,
        description="Limite global de pontos na resposta visual.",
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

    def get_cors_origins(self) -> List[str]:
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
