"""Normalized exceptions raised by the PI integration layer."""
from typing import Optional


class PiIntegrationError(Exception):
    """Base PI integration error.

    These exceptions carry a ``code`` (matching the API error code) and a
    safe message. The HTTP layer translates them to ``AppError`` instances
    with appropriate status codes.
    """

    code: str = "PI_ERROR"
    status_code: int = 502
    retryable: bool = False
    safe_message: str = "Erro na integracao com o PI Web API."

    def __init__(self, message: Optional[str] = None, details: Optional[object] = None) -> None:
        super().__init__(message or self.safe_message)
        self.message = message or self.safe_message
        self.details = details


class PiNotConfiguredError(PiIntegrationError):
    code = "PI_NOT_CONFIGURED"
    status_code = 503
    safe_message = "Integracao com o PI Web API nao configurada."


class PiAuthError(PiIntegrationError):
    code = "PI_AUTH_FAILED"
    status_code = 502
    safe_message = "Falha de autenticacao no PI Web API."


class PiTimeoutError(PiIntegrationError):
    code = "PI_TIMEOUT"
    status_code = 504
    retryable = True
    safe_message = "Timeout na comunicacao com o PI Web API."


class PiSSLError(PiIntegrationError):
    code = "PI_SSL_ERROR"
    status_code = 502
    retryable = True
    safe_message = "Falha de SSL/TLS na comunicacao com o PI Web API."


class PiUnavailableError(PiIntegrationError):
    code = "PI_UNAVAILABLE"
    status_code = 502
    retryable = True
    safe_message = "PI Web API indisponivel."


class PiRateLimitedError(PiIntegrationError):
    code = "PI_RATE_LIMITED"
    status_code = 503
    retryable = True
    safe_message = "PI Web API retornou 429 (Too Many Requests)."


class PiInvalidResponseError(PiIntegrationError):
    code = "PI_INVALID_RESPONSE"
    status_code = 502
    safe_message = "Resposta invalida recebida do PI Web API."


class PiTagNotFoundError(PiIntegrationError):
    code = "PI_TAG_NOT_FOUND"
    status_code = 404
    safe_message = "Tag nao encontrada no PI Web API."


class PiUnsupportedAuthError(PiIntegrationError):
    code = "PI_UNSUPPORTED_AUTH"
    status_code = 501
    safe_message = "Modo de autenticacao do PI Web API nao suportado."
