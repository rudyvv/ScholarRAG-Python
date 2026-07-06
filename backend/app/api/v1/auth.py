"""Auth-related API endpoints.

Provides registration, login, token refresh, profile management,
and password change.
"""

import hashlib

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_redis
from app.core.exceptions import BadRequestException, UnauthorizedException
from app.core.ratelimit import LOGIN_LIMIT, REGISTER_LIMIT, limiter
from app.core.redis_manager import RedisManager
from app.core.response import success_response
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.models.user import User
from app.schemas.user import (
    PasswordChange,
    RefreshRequest,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from app.services.user_service import (
    authenticate_user,
    change_password,
    create_user,
    get_user_by_id,
    update_user,
)

# Extract raw Bearer token for the logout endpoint
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)

router = APIRouter()


@router.post("/register", status_code=201)
@limiter.limit(REGISTER_LIMIT)
async def register(
    request: Request,  # noqa: ARG001 — consumed by slowapi
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user."""
    try:
        user = await create_user(
            db,
            username=body.username,
            email=body.email,
            password=body.password,
            invite_code=body.invite_code,
        )
    except ValueError as e:
        raise BadRequestException(str(e)) from e

    return success_response(
        data=UserResponse.model_validate(user),
        message="Registration successful",
        status_code=201,
    )


@router.post("/login")
@limiter.limit(LOGIN_LIMIT)
async def login(
    request: Request,  # noqa: ARG001 — consumed by slowapi
    body: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user and return JWT tokens."""
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise UnauthorizedException("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedException("User account is disabled")

    access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return success_response(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        },
    )


@router.post("/logout")
async def logout(
    token: str | None = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    redis: RedisManager = Depends(get_redis),
):
    """Log out the current user by blacklisting the access token.

    The token's SHA-256 hash is stored in Redis with a TTL matching its
    remaining lifetime, so it cannot be reused even before natural expiry.
    """
    if token is None:
        raise UnauthorizedException("Not authenticated")

    payload = decode_access_token(token)
    exp = payload.get("exp") if payload else None

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    blacklist_key = f"access_blacklist:{token_hash}"

    if exp is not None:
        import time  # noqa: PLC0415

        ttl = max(int(exp) - int(time.time()), 0)
    else:
        ttl = 900  # fallback 15 min

    await redis.set_key(blacklist_key, "1", expire=ttl)

    return success_response(message="Logged out successfully")


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisManager = Depends(get_redis),
):
    """Issue a new access token using a valid refresh token.

    Invalidates the used refresh token via a Redis blacklist so it
    cannot be replayed.
    """
    raw_token = body.refresh_token

    # ── Blacklist check ────────────────────────────────────────────
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    blacklist_key = f"refresh_blacklist:{token_hash}"
    if await redis.exists(blacklist_key):
        raise UnauthorizedException("Refresh token has already been used")

    payload = decode_refresh_token(raw_token)
    if payload is None:
        raise UnauthorizedException("Invalid or expired refresh token")

    user_id: object = payload.get("sub")
    if user_id is None:
        raise UnauthorizedException("Invalid token payload")

    user = await get_user_by_id(db, int(user_id))  # type: ignore[arg-type]
    if user is None or not user.is_active:
        raise UnauthorizedException("User not found or inactive")

    # ── Blacklist the old refresh token (TTL = remaining lifetime) ──
    exp = payload.get("exp")
    if exp is not None:
        import time

        ttl = max(int(exp) - int(time.time()), 0)
    else:
        ttl = 900  # fallback 15 min
    await redis.set_key(blacklist_key, "1", expire=ttl)

    access_token = create_access_token({"sub": str(user.id), "role": user.role.value})

    return success_response(
        data={"access_token": access_token, "token_type": "bearer"},
    )


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's profile."""
    return success_response(
        data=UserResponse.model_validate(current_user),
    )


@router.put("/me")
async def update_me(
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the authenticated user's profile fields."""
    try:
        updated_user = await update_user(db, current_user.id, body)
    except ValueError as e:
        raise BadRequestException(str(e)) from e

    return success_response(
        data=UserResponse.model_validate(updated_user),
    )


@router.put("/me/password")
async def change_my_password(
    body: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the authenticated user's password."""
    try:
        await change_password(db, current_user.id, body.old_password, body.new_password)
    except ValueError as e:
        raise BadRequestException(str(e)) from e

    return success_response(message="Password changed successfully")
