"""Custom exception classes and FastAPI exception handlers.

Defines a hierarchy of application exceptions and a registration
function that wires them into a FastAPI ``app``.
"""

from fastapi import HTTPException, status
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.core.response import error_response


class AppException(HTTPException):
    """Base application exception.

    All custom exceptions inherit from this class. The ``code`` field
    carries the HTTP status code by default but may carry a different
    application-level code when needed.
    """

    def __init__(
        self,
        status_code: int = 500,
        message: str = "Internal server error",
        code: int | None = None,
    ) -> None:
        self.code = code or status_code
        self.message = message
        super().__init__(status_code=status_code, detail=message)


class NotFoundException(AppException):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, message=message)


class UnauthorizedException(AppException):
    """Authentication required (401)."""

    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, message=message)


class ForbiddenException(AppException):
    """Access denied (403)."""

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, message=message)


class BadRequestException(AppException):
    """Invalid request (400)."""

    def __init__(self, message: str = "Bad request") -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, message=message)


class ConflictException(AppException):
    """Resource conflict (409)."""

    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, message=message)


class StorageError(Exception):
    """MinIO / file-storage related error.

    This is a non-HTTP exception raised by the storage service layer.
    Callers (route handlers) should catch it and translate to an
    appropriate HTTP response when needed.
    """

    def __init__(self, message: str = "Storage error") -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


async def _app_exception_handler(_request: Request, exc: AppException) -> JSONResponse:
    """Handle any ``AppException`` subclass."""
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            message=exc.message,
            status_code=exc.status_code,
        ).model_dump(),
    )


async def _generic_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions (500)."""
    return JSONResponse(
        status_code=500,
        content=error_response(
            message="Internal server error",
            status_code=500,
        ).model_dump(),
    )


_EXCEPTION_HANDLERS: list[tuple[type[Exception], type]] = [
    (AppException, _app_exception_handler),
    (Exception, _generic_exception_handler),
]


def register_exception_handlers(app) -> None:
    """Register all custom exception handlers on a FastAPI application.

    Args:
        app: A FastAPI instance.
    """
    for exc_cls, handler in _EXCEPTION_HANDLERS:
        app.add_exception_handler(exc_cls, handler)
