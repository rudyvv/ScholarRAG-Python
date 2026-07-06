"""Document upload service with chunked upload and resume support.

Provides the business-logic layer for the document upload API,
coordinating Redis (tracking), MinIO (storage), and the database
(Document records).
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.redis_manager import RedisManager
from app.models.document import DocStatus, Document, DocumentChunk
from app.services.storage_service import StorageService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 5 * 1024 * 1024  # 5 MiB

# Redis key prefixes
_REDIS_UPLOAD = "upload:{upload_id}"
_REDIS_CHUNKS = "upload:{upload_id}:chunks"  # Set[int] — received chunk numbers
_REDIS_PARTS = "upload:{upload_id}:parts"  # Hash[int → etag]
_UPLOAD_TTL = 3600  # 1 hour

# ── Helpers -----------------------------------------------------------------


def _upload_key(upload_id: str) -> str:
    return _REDIS_UPLOAD.format(upload_id=upload_id)


def _chunks_key(upload_id: str) -> str:
    return _REDIS_CHUNKS.format(upload_id=upload_id)


def _parts_key(upload_id: str) -> str:
    return _REDIS_PARTS.format(upload_id=upload_id)


async def _rc(redis: RedisManager) -> AsyncRedis:
    """Return the underlying ``redis.asyncio.Redis`` client."""
    return redis._client  # type: ignore[return-value]


def _object_name(upload_id: str) -> str:
    """Return the MinIO object key for the final assembled file."""
    return f"uploads/{upload_id}/final"


# ── Public API --------------------------------------------------------------


async def check_document_dedup(
    db: AsyncSession,
    user_id: int,
    file_md5: str | None,
) -> Document | None:
    """Return an existing *Document* with the same MD5 + user, or *None*."""
    if not file_md5:
        return None  # Empty MD5 → skip dedup (NULLs are not unique in MySQL)
    result = await db.execute(
        select(Document).where(
            Document.file_md5 == file_md5,
            Document.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def init_upload(
    redis: RedisManager,
    storage: StorageService,
    *,
    filename: str,
    file_size: int,
    file_md5: str,
    content_type: str | None,
    user_id: int,
) -> dict[str, Any]:
    """Initialise a chunked upload session.

    Returns:
        A dict with ``upload_id`` and ``chunk_size``.
    """
    upload_id = uuid.uuid4().hex
    obj_name = _object_name(upload_id)

    # Ensure the bucket exists before creating the multipart upload
    await storage.init_storage()

    # Create a MinIO multipart upload session so we can use upload_part()
    minio_upload_id = await storage.create_multipart_upload(
        object_name=obj_name,
    )

    client = await _rc(redis)
    uk = _upload_key(upload_id)

    await client.hset(
        uk,
        mapping={
            "filename": filename,
            "file_size": str(file_size),
            "file_md5": file_md5,
            "content_type": content_type or "",
            "user_id": str(user_id),
            "minio_upload_id": minio_upload_id,
            "object_name": obj_name,
        },
    )
    await client.expire(uk, _UPLOAD_TTL)

    return {
        "upload_id": upload_id,
        "chunk_size": CHUNK_SIZE,
    }


async def upload_chunk(
    redis: RedisManager,
    storage: StorageService,
    *,
    upload_id: str,
    chunk_number: int,
    data: bytes,
    user_id: int,
) -> dict[str, Any]:
    """Upload a single chunk belonging to an active upload session.

    Returns:
        A dict with ``chunk_number``.
    """
    client = await _rc(redis)
    uk = _upload_key(upload_id)

    upload_info = await client.hgetall(uk)
    if not upload_info:
        raise NotFoundException("Upload session not found")

    if int(upload_info["user_id"]) != user_id:
        raise ConflictException("Upload session belongs to a different user")

    minio_upload_id = upload_info["minio_upload_id"]
    obj_name = upload_info["object_name"]

    # MinIO S3 API requires part numbers starting at 1.
    part_number = chunk_number + 1

    # Upload chunk data directly to MinIO (no temp file needed)
    part_number, etag = await storage.upload_part(
        data=data,
        object_name=obj_name,
        part_number=part_number,
        upload_id=minio_upload_id,
    )

    # Track in Redis
    await client.sadd(_chunks_key(upload_id), part_number)
    await client.hset(_parts_key(upload_id), str(part_number), etag)

    # Refresh TTL on all keys
    for key in (uk, _chunks_key(upload_id), _parts_key(upload_id)):
        await client.expire(key, _UPLOAD_TTL)

    return {"chunk_number": chunk_number}


async def complete_upload(
    redis: RedisManager,
    storage: StorageService,
    db: AsyncSession,
    *,
    upload_id: str,
    user_id: int,
    org_tag: str | None = None,
) -> dict[str, Any]:
    """Finalise a chunked upload and persist the Document record.

    Returns:
        A dict with ``document_id`` and ``status``.
    """
    client = await _rc(redis)
    uk = _upload_key(upload_id)

    upload_info = await client.hgetall(uk)
    if not upload_info:
        raise NotFoundException("Upload session not found")

    if int(upload_info["user_id"]) != user_id:
        raise ConflictException("Upload session belongs to a different user")

    file_size = int(upload_info["file_size"])
    expected_chunks = math.ceil(file_size / CHUNK_SIZE)

    # Verify all chunks have been received
    raw = await client.smembers(_chunks_key(upload_id))
    received = {int(c) for c in raw}
    expected_set = set(range(1, expected_chunks + 1))
    if received != expected_set:
        missing = sorted(expected_set - received)
        raise BadRequestException(
            message=f"Missing chunks: {missing}",
        )

    minio_upload_id = upload_info["minio_upload_id"]
    obj_name = upload_info["object_name"]

    # Collect part info ordered by part number
    parts_raw = await client.hgetall(_parts_key(upload_id))
    parts = sorted(
        ({"PartNumber": int(pn), "ETag": etag} for pn, etag in parts_raw.items()),
        key=lambda p: p["PartNumber"],
    )

    await storage.complete_multipart_upload(
        object_name=obj_name,
        upload_id=minio_upload_id,
        parts=parts,
    )

    # Persist Document record
    document = Document(
        user_id=user_id,
        filename=upload_info["filename"],
        file_md5=upload_info["file_md5"]
        or None,  # NULL if empty (MySQL unique const ignores NULLs)
        file_size=file_size,
        storage_path=obj_name,
        content_type=upload_info.get("content_type") or None,
        doc_status=DocStatus.UPLOADING,
        org_tag=org_tag,
        chunk_count=expected_chunks,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Clean up Redis keys
    await client.delete(uk, _chunks_key(upload_id), _parts_key(upload_id))

    return {"document_id": document.id, "status": document.doc_status.value}


async def get_upload_status(
    redis: RedisManager,
    *,
    upload_id: str,
) -> dict[str, Any]:
    """Return the current progress of an active upload session."""
    client = await _rc(redis)
    uk = _upload_key(upload_id)

    upload_info = await client.hgetall(uk)
    if not upload_info:
        raise NotFoundException("Upload session not found")

    file_size = int(upload_info["file_size"])
    expected_chunks = math.ceil(file_size / CHUNK_SIZE)

    raw = await client.smembers(_chunks_key(upload_id))
    received = {int(c) for c in raw}

    return {
        "upload_id": upload_id,
        "filename": upload_info["filename"],
        "file_size": file_size,
        "received_chunks": sorted(received),
        "total_chunks": expected_chunks,
    }


async def delete_document(
    db: AsyncSession,
    storage: StorageService,
    *,
    document_id: int,
    user_id: int,
) -> None:
    """Delete a document — both the MinIO object and the database record."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundException("Document not found")
    if document.user_id != user_id:
        raise ForbiddenException("You do not have permission to delete this document")

    # Remove from MinIO
    if document.storage_path:
        await storage.delete_file(document.storage_path)

    # Remove chunks explicitly (FK has no CASCADE)
    from sqlalchemy import delete as sa_delete
    from app.models.document import DocumentChunk

    await db.execute(
        sa_delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )

    # Remove the document record
    await db.delete(document)
    await db.commit()


