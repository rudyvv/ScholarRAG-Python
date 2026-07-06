"""Document processing tasks — parse, chunk, and vectorize documents asynchronously."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from celery import shared_task

from app.config import settings
from app.db.session import sync_session_factory
from app.models.document import DocStatus, Document, DocumentChunk
from app.services.document_chunker import DocumentChunker
from app.services.document_parser import DocumentParser
from app.services.embedding_service import generate_embeddings
from app.services.search_service import bulk_index_chunks
from app.services.storage_service import StorageService
from app.services.vector_store import MilvusClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent event loop for Celery tasks
# ---------------------------------------------------------------------------
# Celery workers run synchronous task functions.  We need async for
# network I/O (ES, Milvus, MinIO, embedding API).  Instead of creating
# and destroying an event loop per task with ``asyncio.run()`` (which
# leaks aiohttp client sessions), we use a persistent event loop that
# lives across task invocations within the same worker process.

_shared_loop: asyncio.AbstractEventLoop | None = None


def _run_async(coro) -> Any:
    """Run a coroutine in a persistent event loop.

    Reuses the same event loop across Celery task invocations so that
    aiohttp / ES client sessions are properly managed and don't leak.
    """
    global _shared_loop  # noqa: PLW0603
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_shared_loop)
    return _shared_loop.run_until_complete(coro)


@shared_task(
    name="process_document",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    queue="documents",
    soft_time_limit=1800,
    time_limit=2100,
)
def process_document_task(self, document_id: int) -> dict:  # noqa: ARG001 - required by Celery bind=True
    """Parse, chunk, and persist a document.

    Steps:
        1. Fetch the Document from DB.
        2. Download the file from MinIO.
        3. Parse with DocumentParser.
        4. Chunk with DocumentChunker.
        5. Save chunks to DB.
        6. Chain-call vectorize_chunks_task.
    """
    temp_path: str | None = None
    db = sync_session_factory()
    try:
        # ------------------------------------------------------------------
        # 1. Fetch document
        # ------------------------------------------------------------------
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            logger.warning("Document %d not found, aborting", document_id)
            return {
                "status": "skipped",
                "document_id": document_id,
                "reason": "not_found",
            }
        if doc.doc_status == DocStatus.READY:
            logger.info("Document %d already ready, skipping", document_id)
            return {
                "status": "skipped",
                "document_id": document_id,
                "reason": "already_ready",
            }

        # ------------------------------------------------------------------
        # 2. Mark as PROCESSING
        # ------------------------------------------------------------------
        doc.doc_status = DocStatus.PROCESSING
        db.commit()

        # ------------------------------------------------------------------
        # 3. Download file + parse + chunk + index to ES (single async pass)
        # ------------------------------------------------------------------
        storage = StorageService(settings)
        file_type = Path(doc.filename).suffix.lstrip(".").lower()

        async def _process() -> tuple[list[dict], list[int]]:
            """Download, parse, chunk, and bulk-index to ES in one async pass."""
            nonlocal temp_path
            temp_path = await storage.download_file(doc.storage_path)

            # Parse
            parser = DocumentParser()
            parse_result = parser.parse_document(temp_path, file_type)
            text = parse_result["text"]
            metadata = parse_result["metadata"]

            # Chunk — type-aware
            chunker = DocumentChunker(chunk_size=512, chunk_overlap=128)
            chunks = chunker.chunk_document(text, file_type=file_type, metadata=metadata)

            # Save chunks to DB
            _saved_chunks: list[DocumentChunk] = []
            for chunk_data in chunks:
                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_data["chunk_index"],
                    content=chunk_data["content"],
                    chunk_metadata=chunk_data.get("metadata"),
                )
                db.add(chunk)
                _saved_chunks.append(chunk)
            db.flush()

            # Bulk-index to ES
            es_chunks = [
                {
                    "id": c.id,
                    "document_id": document_id,
                    "chunk_index": c.chunk_index,
                    "content": c.content,
                }
                for c in _saved_chunks
            ]
            try:
                await bulk_index_chunks(es_chunks)
                logger.info(
                    "Indexed %d chunks to ES for doc %d",
                    len(es_chunks), document_id,
                )
            except Exception:
                logger.exception(
                    "ES indexing failed for doc %d (non-fatal)", document_id,
                )

            return es_chunks, [c.id for c in _saved_chunks]

        es_chunks, chunk_ids = _run_async(_process())

        # ------------------------------------------------------------------
        # 8. Update document status
        # ------------------------------------------------------------------
        doc.chunk_count = len(chunk_ids)
        doc.doc_status = DocStatus.READY
        db.commit()

        # ------------------------------------------------------------------
        # 9. Chain vectorize task
        # ------------------------------------------------------------------
        vectorize_chunks_task.delay(document_id, chunk_ids)

        logger.info(
            "Document %d processed: %d chunks, queued for vectorization",
            document_id,
            len(chunk_ids),
        )
        return {
            "status": "success",
            "document_id": document_id,
            "chunk_count": len(chunk_ids),
        }

    except Exception:
        logger.exception("Failed to process document %d", document_id)
        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc is not None:
                doc.doc_status = DocStatus.FAILED
                db.commit()
        except Exception:
            db.rollback()
        return {"status": "failed", "document_id": document_id}

    finally:
        db.close()
        if temp_path is not None:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to clean up temp file: %s", temp_path)


@shared_task(
    name="vectorize_chunks",
    queue="embeddings",
    soft_time_limit=300,
    time_limit=600,
)
def vectorize_chunks_task(document_id: int, chunk_ids: list[int]) -> dict:
    """Generate embeddings for document chunks and store in Milvus."""
    db = sync_session_factory()
    try:
        # ── Fetch chunk content from DB ────────────────────────────────
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.document_id == document_id,
            )
            .all()
        )
        if not chunks:
            logger.warning(
                "No chunks found for doc %d, ids: %s", document_id, chunk_ids
            )
            return {
                "status": "skipped",
                "document_id": document_id,
                "reason": "no_chunks",
            }

        async def _vectorize() -> None:
            """Generate embeddings and store in Milvus in one async pass."""
            texts = [c.content for c in chunks]

            # Generate embeddings
            embeddings = await generate_embeddings(texts)
            logger.info(
                "Generated %d embeddings (dim=%d) for doc %d",
                len(embeddings),
                len(embeddings[0]) if embeddings else 0,
                document_id,
            )

            # Store in Milvus
            vector_items = [
                {
                    "chunk_id": c.id,
                    "doc_id": document_id,
                    "chunk_index": c.chunk_index,
                    "content": c.content,
                    "embedding": emb,
                }
                for c, emb in zip(chunks, embeddings, strict=False)
            ]

            client = MilvusClient()
            try:
                await client.add_batch(vector_items)
            finally:
                client.close()

        _run_async(_vectorize())
        logger.info(
            "Stored %d vectors in Milvus for doc %d",
            len(chunk_ids), document_id,
        )

        return {
            "status": "success",
            "document_id": document_id,
            "chunk_count": len(chunks),
        }

    except Exception:
        logger.exception("Vectorization failed for doc %d", document_id)
        return {"status": "failed", "document_id": document_id}

    finally:
        db.close()
