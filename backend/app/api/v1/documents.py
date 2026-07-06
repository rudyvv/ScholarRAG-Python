"""Document upload API endpoints.

Provides chunked upload with resume support and document management.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis_manager as _redis_mgr
from app.config import settings
from app.core.deps import get_current_user, get_db, get_redis
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.redis_manager import RedisManager
from app.core.response import success_response
from app.core.security import decode_access_token
from app.models.document import Document
from app.models.user import User, UserRole
from app.services.document_service import (
    check_document_dedup,
    complete_upload,
    delete_document,
    get_document,
    get_document_chunks,
    get_download_url,
    get_upload_status,
    init_upload,
    list_documents,
    upload_chunk,
)
from app.services.storage_service import StorageService
from app.tasks.document_tasks import process_document_task

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InitUploadRequest(BaseModel):
    filename: str
    file_size: int
    file_md5: str
    content_type: str


class CompleteUploadRequest(BaseModel):
    upload_id: str


class VisibilityRequest(BaseModel):
    is_public: bool


class DocumentItem(BaseModel):
    """Lightweight document model for list/detail responses."""

    id: int
    filename: str
    file_size: int
    content_type: str | None
    doc_status: str
    is_public: bool
    chunk_count: int
    created_at: str | None
    updated_at: str | None


def _document_to_item(doc: Document) -> DocumentItem:
    """Convert a Document ORM instance to a serialisable Pydantic model."""
    return DocumentItem(
        id=doc.id,
        filename=doc.filename,
        file_size=doc.file_size,
        content_type=doc.content_type,
        doc_status=doc.doc_status.value if doc.doc_status else "unknown",
        is_public=doc.is_public,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
        updated_at=doc.updated_at.isoformat() if doc.updated_at else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upload/init")
async def api_init_upload(
    body: InitUploadRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisManager = Depends(get_redis),
    current_user: User = Depends(get_current_user),
):
    """Initialise a chunked upload session.

    Checks for duplicate files (by MD5 + user) before starting.
    """
    # Dedup check (skip if MD5 is empty, since browser can't compute MD5)
    if body.file_md5:
        existing = await check_document_dedup(
            db,
            user_id=current_user.id,
            file_md5=body.file_md5,
        )
        if existing is not None:
            return success_response(
                data={
                    "duplicate": True,
                    "document_id": existing.id,
                    "message": "File already uploaded",
                },
            )

    storage = StorageService(settings)
    result = await init_upload(
        redis,
        storage,
        filename=body.filename,
        file_size=body.file_size,
        file_md5=body.file_md5,
        content_type=body.content_type,
        user_id=current_user.id,
    )

    return success_response(
        data={
            "upload_id": result["upload_id"],
            "chunk_size": result["chunk_size"],
            "duplicate": False,
        },
    )


@router.post("/upload/chunk")
async def api_upload_chunk(
    upload_id: str = Form(...),
    chunk_number: int = Form(...),
    file: UploadFile = File(...),
    redis: RedisManager = Depends(get_redis),
    current_user: User = Depends(get_current_user),
):
    """Upload a single chunk of a file."""
    data = await file.read()

    storage = StorageService(settings)
    result = await upload_chunk(
        redis,
        storage,
        upload_id=upload_id,
        chunk_number=chunk_number,
        data=data,
        user_id=current_user.id,
    )

    return success_response(
        data={
            "chunk_number": result["chunk_number"],
            "received": True,
        },
    )


@router.post("/upload/complete")
async def api_complete_upload(
    body: CompleteUploadRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisManager = Depends(get_redis),
    current_user: User = Depends(get_current_user),
):
    """Finalise a chunked upload and submit document for async processing."""
    storage = StorageService(settings)
    # Inherit org tags from the uploading user (store all, semicolon-separated)
    upload_org_tag = current_user.org_tags if current_user.org_tags else None
    result = await complete_upload(
        redis,
        storage,
        db,
        upload_id=body.upload_id,
        user_id=current_user.id,
        org_tag=upload_org_tag,
    )

    doc_id = result["document_id"]

    # Submit to Celery async pipeline
    async_result = process_document_task.delay(doc_id)
    task_id = async_result.id

    # Store task→document mapping in Redis for progress tracking
    if _redis_mgr.redis_manager is not None:
        await _redis_mgr.redis_manager.set_key(
            f"doc_task:{doc_id}", task_id, expire=86400
        )

    return success_response(
        data={
            "document_id": doc_id,
            "task_id": task_id,
            "status": "PENDING",
        },
    )


@router.get("/upload/status/{upload_id}")
async def api_upload_status(
    upload_id: str,
    redis: RedisManager = Depends(get_redis),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Return the current progress of an active upload session."""
    result = await get_upload_status(redis, upload_id=upload_id)

    return success_response(data=result)


