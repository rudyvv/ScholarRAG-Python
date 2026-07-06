# Paismart RAG — Reasonix Context

## Stack

- **Python 3.11** — runtime version (`.python-version`)
- **FastAPI** — async web framework with `uvicorn[standard]` server
- **Vue 3 + TypeScript** — frontend SPA, built with Vite + UnoCSS + Naive UI + Pinia
- **SQLAlchemy 2.0** — async ORM with `aiomysql` driver; Alembic for migrations
- **Celery** — task queue with RabbitMQ broker (Redis as result backend)
- **Elasticsearch 8** — full-text search (IK Chinese analyzer)
- **Milvus 2.3** — vector database for embeddings
- **MinIO** — S3-compatible object storage for documents

## Layout

- `backend/` — FastAPI application (`app/main.py`). API routes in `app/api/v1/`, DB models in `app/models/`, business logic in `app/services/`, Celery tasks in `app/tasks/`, config in `app/config.py`.
- `frontend/` — Vue 3 SPA. Pages under `src/pages/` (chat, kb, admin), store in `src/stores/`, API client in `src/api/client.ts`.
- `docker-compose.yml` — all infrastructure services (MySQL, Redis, MinIO, Elasticsearch, RabbitMQ, Milvus). Start with `make up`.
- `scripts/` — one-shot init scripts (db schema, Milvus collection). ES index and admin bootstrap are auto-created on app startup.
- `volumes/milvus/` — Milvus local data (etcd, rocksdb) checked into repo for development.
- `Makefile` — orchestrates Docker Compose + dev commands.

## Commands

| Make target / script | What it runs |
|---|---|
| `make up` | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` |
| `make down` | Stop all infrastructure containers |
| `make test` | `python -m pytest tests/ -v --tb=short` |
| `make migrate` | `cd backend && alembic upgrade head` |
| `make init` | Initialize database + Milvus (ES index + admin auto-created on startup) |
| `npm run dev` (frontend) | Vite dev server |
| `npm run build` (frontend) | `vue-tsc && vite build` |

## Conventions

- **Ruff** for lint + format — double quotes, py311 target, E501 (line length) ignored. Run `ruff check .` and `ruff format .` from `backend/`.
- **mypy** for type checking — config in `backend/pyproject.toml` with third-party library imports suppressed.
- **pytest-asyncio** in `auto` mode — async test functions work without decorators.
- **API versioning** — all endpoints under `/api/v1/`, each resource group gets its own router with a prefix and `tags` (auth, admin, chat, documents, models, search, tasks).
- **UV workspace** — root `pyproject.toml` is a workspace pointer; real dependencies live in `backend/pyproject.toml`.

## Watch out for

- **`.env` is required** — copy `.env.example` to `.env` before any `docker compose` or backend command.
- **Infrastructure-first** — backend won't start without MySQL + Redis + Elasticsearch + Milvus. Always `make up` first.
- **Generated files** — `__pycache__/`, `.ruff_cache/`, `.venv/`, `frontend/dist/`, `node_modules/` are gitignored. Don't edit by hand.
- **Alembic migrations** live in `backend/alembic/versions/`; generate new ones with `alembic revision --autogenerate -m "desc"` from `backend/`.
