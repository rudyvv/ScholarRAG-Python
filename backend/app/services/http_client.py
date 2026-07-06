"""Global HTTP client singleton for outbound API calls.

Provides a single ``httpx.AsyncClient`` instance with connection
pooling, shared across embedding and LLM API calls.  Managed by the
application lifespan (``init_http_client`` / ``close_http_client``).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# ── Global client singleton ─────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the global ``httpx.AsyncClient`` singleton.

    Lazily creates the client with sensible defaults for outbound
    LLM / embedding API calls.
    """
    global _client  # noqa: PLW0603
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
        )
        logger.info("Global httpx.AsyncClient created")
    return _client


async def close_http_client() -> None:
    """Close the global ``httpx.AsyncClient`` singleton."""
    global _client  # noqa: PLW0603
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Global httpx.AsyncClient closed")
