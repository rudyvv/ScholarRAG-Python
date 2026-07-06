"""Celery application — async task queue backed by RabbitMQ + Redis.

Usage::

    from app.tasks.celery_app import celery_app

    # Send a task
    celery_app.send_task("process_document", args=[doc_id])

    # Start worker (CLI):
    #   celery -A app.tasks.celery_app worker -l info -Q documents,embeddings
"""

from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "paismart",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.REDIS_URL,
)

# -- Default configuration ------------------------------------------------
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_store_errors_even_if_ignored=True,
    task_acks_late=True,  # Re-deliver on worker crash
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    task_max_retries=3,
    task_soft_time_limit=1800,  # 30 minutes
    task_time_limit=2100,  # 35 minutes
)

# -- Task routing ---------------------------------------------------------
# Task names match the ``@shared_task(name=...)`` value set on each task.
celery_app.conf.task_routes = {
    "process_document": {"queue": "documents"},
    "vectorize_chunks": {"queue": "embeddings"},
}

# -- Explicit imports ensure task modules are registered -------------------
import app.tasks.document_tasks  # noqa: F401  # register process_document, vectorize_chunks

# -- Autodiscover tasks from registered modules ---------------------------
celery_app.autodiscover_tasks(["app.tasks"])