# ── CRUD Operations ---------------------------------------------------------


async def list_documents(
    db: AsyncSession,
    user_id: int,
    is_admin: bool = False,
    user_org_tags: list[str] | None = None,
    org_tag: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """List documents with org-based access control.

    Access rules:
    - Admin → all documents.
    - Regular user → own documents + public documents from same org.

    Args:
        db: Database session.
        user_id: The requesting user's ID.
        is_admin: Whether the requester is an admin.
        user_org_tags: The requester's org tags (list of strings).
        org_tag: Optional filter by specific org tag.
        status: Optional document status filter.
        page: 1-indexed page number.
        size: Number of items per page.

    Returns:
        A dict with ``items``, ``total``, ``page``, and ``size``.
    """
    from sqlalchemy import or_ as sqla_or  # noqa: PLC0415

    if is_admin:
        conditions: list = []
    elif user_org_tags:
        # Build LIKE conditions for semicolon-separated org_tag field.
        # Document.org_tag stores tags as "tag1;tag2;tag3".
        # We need to match if ANY of the user's org tags appears as a delimited item.
        tag_matches = []
        for tag in user_org_tags:
            safe = tag.replace("%", "\\%").replace("_", "\\_")
            tag_matches.extend([
                Document.org_tag == safe,
                Document.org_tag.like(f"{safe};%"),
                Document.org_tag.like(f"%;{safe};%"),
                Document.org_tag.like(f"%;{safe}"),
            ])
        conditions = [
            sqla_or(
                Document.user_id == user_id,
                Document.is_public.is_(True),
                sqla_or(*tag_matches),
            )
        ]
    else:
        conditions = [Document.user_id == user_id]

    if org_tag:
        conditions.append(Document.org_tag == org_tag)
    if status:
        conditions.append(Document.doc_status == DocStatus(status))

    # Count total matching documents
    count_q = select(func.count(Document.id)).select_from(Document).where(*conditions)
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Fetch paginated items with owner username
    offset = (page - 1) * size
    from app.models.user import User  # noqa: PLC0415

    items_q = (
        select(Document, User.username)
        .join(User, Document.user_id == User.id, isouter=True)
        .where(*conditions)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    items_result = await db.execute(items_q)
    rows = items_result.all()

    items = []
    for doc, owner_name in rows:
        doc_dict = {
            "id": doc.id,
            "user_id": doc.user_id,
            "filename": doc.filename,
            "file_md5": doc.file_md5,
            "file_size": doc.file_size,
            "storage_path": doc.storage_path,
            "content_type": doc.content_type,
            "doc_status": doc.doc_status,
            "is_public": doc.is_public,
            "org_tag": doc.org_tag,
            "chunk_count": doc.chunk_count,
            "owner_username": owner_name or "unknown",
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
        }
        items.append(doc_dict)

    return {"items": items, "total": total, "page": page, "size": size}


async def get_document(
    db: AsyncSession,
    document_id: int,
    user_id: int,
    is_admin: bool = False,
    user_org_tags: list[str] | None = None,
) -> Document:
    """Get a document by ID with org-based access control.

    Access rules:
    - Owner → always.
    - Admin → any document.
    - Other users → only if document is public AND shares an org tag.

    Args:
        db: Database session.
        document_id: Document ID.
        user_id: The requesting user's ID.
        is_admin: Whether the requester is an admin.
        user_org_tags: The requester's org tags.

    Returns:
        The ``Document`` SQLAlchemy model instance.

    Raises:
        NotFoundException: If the document is not found or not accessible.
    """
    from sqlalchemy import or_ as sqla_or  # noqa: PLC0415

    if is_admin:
        conditions = [Document.id == document_id]
    else:
        conditions = [
            Document.id == document_id,
            sqla_or(
                Document.user_id == user_id,
                Document.is_public.is_(True),
                Document.org_tag.in_(user_org_tags) if user_org_tags else False,
            ),
        ]

    result = await db.execute(select(Document).where(*conditions))
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundException("Document not found")
    return document


async def get_document_chunks(
    db: AsyncSession,
    document_id: int,
    user_id: int,
    is_admin: bool = False,
    user_org_tags: list[str] | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """Get chunks for a document with ownership check.

    Args:
        db: Database session.
        document_id: Document ID.
        user_id: The requesting user's ID.
        is_admin: Whether the requester is an admin.
        user_org_tags: The requester's org tags.
        page: 1-indexed page number.
        size: Number of chunks per page.

    Returns:
        A dict with ``chunks``, ``total``, ``page``, and ``size``.
    """
    # Verify access first
    await get_document(db, document_id, user_id, is_admin=is_admin, user_org_tags=user_org_tags)

    # Count total chunks
    count_q = select(func.count(DocumentChunk.id)).where(
        DocumentChunk.document_id == document_id
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Fetch paginated chunks
    offset = (page - 1) * size
    items_q = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .offset(offset)
        .limit(size)
    )
    items_result = await db.execute(items_q)
    chunks = list(items_result.scalars().all())

    # Serialise to dicts
    chunk_list = [
        {
            "id": c.id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "chunk_metadata": c.chunk_metadata,
        }
        for c in chunks
    ]

    return {
        "chunks": chunk_list,
        "total": total,
        "page": page,
        "size": size,
    }


async def update_document_status(
    db: AsyncSession,
    document_id: int,
    status: DocStatus,
    user_id: int | None = None,
) -> Document:
    """Update document status with optional ownership check.

    Args:
        db: Database session.
        document_id: Document ID.
        status: New ``DocStatus`` value.
        user_id: If provided, verifies the document belongs to this user.

    Returns:
        The updated ``Document``.

    Raises:
        NotFoundException: If the document is not found or fails the
            ownership check.
    """
    conditions = [Document.id == document_id]
    if user_id is not None:
        conditions.append(Document.user_id == user_id)

    result = await db.execute(select(Document).where(*conditions))
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundException("Document not found")

    document.doc_status = status
    await db.commit()
    await db.refresh(document)
    return document


async def get_document_statistics(db: AsyncSession, user_id: int) -> dict:
    """Get document statistics for a user.

    Args:
        db: Database session.
        user_id: Owner user ID.

    Returns:
        A dict with ``total_documents``, ``total_chunks``, and
        ``status_distribution``.
    """
    # Total documents
    doc_count_result = await db.execute(
        select(func.count(Document.id)).where(Document.user_id == user_id)
    )
    total_documents = doc_count_result.scalar() or 0

    # Total chunks (user scoped via join)
    chunk_count_result = await db.execute(
        select(func.count(DocumentChunk.id))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
    )
    total_chunks = chunk_count_result.scalar() or 0

    # Status distribution
    dist_result = await db.execute(
        select(Document.doc_status, func.count(Document.id))
        .where(Document.user_id == user_id)
        .group_by(Document.doc_status)
    )
    status_distribution: dict[str, int] = {}
    for row in dist_result.all():
        status_distribution[row[0].value] = row[1]

    return {
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "status_distribution": status_distribution,
    }


async def get_download_url(
    db: AsyncSession,
    storage: StorageService,
    document_id: int,
    user_id: int,
) -> str:
    """Get a presigned download URL (1-hour expiry) for a document.

    Args:
        db: Database session.
        storage: ``StorageService`` instance.
        document_id: Document ID.
        user_id: Expected owner user ID.

    Returns:
        A presigned URL string valid for 1 hour.
    """
    document = await get_document(db, document_id, user_id)
    url = await storage.get_file_url(document.storage_path, expires=3600)
    return url
