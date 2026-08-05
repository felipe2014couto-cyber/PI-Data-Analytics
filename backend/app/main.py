"""FastAPI application entry point."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import register_error_handlers
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.integrations.pi.manager import shutdown_pi_provider, startup_pi_provider
from app.services.cep_query_store import get_cep_query_store
from app.services.query_registry import get_query_registry


async def _cep_cleanup_loop() -> None:
    """Periodically clean up expired CEP operations."""
    store = get_cep_query_store()
    registry = get_query_registry()
    interval = settings.pi_cep_cleanup_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            result = await store.cleanup_expired()
            for qid in result.timed_out:
                await registry.cancel(qid)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("CEP cleanup failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    await startup_pi_provider()

    # Start CEP cleanup task
    cleanup_task = asyncio.create_task(_cep_cleanup_loop())

    try:
        yield
    finally:
        # Shutdown cleanup task
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await shutdown_pi_provider()
        logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="PI Analytics Data - Fase 2 (Integracao com PI Web API).",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    register_error_handlers(app)

    return app


app = create_app()
