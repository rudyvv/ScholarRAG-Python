"""FastAPI application entry-point."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# ── Force logging config (force=True overrides uvicorn's preset) ────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import api_v1_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.ratelimit import limiter
from app.core.redis_manager import close_redis, init_redis
from app.services.http_client import close_http_client
from app.services.search_service import close_es, init_es
from app.services.storage_service import StorageService


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ARG001
    """Application lifespan: initialise and tear down connections."""
    # ── Startup ──────────────────────────────────────────────────────
    # Run all infrastructure initialisation in parallel with individual
    # timeouts so a single slow service doesn't block the entire startup.
    async def _init_redis() -> None:
        await init_redis(settings.REDIS_URL)

    async def _init_bootstrap() -> None:
        from app.db.session import async_session_factory
        from app.services.bootstrap_service import run_bootstrap

        async with async_session_factory() as session:
            result = await run_bootstrap(session)
            print(f"Bootstrap result: {result}")

    async def _init_minio() -> None:
        storage = StorageService(settings)
        await storage.init_storage()
        logger.info("MinIO bucket '%s' ready", settings.MINIO_BUCKET)

    async def _init_es() -> None:
        await init_es()
        from app.services.search_service import init_search_index

        await init_search_index()
        logger.info("ES client + index ready")

    startup_tasks = [
        _init_redis(),
        _init_bootstrap(),
        _init_minio(),
        _init_es(),
    ]

    results = await asyncio.gather(
        *(asyncio.wait_for(t, timeout=15) for t in startup_tasks),
        return_exceptions=True,
    )

    for name, result in zip(
        ["Redis", "Bootstrap", "MinIO", "Elasticsearch"],
        results,
    ):
        if isinstance(result, Exception):
            logger.warning("%s init failed (non-fatal): %s", name, result)
        elif isinstance(result, TimeoutError):
            logger.warning("%s init timed out after 15s (non-fatal)", name)
        else:
            logger.info("%s initialized", name)

    # ── Celery worker ─────────────────────────────────────────────────
    # Celery worker is managed via Docker Compose (``celery-worker`` service)
    # or started manually with ``celery -A app.tasks.celery_app worker ...``.
    # Do NOT auto-spawn a subprocess here — it causes process pile-ups
    # when uvicorn runs with ``--reload``.
    logger.info(
        "Celery worker auto-start disabled — use Docker Compose or "
        "``celery -A app.tasks.celery_app worker`` manually"
    )

    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    await close_es()
    await close_http_client()
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(",")
    if settings.CORS_ORIGINS != "*"
    else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting (slowapi) ──────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Exception handlers ───────────────────────────────────────────────
register_exception_handlers(app)

# ── Routers ──────────────────────────────────────────────────────────
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/health")
async def health():
    """Health-check endpoint (outside /api/v1 prefix)."""
    return {"status": "ok"}
