# Repository Guidelines

## Project Structure & Module Organization

```
paismart-python/
├── backend/                  # FastAPI application (Python 3.11+)
│   ├── app/
│   │   ├── api/v1/           # Route handlers (auth, documents, search, chat, admin, tasks, models)
│   │   ├── core/             # Cross-cutting concerns (security, config, deps, exceptions, rate limiting)
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic (document, search, rag, embedding, storage, etc.)
│   │   ├── tasks/            # Celery async task definitions
│   │   ├── db/               # Database session factory, declarative base
│   │   ├── config.py         # Pydantic Settings (reads from .env)
│   │   └── main.py           # FastAPI application entry point
│   ├── alembic/              # Database migrations
│   └── tests/                # Test suite
├── frontend/                 # Vue 3 + Vite + TypeScript + Naive UI + Pinia
│   └── src/
│       ├── pages/            # Page components (Login, Register, Dashboard, Chat, KB, Admin)
│       ├── layouts/          # Layout components
│       └── App.vue           # Root component
├── docker/                   # Custom Dockerfiles (Elasticsearch IK analyzer)
├── scripts/                  # Shell initialization scripts
├── docs/                     # Documentation
├── docker-compose.yml        # Infrastructure services (MySQL, Redis, MinIO, ES, RabbitMQ, Milvus)
├── docker-compose.dev.yml    # Dev overrides
├── Makefile                  # Common development commands
└── pyproject.toml            # UV workspace root (members: backend)
```

## Build, Test, and Development Commands

| Command | Purpose |
|---------|---------|
| `make up` | Start all infrastructure services via Docker Compose |
| `make down` | Stop all services |
| `make test` | Run pytest (`python -m pytest tests/ -v --tb=short`) |
| `make migrate` | Run Alembic migrations (`alembic upgrade head`) |
| `make init` | Initialize database + Milvus collection |
| `cd backend && uv run uvicorn app.main:app --reload` | Start backend dev server |
| `cd frontend && npx vite` | Start frontend dev server |
| `cd frontend && npx vite build` | Build frontend for production |

Run `make` (or `make help`) to see all available targets.

## Coding Style & Naming Conventions

- **Python**: Follow `ruff` linting (rule sets: E, F, I, N, W, UP, B, SIM, ARG, PTH, TRY) and `ruff format` with double quotes. Target Python 3.11.
- **Type hints**: Use `mypy` for static type checking; enable `check_untyped_defs` and `warn_return_any`. Add `# noqa` or `# type: ignore` only when necessary.
- **Naming**: `snake_case` for variables, functions, and modules; `PascalCase` for classes and SQLAlchemy models; `UPPER_CASE` for constants and env-var backed settings.
- **Frontend**: Vue 3 `<script setup>` composition API with TypeScript. UnoCSS utility classes for styling. Pinia stores for state management.
- **Imports**: Group as standard library, third-party, then local; `ruff` rule I enforces this automatically.

## Testing Guidelines

- **Framework**: pytest with `pytest-asyncio` (async tests auto-detected).
- **Test location**: `backend/tests/` -- mirror the `app/` module structure.
- **Naming**: Test files prefixed `test_`, test functions prefixed `test_`, classes prefixed `Test`.
- **Coverage**: Target critical paths (auth, document ingest, search, chat) with at least basic smoke tests.

## Commit & Pull Request Guidelines

- **Commit messages**: Use conventional commits format: `type(scope): description` (e.g., `feat(auth): add refresh token endpoint`, `fix(search): handle empty query gracefully`). Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`.
- **PRs**: Every PR must include a description of changes, link to the related issue, and test evidence. Frontend changes should include screenshots if user-facing.

## Architecture Overview

Paismart is a RAG knowledge-base QA system. Documents are uploaded, parsed, chunked, and stored in three search tiers:

1. **Elasticsearch** -- full-text keyword search on document chunks
2. **Milvus** -- vector similarity search on chunk embeddings
3. **MySQL** -- relational storage for documents, users, conversations, and metadata

The system uses **Celery** for async document processing (parsing, chunking, embedding) via RabbitMQ as broker and Redis as result backend. **MinIO** provides S3-compatible object storage for raw files.

## Agent-Specific Instructions

- Run `make up` first to start infrastructure dependencies before working on backend features.
- Backend settings are environment-driven via `.env`; copy `.env.example` to `.env` and adjust as needed.
- This project uses **uv** for Python dependency management (`backend/pyproject.toml`). Add new dependencies there, then run `uv lock` and `uv sync`.
- Frontend dependencies go in `frontend/package.json`; run `npm install` after changes.
- Never commit `node_modules/`, `.venv/`, or auto-generated cache directories.
