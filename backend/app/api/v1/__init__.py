"""API v1 router.

All version-1 endpoints are registered under ``/api/v1``.
Route handlers are defined under ``routes/`` (Phase 2).
"""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.models import router as models_router
from app.api.v1.search import router as search_router
from app.api.v1.tasks import router as tasks_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(admin_router, prefix="/admin", tags=["admin"])
api_v1_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_v1_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_v1_router.include_router(models_router, prefix="/models", tags=["models"])
api_v1_router.include_router(search_router, prefix="/search", tags=["search"])
api_v1_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
