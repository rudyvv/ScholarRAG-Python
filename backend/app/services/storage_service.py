"""Async MinIO storage service with chunked upload support.

Provides a full ``StorageService`` class that wraps the synchronous
``minio.Minio`` SDK with ``asyncio.to_thread()`` so all public methods
are async-friendly.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from minio import Minio
from minio.datatypes import Object, Part
from minio.error import S3Error

from app.config import Settings
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)

_MINIO_TIMEOUT: int = 30  # seconds for thread-pool operations


async def _run_to_thread(func, *args, **kwargs):
    """Run a sync function via ``asyncio.to_thread`` with a timeout.

    Args:
        func: Sync callable.
        *args: Positional args forwarded to *func*.
        **kwargs: Keyword args forwarded to *func*.

    Returns:
        The return value of *func*.

    Raises:
        StorageError: On timeout or any other S3Error.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(functools.partial(func, *args, **kwargs)),
            timeout=_MINIO_TIMEOUT,
        )
    except TimeoutError:
        logger.warning("MinIO operation timed out after %ss", _MINIO_TIMEOUT)
        raise StorageError("MinIO operation timed out") from None


class StorageService:
    """Async file-storage service backed by MinIO.

    Every public method is async and dispatches the synchronous MinIO
    SDK call to a thread-pool via ``asyncio.to_thread()``, keeping the
    event loop unblocked.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the underlying ``minio.Minio`` client.

        Args:
            settings: Application settings providing MinIO connection
                parameters (``MINIO_ENDPOINT``, ``MINIO_ACCESS_KEY``,
                ``MINIO_SECRET_KEY``, ``MINIO_SECURE``).
        """
        self._client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self._default_bucket = settings.MINIO_BUCKET
        logger.debug(
            "StorageService initialised for %s/%s",
            settings.MINIO_ENDPOINT,
            settings.MINIO_BUCKET,
        )

    # ------------------------------------------------------------------
    # Bucket management
    # ------------------------------------------------------------------

    async def init_storage(self, bucket: str | None = None) -> None:
        """Ensure the target bucket exists, creating it if necessary.

        Args:
            bucket: Bucket name (falls back to ``settings.MINIO_BUCKET``).

        Raises:
            StorageError: If the bucket cannot be created.
        """
        target = bucket or self._default_bucket
        try:
            exists = await _run_to_thread(self._client.bucket_exists, target)
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to initialise bucket '{target}': {exc.message or exc.code}"
            ) from exc
        else:
            if not exists:
                await _run_to_thread(self._client.make_bucket, target)
                logger.info("Bucket '%s' created", target)
            else:
                logger.debug("Bucket '%s' already exists", target)

    # ------------------------------------------------------------------
    # Simple (single-part) upload
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        file_path: str,
        object_name: str,
        bucket: str | None = None,
    ) -> str:
        """Upload a local file to MinIO as a single-part upload.

        Args:
            file_path: Absolute or relative path to the local file.
            object_name: Key under which the object is stored in MinIO.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Returns:
            The ``object_name`` on success.

        Raises:
            StorageError: If the upload fails.
        """
        target = bucket or self._default_bucket
        try:
            result = await _run_to_thread(
                self._client.fput_object,
                target,
                object_name,
                file_path,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to upload '{file_path}' to '{target}/{object_name}': "
                f"{exc.message or exc.code}"
            ) from exc
        else:
            logger.info(
                "Uploaded '%s' -> %s/%s (etag=%s)",
                file_path, target, object_name, result.etag,
            )
            return object_name

    # ------------------------------------------------------------------
    # Multipart (chunked) upload
    # ------------------------------------------------------------------

    async def create_multipart_upload(
        self,
        object_name: str,
        bucket: str | None = None,
    ) -> str:
        """Initialise a multipart upload session.

        Args:
            object_name: Key under which the final object is stored.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Returns:
            An ``upload_id`` string that identifies the session.

        Raises:
            StorageError: If the session cannot be created.
        """
        target = bucket or self._default_bucket
        try:
            upload_id = await _run_to_thread(
                self._client._create_multipart_upload,  # noqa: SLF001
                target,
                object_name,
                {},  # headers (required by MinIO SDK)
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to create multipart upload for "
                f"'{target}/{object_name}': {exc.message or exc.code}"
            ) from exc
        else:
            logger.debug(
                "Multipart upload created: %s/%s (upload_id=%s)",
                target, object_name, upload_id,
            )
            return upload_id

    async def upload_part(
        self,
        data: bytes,
        object_name: str,
        part_number: int,
        upload_id: str,
        bucket: str | None = None,
    ) -> tuple[int, str]:
        """Upload a single chunk as part of a multipart upload.

        Args:
            data: Raw chunk bytes to upload.
            object_name: Key under which the final object is stored.
            part_number: Part number (1-based).
            upload_id: The upload session ID.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Returns:
            A ``(part_number, etag)`` tuple to be collected for the
            final completion step.

        Raises:
            StorageError: If the part upload fails.
        """
        target = bucket or self._default_bucket

        try:
            etag = await _run_to_thread(
                self._client._upload_part,  # noqa: SLF001
                target,
                object_name,
                data,
                None,  # headers
                upload_id,
                part_number,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to upload part {part_number} for "
                f"'{target}/{object_name}': {exc.message or exc.code}"
            ) from exc
        else:
            logger.debug(
                "Part %d uploaded for '%s/%s' (etag=%s)",
                part_number, target, object_name, etag,
            )
            return part_number, etag

    async def complete_multipart_upload(
        self,
        object_name: str,
        upload_id: str,
        parts: list[dict[str, Any]],
        bucket: str | None = None,
    ) -> None:
        """Complete a multipart upload by assembling the uploaded parts.

        Args:
            object_name: Key under which the final object is stored.
            upload_id: The upload session ID.
            parts: Ordered list of dicts with keys ``"PartNumber"`` and
                ``"ETag"``, exactly as returned by ``upload_part``.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Raises:
            StorageError: If the completion fails.
        """
        target = bucket or self._default_bucket
        part_objects = [
            Part(part_number=p["PartNumber"], etag=p["ETag"]) for p in parts
        ]
        try:
            await _run_to_thread(
                self._client._complete_multipart_upload,  # noqa: SLF001
                target,
                object_name,
                upload_id,
                part_objects,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to complete multipart upload for "
                f"'{target}/{object_name}': {exc.message or exc.code}"
            ) from exc
        else:
            logger.info(
                "Multipart upload completed: %s/%s (upload_id=%s)",
                target, object_name, upload_id,
            )

    async def abort_multipart_upload(
        self,
        object_name: str,
        upload_id: str,
        bucket: str | None = None,
    ) -> None:
        """Abort an incomplete multipart upload and discard its parts.

        Args:
            object_name: Key under which the object was being uploaded.
            upload_id: The upload session ID.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Raises:
            StorageError: If the abort fails.
        """
        target = bucket or self._default_bucket
        try:
            await _run_to_thread(
                self._client._abort_multipart_upload,  # noqa: SLF001
                target,
                object_name,
                upload_id,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to abort multipart upload for "
                f"'{target}/{object_name}': {exc.message or exc.code}"
            ) from exc
        else:
            logger.info(
                "Multipart upload aborted: %s/%s (upload_id=%s)",
                target, object_name, upload_id,
            )

    # ------------------------------------------------------------------
    # URL generation
    # ------------------------------------------------------------------

    async def get_file_url(
        self,
        object_name: str,
        bucket: str | None = None,
        expires: int = 3600,
    ) -> str:
        """Generate a presigned GET URL for the object.

        Args:
            object_name: Key of the object.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).
            expires: URL validity duration in seconds (default 1 hour).

        Returns:
            A presigned URL string.

        Raises:
            StorageError: If the URL cannot be generated.
        """
        target = bucket or self._default_bucket
        try:
            url = await _run_to_thread(
                self._client.presigned_get_object,
                target,
                object_name,
                timedelta(seconds=expires),
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to generate presigned URL for "
                f"'{target}/{object_name}': {exc.message or exc.code}"
            ) from exc
        else:
            return url

    async def download_file(
        self,
        object_name: str,
        file_path: str | Path | None = None,
        bucket: str | None = None,
    ) -> str:
        """Download an object from MinIO to a temporary local file.

        Args:
            object_name: Key of the object to download.
            file_path: Destination path. If ``None``, a temp file is
                created automatically.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Returns:
            The absolute path to the downloaded file.

        Raises:
            StorageError: If the download fails.
        """
        import tempfile

        target = bucket or self._default_bucket
        if file_path is None:
            file_path = Path(tempfile.gettempdir()) / f"minio_dl_{Path(object_name).name}"
        else:
            file_path = Path(file_path)

        try:
            await _run_to_thread(
                self._client.fget_object,
                target,
                object_name,
                str(file_path),
            )
        except S3Error as exc:
            raise StorageError(
                f"Failed to download '{target}/{object_name}': "
                f"{exc.message or exc.code}"
            ) from exc
        else:
            logger.info("Downloaded '%s/%s' to %s", target, object_name, file_path)
            return str(file_path)

    # ------------------------------------------------------------------
    # Streaming / object access
    # ------------------------------------------------------------------

    async def stat_object(
        self,
        object_name: str,
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve object metadata (size, etag, content-type, etc.).

        Args:
            object_name: Key of the object.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Returns:
            A dict with keys ``size``, ``etag``, ``content_type``, and
            ``last_modified``.

        Raises:
            StorageError: If the object cannot be found or accessed.
        """
        target = bucket or self._default_bucket
        try:
            obj = await _run_to_thread(
                self._client.stat_object,
                target,
                object_name,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to stat object '{target}/{object_name}': "
                f"{exc.message or exc.code}"
            ) from exc
        else:
            return {
                "size": obj.size,
                "etag": obj.etag,
                "content_type": obj.content_type,
                "last_modified": obj.last_modified,
            }

    async def get_object_stream(
        self,
        object_name: str,
        bucket: str | None = None,
        offset: int = 0,
        length: int = 0,
    ):
        """Open a streaming read from MinIO, optionally for a byte range.

        Args:
            object_name: Key of the object.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).
            offset: Byte offset to start reading from.
            length: Number of bytes to read (``0`` means the rest of the
                object after *offset*).

        Returns:
            A ``urllib3.HTTPResponse`` object that can be iterated or
            read chunk-by-chunk.

        Raises:
            StorageError: If the object cannot be read.
        """
        target = bucket or self._default_bucket
        try:
            response = await _run_to_thread(
                self._client.get_object,
                target,
                object_name,
                offset=offset,
                length=length,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to stream object '{target}/{object_name}' "
                f"(offset={offset}, length={length}): "
                f"{exc.message or exc.code}"
            ) from exc
        else:
            return response

    # ------------------------------------------------------------------
    # File deletion
    # ------------------------------------------------------------------

    async def delete_file(
        self,
        object_name: str,
        bucket: str | None = None,
    ) -> None:
        """Delete an object from MinIO.

        Args:
            object_name: Key of the object to delete.
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Raises:
            StorageError: If the deletion fails.
        """
        target = bucket or self._default_bucket
        try:
            await _run_to_thread(
                self._client.remove_object,
                target,
                object_name,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to delete '{target}/{object_name}': "
                f"{exc.message or exc.code}"
            ) from exc
        else:
            logger.info("Deleted '%s/%s'", target, object_name)

    # ------------------------------------------------------------------
    # File listing
    # ------------------------------------------------------------------

    async def list_files(
        self,
        prefix: str = "",
        bucket: str | None = None,
    ) -> list[dict[str, Any]]:
        """List objects under the given prefix.

        Args:
            prefix: Object-name prefix filter (default ``""`` lists all).
            bucket: Target bucket (falls back to ``settings.MINIO_BUCKET``).

        Returns:
            A list of dicts with keys ``object_name``, ``size``,
            ``etag``, and ``last_modified``.

        Raises:
            StorageError: If the listing fails.
        """
        target = bucket or self._default_bucket
        try:
            objects = await _run_to_thread(
                self._list_objects_sync,
                target,
                prefix,
            )
        except S3Error as exc:
            raise StorageError(  # noqa: TRY003
                f"Failed to list objects in '{target}' "
                f"(prefix='{prefix}'): {exc.message or exc.code}"
            ) from exc
        else:
            return [
                {
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "etag": obj.etag,
                    "last_modified": obj.last_modified,
                }
                for obj in objects
                if not obj.is_dir
            ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _list_objects_sync(self, bucket: str, prefix: str) -> list[Object]:
        """Synchronous helper that collects ``list_objects`` results.

        ``minio.Minio.list_objects`` returns a lazy iterator; we
        materialise it here so ``asyncio.to_thread`` can run the whole
        operation in one thread.
        """
        return list(
            self._client.list_objects(
                bucket,
                prefix=prefix,
                recursive=True,
            )
        )
