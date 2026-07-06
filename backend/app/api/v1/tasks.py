"""Task status and progress tracking endpoints.

Provides REST endpoints to query Celery task state and
document processing progress.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.response import error_response, success_response
from app.models.user import User
from app.services.task_service import TaskService

router = APIRouter()


@router.get("/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),  # noqa: B008, ARG001
):
    """Query the status of a Celery task by its ID.

    Returns the task's current state (PENDING, STARTED, SUCCESS, FAILURE,
    etc.) together with any result or error information.
    """
    data = TaskService.get_task_status(task_id)
    return success_response(data)


@router.get("/documents/{document_id}/progress")
async def get_document_progress(
    document_id: int,
    current_user: User = Depends(get_current_user),  # noqa: B008, ARG001
):
    """Get the processing progress of a document.

    Progress is written to Redis by the Celery worker during document
    ingestion.  Returns fields such as ``status``, ``step``,
    ``total_chunks`` and ``completed_chunks``.
    """
    data = await TaskService.get_document_processing_progress(document_id)
    if data is None:
        return error_response("No progress data found", status_code=404)
    return success_response(data)


@router.get("/queue/health")
async def queue_health(
    current_user: User = Depends(get_current_user),  # noqa: B008, ARG001
):
    """Check Celery worker status via the inspect API.

    Returns the list of connected workers, their queues, and runtime
    stats.  When no workers are connected the ``status`` field is
    ``"no_workers"``.
    """
    from app.tasks.celery_app import celery_app

    try:
        inspector = celery_app.control.inspect()
        active_queues = inspector.active_queues()
        stats = inspector.stats()

        if active_queues is None:
            return success_response(
                {
                    "status": "no_workers",
                    "workers": [],
                    "message": "No Celery workers connected",
                },
            )

        workers = [
            {
                "name": worker_name,
                "queues": [q.get("name") for q in queues if q.get("name")],
                "stats": stats.get(worker_name, {}) if stats else {},
            }
            for worker_name, queues in active_queues.items()
        ]

        return success_response(
            {
                "status": "ok",
                "workers": workers,
                "worker_count": len(workers),
            },
        )
    except Exception as exc:
        return success_response(
            {
                "status": "error",
                "workers": [],
                "message": str(exc),
            },
        )
