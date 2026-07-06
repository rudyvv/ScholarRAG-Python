"""SiliconFlow embedding API client.

Provides async functions to generate text embeddings via the SiliconFlow
``/v1/embeddings`` endpoint.  Both single-text and batch-text interfaces
are exposed, each with automatic retry on transient network failures.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from app.config import settings
from app.core.exceptions import AppException
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

__all__ = [
    "generate_embedding",
    "generate_embeddings",
]

# ── Constants ────────────────────────────────────────────────────────────────

_TIMEOUT = 30  # HTTP request timeout in seconds
_RETRY_WAIT = 2  # Seconds to wait between retry attempts
_MAX_ATTEMPTS = 2  # Initial attempt + 1 retry

# Exception types considered transient (retryable)
_RETRYABLE: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)

# ── Internal helpers ─────────────────────────────────────────────────────────


async def _post_embeddings(
    client: httpx.AsyncClient,
    *,
    input_data: str | list[str],
    api_key: str | None = None,
    api_base_url: str | None = None,
    model: str | None = None,
) -> dict:
    """Post an embedding request and return parsed JSON.

    Reads defaults from ``settings`` when no explicit *api_key*,
    *api_base_url*, or *model* is given — so callers can pass
    DB-driven overrides while keeping environment-variable behaviour
    as the baseline.

    Args:
        client: An ``httpx.AsyncClient`` instance.
        input_data: A single text string or a list of text strings.
        api_key: Optional override (e.g. from ``ModelProviderConfig``).
        api_base_url: Optional override.
        model: Optional override.

    Returns:
        The parsed JSON response body as a dictionary.

    Raises:
        AppException: If the API returns a non-2xx status code.

    """
    resolved_key = api_key or settings.EMBEDDING_API_KEY
    resolved_url = (api_base_url or settings.EMBEDDING_API_BASE_URL).rstrip("/")
    resolved_model = model or settings.EMBEDDING_MODEL

    # Append ``/embeddings`` path only if not already present (settings
    # already includes it, but DB-stored ``api_base_url`` is the root).
    endpoint = (
        resolved_url
        if resolved_url.endswith("/embeddings")
        else resolved_url + "/embeddings"
    )

    payload: dict = {
        "model": resolved_model,
        "input": input_data,
    }
    headers: dict[str, str] = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
    }

    response = await client.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=_TIMEOUT,
    )

    if response.is_success:
        return response.json()

    raise AppException(
        status_code=502,
        message=(f"Embedding API returned {response.status_code}: {response.text}"),
        code=response.status_code,
    )


async def _call_with_retry(
    input_data: str | list[str],
    *,
    api_key: str | None = None,
    api_base_url: str | None = None,
    model: str | None = None,
) -> dict:
    """Call the embedding API with automatic retry on transient errors.

    Args:
        input_data: A single text string or a list of text strings.
        api_key: Optional override (e.g. from ``ModelProviderConfig``).
        api_base_url: Optional override.
        model: Optional override.

    Returns:
        The parsed JSON response body.

    Raises:
        AppException: If all retry attempts are exhausted.

    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=wait_fixed(_RETRY_WAIT),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    ):
        with attempt:
            return await _post_embeddings(
                get_http_client(),
                input_data=input_data,
                api_key=api_key,
                api_base_url=api_base_url,
                model=model,
            )

    # Unreachable (reraise=True), but type checkers need it.
    raise AppException(
        status_code=502,
        message="Embedding API call failed after retries",
    )


# ── Public API ───────────────────────────────────────────────────────────────


async def generate_embedding(
    text: str,
    *,
    api_key: str | None = None,
    api_base_url: str | None = None,
    model: str | None = None,
) -> list[float]:
    """Generate a single embedding vector for the given text.

    Args:
        text: The input text to embed.
        api_key: Optional override (e.g. from ``ModelProviderConfig``).
        api_base_url: Optional override.
        model: Optional override.

    Returns:
        A 1024-dimensional float vector.

    Raises:
        AppException: If the embedding API call fails.

    """
    data = await _call_with_retry(
        text,
        api_key=api_key,
        api_base_url=api_base_url,
        model=model,
    )
    return data["data"][0]["embedding"]


async def generate_embeddings(
    texts: list[str],
    *,
    api_key: str | None = None,
    api_base_url: str | None = None,
    model: str | None = None,
) -> list[list[float]]:
    """Generate embedding vectors for a batch of texts.

    Args:
        texts: A list of input texts to embed.
        api_key: Optional override (e.g. from ``ModelProviderConfig``).
        api_base_url: Optional override.
        model: Optional override.

    Returns:
        A list of 1024-dimensional float vectors, one per input text.

    Raises:
        AppException: If the embedding API call fails.

    """
    data = await _call_with_retry(
        texts,
        api_key=api_key,
        api_base_url=api_base_url,
        model=model,
    )
    return [item["embedding"] for item in data["data"]]
