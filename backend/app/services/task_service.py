"""Task status tracking service.

Provides business-logic for querying Celery task status and
document processing progress from Redis.
"""

from __future__ import annotations

from typing import Any

import app.core.redis_manager as _redis_mgr
from app.tasks.celery_app import celery_app


class TaskService:
    """Service for querying Celery task status and document progress."""

    @staticmethod
    def get_task_status(task_id: str) -> dict[str, Any]:
        """Query the status of a Celery task by its ID.

        Args:
            task_id: The Celery task UUID.

        Returns:
            dict with keys: ``task_id``, ``status``, ``result``, ``error``.
        """
        async_result = celery_app.AsyncResult(task_id)

        result_data = None
        error_data = None

        if async_result.successful():
            result_data = async_result.result
        elif async_result.failed():
            error_data = (
                str(async_result.result) if async_result.result else "Task failed"
            )

        return {
            "task_id": task_id,
            "status": async_result.state,
            "result": result_data,
            "error": error_data,
        }

    @staticmethod
    async def get_document_processing_progress(
        document_id: int,
    ) -> dict[str, Any] | None:
        """Read document processing progress.

        The upload/reprocess API stores a ``doc_task:{document_id}`` mapping
        in Redis.  This method looks up the Celery task ID from that mapping
        and queries its current state.

        Args:
            document_id: The document primary key.

        Returns:
            A dict with progress fields (task_id, status, result, error),
            or ``None`` if no such mapping exists or Redis is unavailable.
        """
        if _redis_mgr.redis_manager is None:
            return None

        task_id = await _redis_mgr.redis_manager.get_key(f"doc_task:{document_id}")
        if not task_id:
            return None

        async_result = celery_app.AsyncResult(task_id)

        result_data = None
        error_data = None

        if async_result.successful():
            result_data = async_result.result
        elif async_result.failed():
            error_data = (
                str(async_result.result) if async_result.result else "Task failed"
            )

        return {
            "document_id": document_id,
            "task_id": task_id,
            "status": async_result.state,
            "result": result_data,
            "error": error_data,
        }

    @staticmethod
    def list_pending_tasks(
        skip: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Stub: list pending / in-progress tasks.

        .. todo:: Admin feature — implement with Celery inspect / Flower API.

        Args:
            skip: Number of tasks to skip.
            limit: Maximum number of tasks to return.

        Returns:
            Paginated dict with ``items``, ``total``, ``skip``, ``limit``.
        """
        return {
            "items": [],
            "total": 0,
            "skip": skip,
            "limit": limit,
        }
