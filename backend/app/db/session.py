from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession, sessionmaker

from app.config import settings

# ── Async (FastAPI) ───────────────────────────────────────────────────
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Sync (Celery workers) ────────────────────────────────────────────
# Build a sync DATABASE_URL from settings (pymysql sync driver)
_sync_db_url = (
    f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}"
    "?charset=utf8mb4"
)

sync_engine = create_engine(
    _sync_db_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=settings.DEBUG,
)

sync_session_factory = sessionmaker(
    bind=sync_engine,
    class_=SyncSession,
    expire_on_commit=False,
)


def get_sync_db() -> SyncSession:
    """Return a sync DB session — caller must close it.

    Intended for Celery tasks and standalone scripts.
    Use as a context manager::

        db = get_sync_db()
        try:
            ...
        finally:
            db.close()
    """
    return sync_session_factory()
