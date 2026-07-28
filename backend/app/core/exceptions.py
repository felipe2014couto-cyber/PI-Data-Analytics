"""Domain exceptions used by services and handlers."""


class AppError(Exception):
    """Base application error."""

    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(self, message: str, details: object = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"

    def __init__(self, message: str = "Registro nao encontrado.", details: object = None) -> None:
        super().__init__(message, details)


class DuplicateCodeError(AppError):
    status_code = 409
    code = "DUPLICATE_CODE"

    def __init__(self, message: str = "Ja existe um registro com este codigo.", details: object = None) -> None:
        super().__init__(message, details)


class DuplicateTagError(AppError):
    status_code = 409
    code = "DUPLICATE_TAG"

    def __init__(self, message: str = "Ja existe uma tag com este nome neste PI Server.", details: object = None) -> None:
        super().__init__(message, details)


class InvalidEquipmentError(AppError):
    status_code = 422
    code = "INVALID_EQUIPMENT"

    def __init__(self, message: str = "Equipamento invalido.", details: object = None) -> None:
        super().__init__(message, details)


class InvalidSectionError(AppError):
    status_code = 422
    code = "INVALID_SECTION"

    def __init__(self, message: str = "Secao invalida.", details: object = None) -> None:
        super().__init__(message, details)


class SectionNotBelongsToEquipmentError(AppError):
    status_code = 422
    code = "SECTION_NOT_BELONGS_TO_EQUIPMENT"

    def __init__(self, message: str = "A secao selecionada nao pertence ao equipamento informado.", details: object = None) -> None:
        super().__init__(message, details)


class InvalidVariableTypeError(AppError):
    status_code = 422
    code = "INVALID_VARIABLE_TYPE"

    def __init__(self, message: str = "Tipo de variavel invalido.", details: object = None) -> None:
        super().__init__(message, details)


class DependencyExistsError(AppError):
    status_code = 409
    code = "DEPENDENCY_EXISTS"

    def __init__(self, message: str = "Nao foi possivel excluir o registro pois existem dependencias.", details: object = None) -> None:
        super().__init__(message, details)


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Erro de validacao.", details: object = None) -> None:
        super().__init__(message, details)


class AuthenticationError(AppError):
    status_code = 401
    code = "AUTHENTICATION_REQUIRED"

    def __init__(self, message: str = "Autenticacao necessaria.", details: object = None) -> None:
        super().__init__(message, details)


class AuthorizationError(AppError):
    status_code = 403
    code = "FORBIDDEN"

    def __init__(self, message: str = "Acesso nao autorizado.", details: object = None) -> None:
        super().__init__(message, details)


class PasswordChangeRequiredError(AppError):
    status_code = 403
    code = "PASSWORD_CHANGE_REQUIRED"

    def __init__(self, message: str = "Altere a senha para continuar.", details: object = None) -> None:
        super().__init__(message, details)


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"

    def __init__(self, message: str = "Conflito na operacao.", details: object = None) -> None:
        super().__init__(message, details)


class TagInactiveError(AppError):
    status_code = 409
    code = "TAG_INACTIVE"

    def __init__(self, message: str = "A tag esta inativa e nao pode ser consultada.", details: object = None) -> None:
        super().__init__(message, details)


class TimeRangeInvalidError(AppError):
    status_code = 400
    code = "TIME_RANGE_INVALID"

    def __init__(self, message: str = "Periodo invalido.", details: object = None) -> None:
        super().__init__(message, details)


class QueryLimitExceededError(AppError):
    status_code = 400
    code = "PI_QUERY_LIMIT_EXCEEDED"

    def __init__(self, message: str = "Limite de consulta excedido.", details: object = None) -> None:
        super().__init__(message, details)


# PI Web API exceptions ---------------------------------------------------


class PiNotConfiguredError(AppError):
    status_code = 503
    code = "PI_NOT_CONFIGURED"

    def __init__(self, message: str = "PI Web API nao configurado.", details: object = None) -> None:
        super().__init__(message, details)


class PiAuthError(AppError):
    status_code = 502
    code = "PI_AUTH_FAILED"

    def __init__(self, message: str = "Falha de autenticacao no PI Web API.", details: object = None) -> None:
        super().__init__(message, details)


class PiTimeoutError(AppError):
    status_code = 504
    code = "PI_TIMEOUT"

    def __init__(self, message: str = "Timeout na comunicacao com o PI Web API.", details: object = None) -> None:
        super().__init__(message, details)


class PiSSLError(AppError):
    status_code = 502
    code = "PI_SSL_ERROR"

    def __init__(self, message: str = "Falha de SSL/TLS na comunicacao com o PI Web API.", details: object = None) -> None:
        super().__init__(message, details)


class PiUnavailableError(AppError):
    status_code = 502
    code = "PI_UNAVAILABLE"

    def __init__(self, message: str = "PI Web API indisponivel.", details: object = None) -> None:
        super().__init__(message, details)


class PiInvalidResponseError(AppError):
    status_code = 502
    code = "PI_INVALID_RESPONSE"

    def __init__(self, message: str = "Resposta invalida do PI Web API.", details: object = None) -> None:
        super().__init__(message, details)


class PiTagNotFoundError(AppError):
    status_code = 404
    code = "PI_TAG_NOT_FOUND"

    def __init__(self, message: str = "Tag nao encontrada no PI Web API.", details: object = None) -> None:
        super().__init__(message, details)


class PiUnsupportedAuthError(AppError):
    status_code = 501
    code = "PI_UNSUPPORTED_AUTH"

    def __init__(self, message: str = "Modo de autenticacao nao suportado.", details: object = None) -> None:
        super().__init__(message, details)


class QueryCancelledError(AppError):
    status_code = 499
    code = "QUERY_CANCELLED"

    def __init__(self, message: str = "Consulta cancelada pelo usuario.", details: object = None) -> None:
        super().__init__(message, details)


class QueryLimitExceeded(AppError):
    status_code = 400
    code = "PI_QUERY_LIMIT_EXCEEDED"

    def __init__(self, message: str = "Limite de requisicoes PI excedido.", details: object = None) -> None:
        super().__init__(message, details)