@router.delete("/{document_id}")
async def api_delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document and its backing storage object."""
    storage = StorageService(settings)
    await delete_document(
        db,
        storage,
        document_id=document_id,
        user_id=current_user.id,
    )

    return success_response(message="Document deleted")


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------


@router.get("/")
async def api_list_documents(
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List documents with org-based access control.

    - Admin: all documents.
    - Regular user: own docs + public docs from same org.
    """
    is_admin = current_user.role == UserRole.ADMIN
    user_org_tags = (
        [t.strip() for t in current_user.org_tags.split(";") if t.strip()]
        if current_user.org_tags
        else None
    )

    result = await list_documents(
        db,
        user_id=current_user.id,
        is_admin=is_admin,
        user_org_tags=user_org_tags,
        org_tag=None,
        status=status,
        page=page,
        size=size,
    )

    return success_response(
        data={
            "items": result["items"],
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
        },
    )


@router.get("/{document_id}")
async def api_get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return detailed information about a single document."""
    is_admin = current_user.role == UserRole.ADMIN
    user_org_tags = (
        [t.strip() for t in current_user.org_tags.split(";") if t.strip()]
        if current_user.org_tags
        else None
    )
    doc = await get_document(
        db, document_id, current_user.id, is_admin=is_admin, user_org_tags=user_org_tags
    )

    return success_response(
        data={
            "id": doc.id,
            "filename": doc.filename,
            "file_size": doc.file_size,
            "content_type": doc.content_type,
            "doc_status": doc.doc_status.value,
            "is_public": doc.is_public,
            "org_tag": doc.org_tag,
            "chunk_count": doc.chunk_count,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        },
    )


@router.put("/{document_id}/visibility")
async def api_update_visibility(
    document_id: int,
    body: VisibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle whether a document is publicly accessible.

    Only the document owner can change visibility.
    """
    is_admin = current_user.role == UserRole.ADMIN
    user_org_tags = (
        [t.strip() for t in current_user.org_tags.split(";") if t.strip()]
        if current_user.org_tags
        else None
    )
    doc = await get_document(
        db,
        document_id=document_id,
        user_id=current_user.id,
        is_admin=is_admin,
        user_org_tags=user_org_tags,
    )
    # Only owner or admin can toggle visibility
    if not is_admin and doc.user_id != current_user.id:
        raise ForbiddenException("You do not have permission to change this document's visibility")
    doc.is_public = body.is_public
    await db.commit()
    await db.refresh(doc)
    return success_response(
        data={"is_public": doc.is_public},
        message="Visibility updated",
    )


