"""Elasticsearch full-text search integration for document chunks.

Provides an async Elasticsearch client singleton and functions to
manage the ``document_chunks`` index, index/update chunk documents,
run BM25 full-text queries, and delete chunks per document or the
entire index.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from elasticsearch import (
    AsyncElasticsearch,
)
from elasticsearch import (
    ConnectionError as ESConnectionError,
)
from elasticsearch import (
    NotFoundError as ESNotFoundError,
)
from elasticsearch.helpers import async_bulk

from app.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_NAME = "document_chunks"
_ES_UNAVAILABLE_MSG = "Elasticsearch is not available"

INDEX_MAPPINGS: dict[str, Any] = {
    "properties": {
        "id": {"type": "integer"},
        "document_id": {"type": "integer"},
        "chunk_index": {"type": "integer"},
        "content": {"type": "text", "analyzer": "ik_max_word"},
        "metadata": {"type": "object", "enabled": True},
        "created_at": {"type": "date"},
    },
}

# ---------------------------------------------------------------------------
# Global ES client singleton (managed by app lifespan)
# ---------------------------------------------------------------------------

_es_client: AsyncElasticsearch | None = None


async def init_es() -> None:
    """Create the global ``AsyncElasticsearch`` client singleton."""
    global _es_client  # noqa: PLW0603
    _es_client = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
    logger.info("Global ES client created — connected to %s", settings.ELASTICSEARCH_URL)


async def close_es() -> None:
    """Close the global ``AsyncElasticsearch`` client singleton."""
    global _es_client  # noqa: PLW0603
    if _es_client is not None:
        await _es_client.close()
        _es_client = None
        logger.info("Global ES client closed")


@asynccontextmanager
async def get_es():
    """Yield the global ``AsyncElasticsearch`` client.

    Lazily creates the client on first call so it works both when
    managed by the app lifespan and when used from Celery tasks
    (which run in a separate process and need their own client).
    """
    global _es_client  # noqa: PLW0603
    if _es_client is None:
        _es_client = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
    try:
        yield _es_client
    finally:
        # In a lifespan-managed context the client stays open;
        # only close when we created it ad-hoc (e.g. from Celery).
        pass


# ---------------------------------------------------------------------------
# Index lifecycle
# ---------------------------------------------------------------------------


async def init_search_index() -> bool:
    """Create the ``document_chunks`` index with its field mappings.

    Returns:
        ``True`` if the index was created, ``False`` if it already
        existed.

    Raises:
        AppException: If Elasticsearch is unreachable (503).

    """
    async with get_es() as es:
        try:
            exists = await es.indices.exists(index=INDEX_NAME)
            if exists:
                logger.info("Index '%s' already exists — skipping creation", INDEX_NAME)
                return False

            await es.indices.create(index=INDEX_NAME, mappings=INDEX_MAPPINGS)
            logger.info("Created index '%s'", INDEX_NAME)
        except ESConnectionError:
            logger.warning("Elasticsearch connection failed — unable to create index")
            raise AppException(status_code=503, message=_ES_UNAVAILABLE_MSG) from None

    return True


async def delete_index() -> None:
    """Delete the entire ``document_chunks`` index.

    Silently succeeds if the index does not exist. Intended for
    testing or full reset scenarios.
    """
    async with get_es() as es:
        try:
            await es.indices.delete(index=INDEX_NAME, ignore_unavailable=True)
            logger.info("Deleted index '%s'", INDEX_NAME)
        except ESConnectionError:
            logger.warning("Elasticsearch connection failed — unable to delete index")
            raise AppException(status_code=503, message=_ES_UNAVAILABLE_MSG) from None


# ---------------------------------------------------------------------------
# Single-document operations
# ---------------------------------------------------------------------------


async def index_chunk(
    chunk_id: int,
    document_id: int,
    chunk_index: int,
    content: str,
    metadata: dict | None = None,
) -> None:
    """Index or update a single chunk document in Elasticsearch.

    The document ``_id`` is set to *chunk_id* so that re-indexing the
    same chunk idempotently updates the existing document.

    Args:
        chunk_id: Primary key of the ``DocumentChunk`` record.
        document_id: FK to the parent ``Document``.
        chunk_index: Ordinal position of the chunk within the document.
        content: Chunk text content.
        metadata: Optional arbitrary JSON metadata.

    """
    async with get_es() as es:
        doc: dict[str, Any] = {
            "id": chunk_id,
            "document_id": document_id,
            "chunk_index": chunk_index,
            "content": content,
            "metadata": metadata,
            "created_at": datetime.now(UTC).isoformat(),
        }
        try:
            await es.index(index=INDEX_NAME, id=chunk_id, body=doc)
            logger.debug("Indexed chunk %d (document_id=%d)", chunk_id, document_id)
        except ESConnectionError:
            logger.warning(
                "Elasticsearch connection failed — unable to index chunk %d",
                chunk_id,
            )
            raise AppException(status_code=503, message=_ES_UNAVAILABLE_MSG) from None


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


async def bulk_index_chunks(chunks: list[dict]) -> None:
    """Bulk-index multiple chunk documents into Elasticsearch.

    Each dict in *chunks* must contain the keys: ``id``,
    ``document_id``, ``chunk_index``, ``content``, and optionally
    ``metadata``.

    Args:
        chunks: A list of chunk dicts to index.

    Raises:
        AppException: If Elasticsearch is unreachable (503).

    """
    actions: list[dict[str, Any]] = [
        {
            "_index": INDEX_NAME,
            "_id": chunk["id"],
            "_source": {
                "id": chunk["id"],
                "document_id": chunk["document_id"],
                "chunk_index": chunk["chunk_index"],
                "content": chunk["content"],
                "metadata": chunk.get("metadata"),
                "created_at": datetime.now(UTC).isoformat(),
            },
        }
        for chunk in chunks
    ]

    if not actions:
        logger.debug("bulk_index_chunks called with empty list — nothing to do")
        return

    async with get_es() as es:
        try:
            success, errors = await async_bulk(es, actions, raise_on_error=False)
            if errors:
                logger.warning(
                    "%d / %d chunks failed to index (sample: %s)",
                    len(actions) - success,
                    len(actions),
                    errors[:3] if isinstance(errors, list) else str(errors)[:300],
                )
            else:
                logger.info("Bulk-indexed %d / %d chunks", success, len(actions))
        except ESConnectionError:
            logger.warning("Elasticsearch connection failed — unable to bulk-index chunks")
            raise AppException(status_code=503, message=_ES_UNAVAILABLE_MSG) from None


async def delete_document_chunks(doc_id: int) -> None:
    """Delete all Elasticsearch documents belonging to a document.

    Uses a ``term`` query on the ``document_id`` field. The operation
    is idempotent — it succeeds even if no chunks exist.

    Args:
        doc_id: The ``Document.id`` whose chunks should be removed.

    Raises:
        AppException: If Elasticsearch is unreachable (503).

    """
    async with get_es() as es:
        try:
            await es.delete_by_query(
                index=INDEX_NAME,
                body={"query": {"term": {"document_id": doc_id}}},
                refresh=True,
            )
            logger.info("Deleted all ES chunks for document_id=%d", doc_id)
        except ESNotFoundError:
            # Index does not exist yet — nothing to delete
            logger.debug(
                "Index '%s' not found — skipping delete for doc_id=%d",
                INDEX_NAME,
                doc_id,
            )
        except ESConnectionError:
            logger.warning(
                "Elasticsearch connection failed — unable to delete document chunks",
            )
            raise AppException(status_code=503, message=_ES_UNAVAILABLE_MSG) from None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def search_fulltext(
    query: str,
    page: int = 1,
    size: int = 10,
    doc_id: int | None = None,
) -> dict[str, Any]:
    """Run a BM25 full-text search against the ``content`` field.

    Args:
        query: The user's search query text.
        page: 1-indexed page number (default 1).
        size: Results per page (default 10, max 100).
        doc_id: If provided, restrict results to a single document.

    Returns:
        A dict with:

        - ``results``: list of hit dicts containing ``chunk_id``,
          ``document_id``, ``chunk_index``, ``content``, ``metadata``,
          and ``score``.
        - ``total``: total number of matching documents.
        - ``page``: the requested page number.
        - ``size``: the requested page size.

    Raises:
        AppException: If Elasticsearch is unreachable (503).

    """
    page = max(page, 1)
    size = max(size, 1)
    size = min(size, 100)

    must: list[dict] = [{"match": {"content": query}}]
    filters: list[dict] = []

    if doc_id is not None:
        filters.append({"term": {"document_id": doc_id}})

    body: dict[str, Any] = {
        "query": {"bool": {"must": must}},
        "from": (page - 1) * size,
        "size": size,
    }
    if filters:
        body["query"]["bool"]["filter"] = filters  # type: ignore[call-overload]

    async with get_es() as es:
        try:
            resp = await es.search(index=INDEX_NAME, body=body)
        except ESConnectionError:
            logger.warning("Elasticsearch connection failed — unable to search")
            raise AppException(status_code=503, message=_ES_UNAVAILABLE_MSG) from None

    total = resp["hits"]["total"]["value"] if "total" in resp["hits"] else 0
    results = [
        {
            "chunk_id": hit["_source"]["id"],
            "document_id": hit["_source"]["document_id"],
            "chunk_index": hit["_source"]["chunk_index"],
            "content": hit["_source"]["content"],
            "metadata": hit["_source"].get("metadata"),
            "score": hit["_score"],
        }
        for hit in resp["hits"]["hits"]
    ]

    return {
        "results": results,
        "total": total,
        "page": page,
        "size": size,
    }
