"""Bootstrap service: auto-create admin user, default invite codes, etc.

All functions are idempotent — safe to call on every application startup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import hash_password
from app.models.user import InviteCode, User, UserRole

logger = logging.getLogger(__name__)

# ── Admin credentials (read from Settings) ──────────────────────────────
_ADMIN_USERNAME: str = settings.ADMIN_USERNAME
_ADMIN_EMAIL: str = settings.ADMIN_EMAIL
_ADMIN_PASSWORD: str = settings.ADMIN_PASSWORD


async def init_admin_user(db: AsyncSession) -> str:
    """Create the initial admin user if none exists.

    Returns ``"created"`` or ``"skipped"``.
    """
    result = await db.execute(select(User).where(User.role == UserRole.ADMIN))
    existing = result.scalar_one_or_none()
    if existing is not None:
        logger.info("Admin user already exists (id=%s), skipping", existing.id)
        return "skipped"

    hashed = hash_password(_ADMIN_PASSWORD)
    admin = User(
        username=_ADMIN_USERNAME,
        email=_ADMIN_EMAIL,
        hashed_password=hashed,
        role=UserRole.ADMIN,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    logger.info("Created admin user (id=%s, email=%s)", admin.id, admin.email)
    return "created"


async def init_default_invite_codes(db: AsyncSession) -> str:
    """Create default invite codes if none exist.

    Returns ``"created"`` or ``"skipped"``.
    """
    result = await db.execute(select(InviteCode).limit(1))
    existing = result.scalar_one_or_none()
    if existing is not None:
        logger.info("Invite codes already exist, skipping defaults")
        return "skipped"

    expires_at = datetime.now(timezone.utc) + timedelta(days=365)
    codes = [
        InviteCode(code="PRE_INVITE_001", expires_at=expires_at),
        InviteCode(code="PRE_INVITE_002", expires_at=expires_at),
    ]
    db.add_all(codes)
    await db.commit()
    logger.info("Created %d default invite codes", len(codes))
    return "created"


async def init_default_model_providers(db: AsyncSession) -> str:
    """Create a default ``ModelProviderConfig`` from environment variables.

    Only creates a record when:
    1. No active provider exists yet, **and**
    2. At least ``LLM_API_KEY`` is configured (otherwise there's nothing
       meaningful to seed).

    Returns ``"created"`` or ``"skipped"``.
    """
    if not settings.LLM_API_KEY:
        logger.info("LLM_API_KEY not set — skipping default provider")
        return "skipped"

    from app.models.provider_config import ModelProviderConfig  # noqa: PLC0415
    from app.core.security import encrypt_api_key  # noqa: PLC0415

    result = await db.execute(
        select(ModelProviderConfig)
        .where(ModelProviderConfig.is_active.is_(True))
        .limit(1)
    )
    if result.scalar_one_or_none() is not None:
        logger.info("Active provider already exists — skipping default")
        return "skipped"

    provider = ModelProviderConfig(
        provider_name="default",
        api_base_url=settings.LLM_API_BASE_URL,
        api_key_ciphertext=encrypt_api_key(settings.LLM_API_KEY),
        model_name=settings.LLM_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dim=settings.EMBEDDING_DIM,
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    logger.info("Created default provider from env (id=%s)", provider.id)
    return "created"


async def run_bootstrap(db: AsyncSession) -> dict[str, str]:
    """Run all bootstrap initialisations in sequence.

    Returns a dict with per-task outcomes (``"created"`` or ``"skipped"``).
    """
    return {
        "admin": await init_admin_user(db),
        "invite_codes": await init_default_invite_codes(db),
        "model_providers": await init_default_model_providers(db),
    }
