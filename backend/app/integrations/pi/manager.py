"""Lifecycle management for the PI data provider singleton."""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import Settings, get_settings
from app.integrations.pi.errors import PiNotConfiguredError
from app.integrations.pi.provider import PiDataProvider
from app.integrations.pi.webapi_provider import PiWebApiDataProvider, reset_global_semaphore, set_global_semaphore

logger = logging.getLogger("pi_analytics_data.pi.manager")


class PiDataProviderManager:
    """Holds a single PI data provider and manages its lifecycle.

    The manager inspects the current settings on every call to :meth:`get`
    so that test setups that mutate settings (or environments that update
    configuration at runtime) are reflected immediately.
    """

    def __init__(self) -> None:
        self._provider: Optional[PiDataProvider] = None
        self._configured_base_url: Optional[str] = None
        self._configured_data_server: Optional[str] = None
        self._configured_auth_mode: Optional[str] = None
        self._configured_username: Optional[str] = None

    def _settings_signature(self, s: Settings) -> tuple:
        return (
            s.pi_web_api_base_url,
            s.pi_data_server_name,
            s.pi_web_api_auth_mode,
            s.pi_web_api_username,
        )

    def configure(self, settings: Optional[Settings] = None) -> Optional[PiDataProvider]:
        s = settings or get_settings()
        if not s.is_pi_configured():
            if self._provider is not None:
                self._safe_close(self._provider)
                self._provider = None
                self._reset_signature()
            return None

        signature = self._settings_signature(s)
        if self._provider is not None and self._configured_base_url is not None:
            current = (
                self._configured_base_url,
                self._configured_data_server,
                self._configured_auth_mode,
                self._configured_username,
            )
            if current == signature:
                return self._provider
            # Settings changed: rebuild provider.
            self._safe_close(self._provider)
            self._provider = None
            self._reset_signature()

        provider = PiWebApiDataProvider(
            base_url=s.pi_web_api_base_url or "",
            data_server=s.pi_data_server_name or "",
            auth_mode=s.pi_web_api_auth_mode,
            username=s.pi_web_api_username,
            password=s.pi_web_api_password,
            verify_ssl=s.pi_web_api_verify_ssl,
            timeout=s.pi_request_timeout_seconds,
            max_retries=s.pi_request_max_retries,
            concurrency=s.pi_query_concurrency,
        )
        self._provider = provider
        self._configured_base_url = s.pi_web_api_base_url
        self._configured_data_server = s.pi_data_server_name
        self._configured_auth_mode = s.pi_web_api_auth_mode
        self._configured_username = s.pi_web_api_username
        return provider

    def _reset_signature(self) -> None:
        self._configured_base_url = None
        self._configured_data_server = None
        self._configured_auth_mode = None
        self._configured_username = None

    @staticmethod
    def _safe_close(provider: PiDataProvider) -> None:
        if not isinstance(provider, PiWebApiDataProvider):
            return
        if not provider.is_started:
            return
        try:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop is not None and loop.is_running():
                loop.create_task(provider.close())
            else:
                asyncio.run(provider.close())
        except Exception:  # pragma: no cover - defensive
            logger.exception("Falha ao fechar cliente PI anterior.")

    def get(self) -> Optional[PiDataProvider]:
        return self.configure()

    def require(self) -> PiDataProvider:
        provider = self.get()
        if provider is None:
            raise PiNotConfiguredError()
        return provider

    async def startup(self) -> None:
        s = get_settings()
        set_global_semaphore(s.pi_query_concurrency)
        provider = self.configure()
        if isinstance(provider, PiWebApiDataProvider):
            await provider.start()
            logger.info("Cliente HTTP do PI Web API inicializado.")

    async def shutdown(self) -> None:
        reset_global_semaphore()
        provider = self._provider
        self._provider = None
        self._reset_signature()
        if isinstance(provider, PiWebApiDataProvider):
            await provider.close()
            logger.info("Cliente HTTP do PI Web API encerrado.")


_manager = PiDataProviderManager()


def get_pi_data_provider() -> Optional[PiDataProvider]:
    return _manager.get()


def configure_pi_data_provider(settings: Optional[Settings] = None) -> Optional[PiDataProvider]:
    return _manager.configure(settings)


def pi_data_provider_dep() -> PiDataProvider:
    """FastAPI dependency that requires a configured PI provider."""
    return _manager.require()


async def startup_pi_provider() -> None:
    await _manager.startup()


async def shutdown_pi_provider() -> None:
    await _manager.shutdown()


pi_data_provider = pi_data_provider_dep