@router.get("/{document_id}/chunks")
async def api_get_document_chunks(
    document_id: int,
    page: int = 1,
    size: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the text chunks belonging to a document."""
    is_admin = current_user.role == UserRole.ADMIN
    user_org_tags = (
        [t.strip() for t in current_user.org_tags.split(";") if t.strip()]
        if current_user.org_tags
        else None
    )
    result = await get_document_chunks(
        db,
        document_id=document_id,
        user_id=current_user.id,
        is_admin=is_admin,
        user_org_tags=user_org_tags,
        page=page,
        size=size,
    )

    return success_response(data=result)


@router.get("/{document_id}/download")
async def api_get_download_url(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a presigned download URL for the document's source file."""
    storage = StorageService(settings)
    url = await get_download_url(
        db,
        storage,
        document_id=document_id,
        user_id=current_user.id,
    )

    return success_response(
        data={
            "url": url,
            "filename": (
                await get_document(
                    db,
                    document_id=document_id,
                    user_id=current_user.id,
                )
            ).filename,
        },
    )


# ── Streaming helpers ────────────────────────────────────────────────────────


_CHUNK_SIZE = 64 * 1024  # 64 KiB


async def _iter_minio_stream(response):
    """Async-generator that yields chunks from a synchronous MinIO stream."""
    try:
        while True:
            chunk = await asyncio.to_thread(response.read, _CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(response.close)
        await asyncio.to_thread(response.release_conn)


async def _log_access(user_id: int, doc_id: int, username: str) -> None:
    """Log document access to Redis — key: ``access_log:{doc_id}``.

    Each entry is ``{user_id}:{username}:{timestamp}``.
    At most 100 entries are kept per document.
    """
    logger.debug(
        "_log_access called: user_id=%s doc_id=%s username=%s",
        user_id,
        doc_id,
        username,
    )
    if _redis_mgr.redis_manager is None:
        logger.debug("_log_access: redis_manager is None, skipping")
        return
    try:
        timestamp = datetime.now(timezone.utc).isoformat()  # noqa: UP017 - need timezone.utc, not datetime.UTC, due to shadowed import
        entry = f"{user_id}:{username}:{timestamp}"
        await _redis_mgr.redis_manager.rpush(f"access_log:{doc_id}", entry)
        # Keep only last 100 entries per document
        await _redis_mgr.redis_manager.ltrim(f"access_log:{doc_id}", -100, -1)
    except Exception as exc:
        logger.warning("Access log failed for doc_id=%d: %s", doc_id, exc)


# ── Preview endpoint ─────────────────────────────────────────────────────────


@router.get("/{document_id}/preview")
async def api_preview_document(
    document_id: int,
    request: Request,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Stream a document file for in-browser preview.

    Supports:
    - Range requests (``206`` partial content) for PDF viewers.
    - ETag caching via ``If-None-Match`` (returns ``304``).
    - Authentication via ``Authorization`` header **or** ``?token=xxx``
      query parameter (for iframe/blob embeds that can't set headers).

    Returns the full file (``200``) or a byte range (``206``).
    """
    # ── Authentication: header first, then query param ──────────────────
    auth_token: str | None = token or None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth_token = auth_header[7:]

    if not auth_token:
        raise UnauthorizedException("Not authenticated")

    payload = decode_access_token(auth_token)
    if payload is None:
        raise UnauthorizedException("Invalid or expired token")

    current_user_id: int = int(payload["sub"])  # type: ignore[arg-type]
    # Fetch minimal user info for access log
    current_user_obj = await db.get(User, current_user_id)

    # ── Fetch document ─────────────────────────────────────────────────
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundException("Document not found")

    # Permission check — owner or public document
    if document.user_id != current_user_id and not document.is_public:
        raise ForbiddenException(
            "You do not have permission to access this document",
        )

    if not document.storage_path:
        raise NotFoundException("Document file not found in storage")

    # ETag from the file's MD5 hash
    etag = f'"{document.file_md5}"'

    # Conditional request handling (If-None-Match)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        candidate = if_none_match.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == etag:
            return Response(status_code=304)

    storage = StorageService(settings)

    # Retrieve object metadata for total size
    obj_info = await storage.stat_object(document.storage_path)
    total_size = obj_info["size"]
    content_type = document.content_type or "application/pdf"

    # ── Fire-and-forget access log ────────────────────────────────────────
    try:
        logger.debug(
            "Schedule access_log: doc_id=%d, redis_manager=%s",
            document_id,
            _redis_mgr.redis_manager,
        )
        if _redis_mgr.redis_manager is not None:
            # Use a wrapper to catch and log any exception from the fire-and-forget task
            _log_task = asyncio.create_task(
                _log_access(
                    current_user_id,
                    document_id,
                    current_user_obj.username if current_user_obj else "unknown",
                ),
            )
            _log_task.add_done_callback(
                lambda t: t.exception() and logger.warning(
                    "Access log task failed: %s", t.exception()
                )
            )
        else:
            logger.warning("redis_manager is None, access log NOT scheduled")
    except Exception:
        logger.exception("Failed to schedule access log")

    # Common headers
    common_headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Cache-Control": "public, max-age=3600",
    }

    # Parse Range header
    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end_str = match.group(2)
            end = int(end_str) if end_str else total_size - 1
            end = min(end, total_size - 1)
            length = end - start + 1

            stream = await storage.get_object_stream(
                document.storage_path,
                offset=start,
                length=length,
            )

            return StreamingResponse(
                _iter_minio_stream(stream),
                status_code=206,
                media_type=content_type,
                headers={
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(length),
                },
            )

    # Full file response
    stream = await storage.get_object_stream(document.storage_path)
    return StreamingResponse(
        _iter_minio_stream(stream),
        media_type=content_type,
        headers={
            **common_headers,
            "Content-Length": str(total_size),
        },
    )


@router.post("/{document_id}/reprocess")
async def api_reprocess_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a document for async re-processing via Celery."""
    # Verify document exists and is accessible
    doc = await get_document(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    if doc is None:
        raise NotFoundException("Document not found")

    # Submit to Celery async pipeline
    async_result = process_document_task.delay(document_id)
    task_id = async_result.id

    # Store task→document mapping in Redis for progress tracking
    if _redis_mgr.redis_manager is not None:
        await _redis_mgr.redis_manager.set_key(
            f"doc_task:{document_id}", task_id, expire=86400
        )

    return success_response(
        data={
            "document_id": document_id,
            "task_id": task_id,
            "status": "PENDING",
        },
    )


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------


class BatchDeleteRequest(BaseModel):
    document_ids: list[int]


class BatchReprocessRequest(BaseModel):
    document_ids: list[int]


@router.post("/batch/delete")
async def api_batch_delete(
    body: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete multiple documents in batch.

    Silently skips documents that don't exist or that the user doesn't
    own (non-admin).  Returns a list of successfully deleted IDs.
    """
    storage = StorageService(settings)
    deleted_ids: list[int] = []
    errors: list[dict] = []

    for doc_id in body.document_ids:
        try:
            await delete_document(
                db, storage, document_id=doc_id, user_id=current_user.id,
            )
            deleted_ids.append(doc_id)
        except (NotFoundException, ForbiddenException) as exc:
            errors.append({"document_id": doc_id, "error": str(exc)})
        except Exception as exc:
            logger.exception("Batch delete failed for doc %d", doc_id)
            errors.append({"document_id": doc_id, "error": str(exc)})

    return success_response(
        data={
            "deleted_ids": deleted_ids,
            "errors": errors,
            "total": len(body.document_ids),
            "succeeded": len(deleted_ids),
        },
        message=f"Deleted {len(deleted_ids)} / {len(body.document_ids)} documents",
    )


@router.post("/batch/reprocess")
async def api_batch_reprocess(
    body: BatchReprocessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit multiple documents for async re-processing.

    Silently skips documents that don't exist or are inaccessible.
    Returns the task mappings for successfully queued documents.
    """
    queued: list[dict] = []
    errors: list[dict] = []

    for doc_id in body.document_ids:
        try:
            doc = await get_document(
                db, document_id=doc_id, user_id=current_user.id,
            )
            if doc is None:
                errors.append({"document_id": doc_id, "error": "Document not found"})
                continue

            async_result = process_document_task.delay(doc_id)
            if _redis_mgr.redis_manager is not None:
                await _redis_mgr.redis_manager.set_key(
                    f"doc_task:{doc_id}", async_result.id, expire=86400
                )
            queued.append({
                "document_id": doc_id,
                "task_id": async_result.id,
                "status": "PENDING",
            })
        except ForbiddenException as exc:
            errors.append({"document_id": doc_id, "error": str(exc)})
        except Exception as exc:
            logger.exception("Batch reprocess failed for doc %d", doc_id)
            errors.append({"document_id": doc_id, "error": str(exc)})

    return success_response(
        data={
            "queued": queued,
            "errors": errors,
            "total": len(body.document_ids),
            "succeeded": len(queued),
        },
        message=f"Queued {len(queued)} / {len(body.document_ids)} documents for reprocessing",
    )
