"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import register_error_handlers
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.integrations.pi.manager import shutdown_pi_provider, startup_pi_provider


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    await startup_pi_provider()
    try:
        yield
    finally:
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
