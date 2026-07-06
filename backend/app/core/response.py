"""Unified API response envelope.

Provides a standard response format used by all API endpoints.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response envelope.

    Attributes:
        status: "success" or "error".
        code: HTTP status code.
        message: Human-readable message.
        data: Response payload (optional).
    """

    status: str = "success"
    code: int = 200
    message: str = "ok"
    data: T | None = None

    model_config = ConfigDict(from_attributes=True)


def success_response(
    data: Any = None,
    message: str = "ok",
    status_code: int = 200,
) -> ApiResponse[Any]:
    """Build a success response.

    Args:
        data: Optional response payload.
        message: Human-readable message.
        status_code: HTTP status code (default 200).

    Returns:
        ApiResponse with status="success".
    """
    return ApiResponse(
        status="success",
        code=status_code,
        message=message,
        data=data,
    )


def error_response(
    message: str = "error",
    status_code: int = 400,
    data: Any = None,
) -> ApiResponse[Any]:
    """Build an error response.

    Args:
        message: Human-readable error message.
        status_code: HTTP status code (default 400).
        data: Optional additional error details.

    Returns:
        ApiResponse with status="error".
    """
    return ApiResponse(
        status="error",
        code=status_code,
        message=message,
        data=data,
    )


def paginated_response(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
    message: str = "ok",
) -> ApiResponse[dict[str, Any]]:
    """Build a paginated list response.

    Args:
        items: List of items for the current page.
        total: Total number of items across all pages.
        page: Current page number (1-indexed).
        page_size: Number of items per page.
        message: Human-readable message.

    Returns:
        ApiResponse with pagination metadata in data.
    """
    return ApiResponse(
        status="success",
        code=200,
        message=message,
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )
