"""Hybrid search API endpoint combining Elasticsearch BM25 + Milvus vector search.

Supports three modes:
- ``fulltext``: BM25 full-text search only (Elasticsearch).
- ``vector``: Vector similarity search only (Milvus).
- ``hybrid``: DBSF-style weighted fusion (0.3 BM25 + 0.7 vector).

Graceful degradation: if the Milvus ``vector_store`` module is not yet
available, vector-dependent modes fall back with an appropriate error
message while full-text mode continues to work.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.response import error_response, success_response
from app.models.document import Document
from app.models.user import User
from app.services.embedding_service import generate_embedding
from app.services.search_service import search_fulltext

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    """Search request payload."""

    query: str = Field(..., min_length=1, description="Search query text")
    mode: Literal["hybrid", "fulltext", "vector"] = Field(
        default="hybrid",
        description="Search mode: hybrid (default), fulltext, or vector",
    )
    page: int = Field(default=1, ge=1, description="1-indexed page number")
    size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Results per page (max 100)",
    )
    doc_id: int | None = Field(
        default=None,
        description="Optional: restrict search to a single document",
    )


class SearchResultItem(BaseModel):
    """Single search hit."""

    chunk_id: int
    document_id: int
    filename: str
    content: str
    score: float
    match_type: Literal["fulltext", "vector", "hybrid"]


class SearchResponse(BaseModel):
    """Paginated search response."""

    items: list[SearchResultItem]
    total: int
    page: int
    size: int
    query: str


# ---------------------------------------------------------------------------
# Lazy Milvus client (graceful degradation)
# ---------------------------------------------------------------------------

_milvus_client: Any | None = None
_MILVUS_UNAVAILABLE_MSG = "vector search unavailable"


def _get_milvus_client() -> Any | None:
    """Return the MilvusClient singleton, or ``None`` if unavailable.

    Graceful degradation: if ``app.services.vector_store.MilvusClient``
    cannot be imported (not yet created or not installed), this function
    returns ``None`` and callers fall back gracefully.
    """
    global _milvus_client  # noqa: PLW0603
    if _milvus_client is not None:
        return _milvus_client

    try:
        from app.services.vector_store import MilvusClient  # noqa: I001
        from app.config import settings  # noqa: I001
    except ImportError:
        logger.warning("MilvusClient not available — vector search degraded")
        return None

    try:
        _milvus_client = MilvusClient(
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )
        logger.info(
            "Milvus client initialised (%s:%s)",
            settings.MILVUS_HOST,
            settings.MILVUS_PORT,
        )
    except Exception:
        logger.exception("Failed to initialise Milvus client")
        return None
    else:
        return _milvus_client


# ---------------------------------------------------------------------------
# Score normalisation helpers
# ---------------------------------------------------------------------------



def _map_to_result_items(
    raw_items: list[dict],
    filename_map: dict[int, str],
    match_type: Literal["fulltext", "vector"],
) -> list[SearchResultItem]:
    """Map raw search hits to ``SearchResultItem`` instances."""
    return [
        SearchResultItem(
            chunk_id=it["chunk_id"],
            document_id=it["document_id"],
            filename=filename_map.get(it["document_id"], ""),
            content=it["content"],
            score=it.get("score") or 0.0,
            match_type=match_type,
        )
        for it in raw_items
    ]


async def _build_filename_map(
    db: AsyncSession,
    doc_ids: set[int],
) -> dict[int, str]:
    """Build a ``{document_id: filename}`` lookup from the database.

    Returns an empty dict on any DB failure so search results are never
    blocked by a filename lookup error.
    """
    if not doc_ids:
        return {}
    try:
        result = await db.execute(
            select(Document.id, Document.filename).where(
                Document.id.in_(doc_ids),
            ),
        )
        return {row[0]: row[1] for row in result.all()}
    except Exception:
        logger.warning("Failed to fetch filenames for %d documents", len(doc_ids))
        return {}


# ---------------------------------------------------------------------------
# Hybrid fusion
# ---------------------------------------------------------------------------


def _fuse_hybrid(
    ft_items: list[dict],
    vec_items: list[dict],
    filename_map: dict[int, str],
    page: int,
    size: int,
    query: str,
) -> SearchResponse:
    """Fuse full-text and vector results with RRF (Reciprocal Rank Fusion).

    RRF only depends on the rank position of each item in each result
    set, not on the raw score values.  This makes it robust to
    differences in score distributions between BM25 and vector cosine
    similarity.

    Steps:
    1. Build rank maps (chunk_id → 1-based rank) for each backend.
    2. Compute RRF score: ``1 / (k + rank_ft) + 1 / (k + rank_vec)``.
    3. Sort by descending RRF score.
    4. Paginate.
    """
    k = 60  # RRF constant (same as rag_service)

    ft_ranks: dict[int, int] = {
        it["chunk_id"]: i + 1 for i, it in enumerate(ft_items)
    }
    vec_ranks: dict[int, int] = {
        it["chunk_id"]: i + 1 for i, it in enumerate(vec_items)
    }

    all_ids = set(ft_ranks) | set(vec_ranks)

    # Build a deduplicated lookup for document_id / content
    by_id: dict[int, dict[str, Any]] = {}
    for it in ft_items:
        by_id[it["chunk_id"]] = it
    for it in vec_items:
        by_id.setdefault(it["chunk_id"], it)  # prefer fulltext entry

    scored: list[dict[str, Any]] = []
    for cid in all_ids:
        entry = by_id[cid]
        rrf = 0.0
        match_type: str = ""
        if cid in ft_ranks:
            rrf += 1.0 / (k + ft_ranks[cid])
            match_type = "fulltext"
        if cid in vec_ranks:
            rrf += 1.0 / (k + vec_ranks[cid])
            match_type = "hybrid" if match_type else "vector"
        scored.append({
            "chunk_id": cid,
            "document_id": entry["document_id"],
            "content": entry["content"],
            "score": rrf,
            "match_type": match_type,
        })

    # Sort by descending RRF score
    scored.sort(key=lambda x: x["score"], reverse=True)
    total = len(scored)

    # Paginate
    start = (page - 1) * size
    page_slice = scored[start : start + size]

    items = [
        SearchResultItem(
            chunk_id=it["chunk_id"],
            document_id=it["document_id"],
            filename=filename_map.get(it["document_id"], ""),
            content=it["content"],
            score=it["score"],
            match_type=it["match_type"],
        )
        for it in page_slice
    ]

    return SearchResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        query=query,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("")
@router.post("/hybrid")
async def api_search(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008, ARG001
):
    """Perform a hybrid search across document chunks.

    **Request body** (``SearchRequest``):
      - ``query``: Search query text (required, min 1 char).
      - ``mode``: ``"hybrid"`` (default), ``"fulltext"``, or ``"vector"``.
      - ``page``: 1-indexed page number.
      - ``size``: Results per page (max 100).
      - ``doc_id``: Optional document ID to restrict results.

    **Responses**:
      - ``200``: ``SearchResponse`` with paginated results.
      - ``503``: Vector search unavailable (vector mode with no Milvus).
    """
    page = body.page
    size = body.size
    query = body.query

    # ── Full-text search (Elasticsearch BM25) ──────────────────────────
    ft_items: list[dict] = []
    ft_total: int = 0
    if body.mode in ("fulltext", "hybrid"):
        try:
            ft_result = await search_fulltext(query, page, size, body.doc_id)
            ft_items = ft_result["results"]
            ft_total = ft_result["total"]
        except Exception:
            logger.exception("Full-text search failed")
            ft_items = []
            ft_total = 0

    # ── Vector search (Milvus) ────────────────────────────────────────
    vec_items: list[dict] = []
    if body.mode in ("vector", "hybrid"):
        client = _get_milvus_client()
        if client is None:
            if body.mode == "vector":
                return error_response(
                    message=_MILVUS_UNAVAILABLE_MSG,
                    status_code=503,
                )
            # Hybrid mode — degrade gracefully with only fulltext results
            logger.warning("Milvus unavailable — hybrid degraded to fulltext")
        else:
            try:
                embedding = await generate_embedding(query)
                raw = await client.search(
                    embedding=embedding,
                    top_k=size,
                    doc_id=body.doc_id,
                )
                # Normalise the response shape (list of dicts, or dict with "results")
                if isinstance(raw, dict):
                    vec_items = raw.get("results", [])
                else:
                    vec_items = list(raw)
            except Exception:
                logger.exception("Vector search failed")
                if body.mode == "vector":
                    return error_response(
                        message="vector search failed",
                        status_code=502,
                    )
                # Hybrid mode — continue with fulltext only
                vec_items = []

    # ── Build response ────────────────────────────────────────────────

    # Batch-lookup filenames for all referenced document IDs
    all_doc_ids: set[int] = set()
    for it in ft_items:
        all_doc_ids.add(it["document_id"])
    for it in vec_items:
        all_doc_ids.add(it["document_id"])
    filename_map = await _build_filename_map(db, all_doc_ids)

    if body.mode == "hybrid":
        return success_response(
            data=_fuse_hybrid(ft_items, vec_items, filename_map, page, size, query),
        )

    if body.mode == "fulltext":
        items = _map_to_result_items(ft_items, filename_map, "fulltext")
        total = ft_total
    else:
        items = _map_to_result_items(vec_items, filename_map, "vector")
        total = len(vec_items)

    return success_response(
        data=SearchResponse(
            items=items,
            total=total,
            page=page,
            size=size,
            query=query,
        ),
    )
