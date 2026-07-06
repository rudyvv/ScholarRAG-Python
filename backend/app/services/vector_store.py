"""Milvus vector store for document chunk embeddings.

Provides a ``MilvusClient`` wrapper that manages the ``document_chunks``
collection — creating the schema on first use, inserting/querying
vector embeddings, and deleting by document or chunk ID.

Under the hood it uses the synchronous ``pymilvus.MilvusClient``; all
public methods are async so they integrate cleanly with FastAPI's
event loop.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

from pymilvus import (
    DataType,
)
from pymilvus import (
    MilvusClient as _PyMilvusClient,
)

from app.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

__all__ = [
    "MilvusClient",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_COLLECTION = "document_chunks"
_EMBEDDING_DIM: int = settings.EMBEDDING_DIM  # 1024
_MILVUS_TIMEOUT: int = 30  # seconds for thread-pool operations


# ---------------------------------------------------------------------------
# Milvus client
# ---------------------------------------------------------------------------


class MilvusClient:
    """Async-friendly wrapper around the synchronous ``pymilvus.MilvusClient``.

    Manages a single ``document_chunks`` collection that stores chunk
    text together with its float32 vector embedding.  The collection is
    created on the first instantiation if it does not already exist.

    Args:
        host: Milvus server hostname (defaults to ``settings.MILVUS_HOST``).
        port: Milvus server port (defaults to ``settings.MILVUS_PORT``).
        collection_name: Name of the collection to manage.

    Raises:
        AppException: If the Milvus connection or schema creation fails.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection_name: str = _DEFAULT_COLLECTION,
    ) -> None:
        self.host: str = host or settings.MILVUS_HOST
        self.port: int = port or settings.MILVUS_PORT
        self.collection_name: str = collection_name

        self._client: _PyMilvusClient = _PyMilvusClient(
            uri=f"http://{self.host}:{self.port}",
        )
        self.ensure_collection()

    # -------------------------------------------------------------------
    # Async helper — run sync Milvus calls in a thread pool with timeout
    # -------------------------------------------------------------------

    async def _run(self, func, *args, **kwargs):
        """Run a sync function in the thread pool with a timeout.

        Args:
            func: A callable (typically ``functools.partial``).
            *args: Positional args forwarded to ``func``.
            **kwargs: Keyword args forwarded to ``func``.

        Returns:
            The return value of *func*.

        Raises:
            AppException(503): On timeout or any other exception.
        """
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, functools.partial(func, *args, **kwargs)),
                timeout=_MILVUS_TIMEOUT,
            )
        except TimeoutError:
            logger.warning("Milvus operation timed out after %ss", _MILVUS_TIMEOUT)
            raise AppException(
                status_code=503,
                message="Milvus operation timed out",
            ) from None
        except Exception as exc:
            raise AppException(
                status_code=503,
                message="Milvus operation failed",
            ) from exc

    # -------------------------------------------------------------------
    # Collection lifecycle
    # -------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the collection if it does not already exist.

        Schema:

        ============  =============  ===================================
        Field         Type           Notes
        ============  =============  ===================================
        chunk_id      INT64          Primary key, ``auto_id=False``
        doc_id        INT64          Foreign key to ``Document.id``
        chunk_index   INT64          Ordinal position within the document
        content       VARCHAR(65535) Raw chunk text
        embedding     FLOAT_VECTOR   Dimension = EMBEDDING_DIM (1024)
        ============  =============  ===================================

        An IVF_FLAT index with IP (inner-product) metric is built on the
        embedding field for approximate nearest-neighbour search.

        Raises:
            AppException: If creation fails (connection error, etc.).
        """
        try:
            if self._client.has_collection(self.collection_name):
                logger.info(
                    "Collection '%s' already exists — skipping creation",
                    self.collection_name,
                )
                return

            schema = _PyMilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(
                field_name="chunk_id",
                datatype=DataType.INT64,
                is_primary=True,
            )
            schema.add_field(field_name="doc_id", datatype=DataType.INT64)
            schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
            schema.add_field(
                field_name="content",
                datatype=DataType.VARCHAR,
                max_length=65535,
            )
            schema.add_field(
                field_name="embedding",
                datatype=DataType.FLOAT_VECTOR,
                dim=_EMBEDDING_DIM,
            )

            index_params = _PyMilvusClient.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type="IP",
                params={"nlist": 128},
            )

            self._client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
            )
            logger.info("Created collection '%s'", self.collection_name)
        except Exception as exc:
            logger.warning(
                "Failed to initialise collection '%s': %s",
                self.collection_name,
                exc,
            )
            raise AppException(
                status_code=503,
                message="Milvus is not available",
            ) from exc

    # -------------------------------------------------------------------
    # Insert
    # -------------------------------------------------------------------

    async def add_chunk(
        self,
        chunk_id: int,
        embedding: list[float],
        doc_id: int,
        chunk_index: int,
        content: str,
    ) -> None:
        """Insert a single chunk embedding into the collection.

        Args:
            chunk_id: Primary key for the chunk.
            embedding: Float embedding vector (must match ``_EMBEDDING_DIM``).
            doc_id: Foreign key referencing the parent ``Document``.
            chunk_index: Ordinal position of the chunk within its document.
            content: Raw chunk text.

        Raises:
            AppException: If the insert operation fails.
        """
        data: dict[str, Any] = {
            "chunk_id": chunk_id,
            "embedding": embedding,
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "content": content,
        }
        try:
            await self._run(
                self._client.insert,
                collection_name=self.collection_name,
                data=data,
            )
            logger.debug("Inserted chunk %d (doc_id=%d)", chunk_id, doc_id)
        except AppException:
            raise
        except Exception as exc:
            logger.warning("Failed to insert chunk %d: %s", chunk_id, exc)
            raise AppException(
                status_code=503,
                message="Milvus insert failed",
            ) from exc

    async def add_batch(self, entries: list[dict]) -> None:
        """Insert multiple chunk embeddings in a single batch.

        Each dict in *entries* must contain the keys ``chunk_id``,
        ``embedding``, ``doc_id``, ``chunk_index``, and ``content``.

        Args:
            entries: A list of chunk dicts to insert.

        Raises:
            AppException: If the batch insert fails.
        """
        if not entries:
            logger.debug("add_batch called with empty list — nothing to do")
            return

        try:
            await self._run(
                self._client.insert,
                collection_name=self.collection_name,
                data=entries,
            )
            logger.info("Batch-inserted %d chunks", len(entries))
        except AppException:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to batch-insert %d chunks: %s",
                len(entries),
                exc,
            )
            raise AppException(
                status_code=503,
                message="Milvus batch insert failed",
            ) from exc

    # -------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------

    async def search(
        self,
        embedding: list[float],
        top_k: int = 10,
        doc_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search for the nearest neighbours of an embedding vector.

        Args:
            embedding: Query embedding vector (must match ``_EMBEDDING_DIM``).
            top_k: Number of nearest neighbours to return.
            doc_id: If provided, restrict results to chunks belonging
                    to a specific document.

        Returns:
            A list of result dicts, each containing ``chunk_id``,
            ``doc_id``, ``chunk_index``, ``content``, and ``score``.

        Raises:
            AppException: If the search fails.
        """
        filter_expr: str = ""
        if doc_id is not None:
            filter_expr = f"doc_id == {doc_id}"

        try:
            raw = await self._run(
                self._client.search,
                collection_name=self.collection_name,
                data=[embedding],
                anns_field="embedding",
                limit=top_k,
                output_fields=["chunk_id", "doc_id", "chunk_index", "content"],
                search_params={
                    "metric_type": "IP",
                    "params": {"nprobe": 10},
                },
                filter=filter_expr,
            )
        except AppException:
            raise
        except Exception as exc:
            logger.warning("Milvus search failed: %s", exc)
            raise AppException(
                status_code=503,
                message="Milvus search failed",
            ) from exc

        results: list[dict[str, Any]] = []
        for hits in raw:
            for hit in hits:
                results.append({
                    "chunk_id": hit["chunk_id"],
                    "doc_id": hit["doc_id"],
                    "chunk_index": hit["chunk_index"],
                    "content": hit["content"],
                    "score": hit["distance"],
                })
        return results

    # -------------------------------------------------------------------
    # Delete
    # -------------------------------------------------------------------

    async def delete(self, doc_id: int) -> None:
        """Delete all chunks belonging to a document.

        Args:
            doc_id: The ``Document.id`` whose chunks should be removed.

        Raises:
            AppException: If the delete operation fails.
        """
        expr = f"doc_id == {doc_id}"
        try:
            await self._run(
                self._client.delete,
                collection_name=self.collection_name,
                filter=expr,
            )
            logger.info("Deleted all Milvus chunks for doc_id=%d", doc_id)
        except AppException:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to delete chunks for doc_id=%d: %s",
                doc_id,
                exc,
            )
            raise AppException(
                status_code=503,
                message="Milvus delete failed",
            ) from exc

    async def delete_chunks(self, chunk_ids: list[int]) -> None:
        """Delete specific chunks by their primary keys.

        Args:
            chunk_ids: List of ``chunk_id`` values to delete.

        Raises:
            AppException: If the delete operation fails.
        """
        if not chunk_ids:
            logger.debug("delete_chunks called with empty list — nothing to do")
            return

        try:
            await self._run(
                self._client.delete,
                collection_name=self.collection_name,
                ids=chunk_ids,
            )
            logger.info("Deleted %d specific chunks", len(chunk_ids))
        except AppException:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to delete %d chunks: %s",
                len(chunk_ids),
                exc,
            )
            raise AppException(
                status_code=503,
                message="Milvus delete failed",
            ) from exc

    # -------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------

    async def count(self, collection_name: str | None = None) -> int:
        """Return the entity count of a collection.

        Args:
            collection_name: Name of the collection (defaults to
                             ``self.collection_name``).

        Returns:
            Number of entities in the collection.

        Raises:
            AppException: If the query fails.
        """
        name = collection_name or self.collection_name
        try:
            result = await self._run(
                self._client.query,
                collection_name=name,
                output_fields=["count(*)"],
                filter="",
            )
        except AppException:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to count collection '%s': %s",
                name,
                exc,
            )
            raise AppException(
                status_code=503,
                message="Milvus count failed",
            ) from exc

        if result:
            return int(result[0]["count(*)"])
        return 0

    def close(self) -> None:
        """Release the underlying Milvus connection."""
        self._client.close()
        logger.info("Closed Milvus connection")
