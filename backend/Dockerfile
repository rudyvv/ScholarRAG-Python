# =============================================================================
# Paismart RAG - Backend Docker Image
# =============================================================================
# Used for the Celery worker service. The FastAPI app runs locally via uvicorn.
#
# Build:
#   docker build -t paismart-backend ./backend
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install deps system-wide (not in .venv) so volume mount doesn't break imports
RUN pip install --no-cache-dir --default-timeout=120 .

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .

ENV PYTHONPATH=/app

CMD ["celery", "-A", "app.tasks.celery_app", "worker", "-l", "info", "-Q", "documents,embeddings"]
