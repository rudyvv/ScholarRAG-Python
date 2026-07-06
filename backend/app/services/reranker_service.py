"""Cross-encoder reranker via SiliconFlow API.

Provides ``rerank_chunks`` to re-score a list of retrieved document
chunks against the original user query using

    BAAI/bge-reranker-v2-m3

This is a cross-encoder model that jointly encodes query + document,
producing a much more accurate relevance score than the embedding-based
dot-product used in vector search.

The reranker is **not** configured via the DB ``ModelProviderConfig``
table — the user explicitly wanted it hardcoded / env-var driven.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_RERANK_TIMEOUT = 30  # HTTP request timeout in seconds
_TOP_K_RERANK = 5  # Return top N after reranking

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def rerank_chunks(
    query: str,
    chunks: list[dict[str, Any]],
    top_k: int = _TOP_K_RERANK,
) -> list[dict[str, Any]]:
    """Re-rank document chunks with a cross-encoder reranker.

    Args:
        query: The original user query.
        chunks: List of chunk dicts, each at least containing
            ``chunk_id``, ``content``, and ``score``.
        top_k: Number of top chunks to return after reranking.

    Returns:
        The top-*k* chunks sorted by descending reranker score, with an
        added ``rerank_score`` field.  If the API call fails, the
        original list (truncated to *top_k*) is returned unchanged.
    """
    if not chunks:
        return []

    documents = [_truncate(c.get("content", ""), 8000) for c in chunks]

    payload: dict[str, Any] = {
        "model": settings.RERANKER_MODEL,
        "query": query,
        "documents": documents,
        "top_n": min(top_k, len(chunks)),
        "return_documents": False,
    }

    headers = {
        "Authorization": f"Bearer {_resolve_api_key()}",
        "Content-Type": "application/json",
    }
    url = f"{settings.RERANKER_API_BASE_URL.rstrip('/')}/rerank"

    try:
        client = get_http_client()
        response = await client.post(
            url, json=payload, headers=headers, timeout=_RERANK_TIMEOUT
        )

        if not response.is_success:
            logger.warning(
                "Reranker API returned %s — falling back to original order",
                response.status_code,
            )
            return chunks[:top_k]

        data = response.json()
        results: list[dict] = data.get("results", [])

        # Build a new list ordered by reranker score
        reranked: list[dict[str, Any]] = []
        for item in results:
            idx = item["index"]
            score = item["relevance_score"]
            chunk = dict(chunks[idx])  # shallow copy
            chunk["score"] = score  # replace original score
            chunk["rerank_score"] = score
            chunk["match_type"] = "reranked"
            reranked.append(chunk)

        logger.info(
            "Reranked %d chunks → top %d (best score=%.4f)",
            len(chunks),
            len(reranked),
            reranked[0]["score"] if reranked else 0,
        )
        return reranked  # noqa: TRY300

    except httpx.TimeoutException:
        logger.warning("Reranker API timed out — falling back to original order")
        return chunks[:top_k]
    except httpx.RequestError as exc:
        logger.warning("Reranker API request failed: %s — falling back", exc)
        return chunks[:top_k]
    except Exception:
        logger.exception("Reranker unexpected error — falling back")
        return chunks[:top_k]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_api_key() -> str:
    """Resolve the reranker API key.

    Prefers the dedicated ``RERANKER_API_KEY`` env var; falls back to
    the embedding API key since both typically point at the same
    SiliconFlow account.
    """
    key = settings.RERANKER_API_KEY or settings.EMBEDDING_API_KEY
    if not key:
        logger.warning("No RERANKER_API_KEY or EMBEDDING_API_KEY configured")
    return key


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to *max_chars* while keeping whole sentences."""
    if len(text) <= max_chars:
        return text
    end = text.rfind("。", 0, max_chars)
    if end == -1:
        end = text.rfind(".", 0, max_chars)
    if end == -1:
        end = max_chars
    return text[: end + 1]
