"""FastAPI dependency injection providers.

Shared dependencies (database session, authenticated user, Redis, etc.)
that can be injected into route handlers via ``Depends(...)``.
"""

import hashlib
from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import redis_manager as _redis_mgr
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_access_token
from app.db.session import async_session_factory
from app.models.user import User, UserRole

# ── OAuth2 scheme (extracts Bearer token from ``Authorization`` header) ──
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:  # type: ignore[misc]
    """Yield an async database session (auto-closed on completion)."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_redis() -> "AsyncGenerator[_redis_mgr.RedisManager, None]":
    """Yield the global ``RedisManager`` singleton.

    Raises:
        RuntimeError: If Redis has not been initialised during startup.
    """
    if _redis_mgr.redis_manager is None:
        msg = "Redis not initialised — call init_redis() during startup"
        raise RuntimeError(msg)
    yield _redis_mgr.redis_manager


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: _redis_mgr.RedisManager = Depends(get_redis),  # noqa: B008
) -> User:
    """Resolve the current authenticated user from the JWT bearer token.

    Also checks the Redis access-token blacklist so that logged-out
    tokens are rejected even before their natural expiry.

    Raises:
        UnauthorizedException: If the token is missing, invalid,
            blacklisted, or the user does not exist or is inactive.
    """
    if token is None:
        raise UnauthorizedException(message="Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise UnauthorizedException(message="Invalid or expired token")

    # ── Blacklist check ─────────────────────────────────────────────
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if await redis.exists(f"access_blacklist:{token_hash}"):
        raise UnauthorizedException(message="Token has been revoked")

    user_id: object = payload.get("sub")
    if user_id is None:
        raise UnauthorizedException(message="Invalid token payload")

    result = await db.execute(select(User).where(User.id == int(user_id)))  # type: ignore[arg-type]
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedException(message="User not found")
    if not user.is_active:
        raise UnauthorizedException(message="User is inactive")

    return user


async def get_current_active_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Resolve the current authenticated admin user.

    Requires that the authenticated user has the ``ADMIN`` role.

    Raises:
        ForbiddenException: If the user does not have admin privileges.
    """
    if current_user.role != UserRole.ADMIN:
        raise ForbiddenException(message="Admin privileges required")
    return current_user
