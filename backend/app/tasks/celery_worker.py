"""Celery worker entry point.

Run via::

    celery -A app.tasks.celery_app worker -l info -Q documents,embeddings

Or use the Docker Compose worker service directly.
"""

import os
import sys

# Ensure the backend/ directory is on sys.path so ``from app …`` works
# regardless of CWD when spawned as a subprocess from main.py.
_backend_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

if __name__ == "__main__":
    from app.tasks.celery_app import celery_app

    celery_app.worker_main(
        argv=["worker", "--loglevel=info", "--queues=documents,embeddings"]
    )
