"""Centralized error handlers."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import (
    INTERNAL_ERROR,
    NOT_FOUND,
    VALIDATION_ERROR,
)
from app.core.exceptions import AppError
from app.schemas.common import ErrorBody, ErrorResponse

logger = logging.getLogger("pi_analytics_data.errors")


def _error_response(code: str, message: str, details: object, status_code: int) -> JSONResponse:
    payload = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=False))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            code=VALIDATION_ERROR,
            message="Erro de validacao nos dados enviados.",
            details=exc.errors(),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {404: NOT_FOUND}
        code = code_map.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Erro na requisicao."
        return _error_response(
            code=code,
            message=message,
            details=None,
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return _error_response(
            code=INTERNAL_ERROR,
            message="Erro interno do servidor.",
            details=None,
            status_code=500,
        )
