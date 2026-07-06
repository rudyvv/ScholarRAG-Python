"""Async CRUD service for InviteCode operations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import InviteCode


async def create_invite_code(
    db: AsyncSession,
    code: str,
    max_uses: int = 1,  # noqa: ARG001
    expires_at: datetime | None = None,
) -> InviteCode:
    """Create a new invite code.

    Args:
        db: Database async session.
        code: Unique invite code string.
        max_uses: Maximum number of uses (reserved for future use).
        expires_at: Optional expiration datetime.

    Returns:
        The newly created InviteCode instance.

    Raises:
        ValueError: If the code already exists.
    """
    # Check for duplicate code
    result = await db.execute(select(InviteCode).where(InviteCode.code == code))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Invite code '{code}' already exists")

    invite = InviteCode(
        code=code,
        is_used=False,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


async def validate_invite_code(db: AsyncSession, code: str) -> InviteCode:
    """Validate an invite code.

    Checks that the code exists, is not already used, and has not expired.

    Args:
        db: Database async session.
        code: The invite code string to validate.

    Returns:
        The matching InviteCode instance if valid.

    Raises:
        ValueError: If the code is invalid, already used, or expired.
    """
    result = await db.execute(select(InviteCode).where(InviteCode.code == code))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise ValueError("Invalid invite code")
    if invite.is_used:
        raise ValueError("Invite code has already been used")
    if invite.expires_at is not None and invite.expires_at < datetime.now(timezone.utc):
        raise ValueError("Invite code has expired")
    return invite


async def use_invite_code(
    db: AsyncSession,
    code: str,
    user_id: int,
) -> InviteCode:
    """Mark an invite code as used by the given user.

    Args:
        db: Database async session.
        code: The invite code string.
        user_id: ID of the user who is using the code.

    Returns:
        The updated InviteCode instance.

    Raises:
        ValueError: If the code does not exist or is already used.
    """
    invite = await validate_invite_code(db, code)
    invite.is_used = True
    invite.used_by = user_id
    await db.commit()
    await db.refresh(invite)
    return invite


async def list_invite_codes(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> tuple[list[InviteCode], int]:
    """List invite codes with pagination.

    Args:
        db: Database async session.
        page: Page number (1-indexed, default 1).
        size: Page size (default 20).

    Returns:
        A tuple of (list of InviteCode, total count).
    """
    count_query = select(func.count(InviteCode.id))
    count_result = await db.execute(count_query)
    total: int = count_result.scalar_one()

    query = select(InviteCode).offset((page - 1) * size).limit(size).order_by(InviteCode.created_at.desc())
    result = await db.execute(query)
    codes = list(result.scalars().all())

    return codes, total
