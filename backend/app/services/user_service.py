"""Async CRUD service for User operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import InviteCode, User
from app.schemas.user import UserUpdate, _validate_password_strength


async def create_user(
    db: AsyncSession,
    username: str,
    email: Optional[str],
    password: str,
    invite_code: Optional[str] = None,
) -> User:
    """Create a new user.

    Validates password strength, checks username uniqueness,
    hashes the password, and optionally validates an invite code.

    Args:
        db: Database async session.
        username: Unique username (3-50 chars).
        email: Optional email address.
        password: Plain-text password (min 8 chars, letter + digit).
        invite_code: Optional invite code string.

    Returns:
        The newly created User instance.

    Raises:
        ValueError: If username is taken or invite code is invalid/expired.
    """
    # Validate password strength
    _validate_password_strength(password)

    # Check username uniqueness
    existing = await get_user_by_username(db, username)
    if existing is not None:
        raise ValueError(f"Username '{username}' is already taken")

    # Check email uniqueness (if provided)
    if email is not None:
        existing_email = await get_user_by_email(db, email)
        if existing_email is not None:
            raise ValueError(f"Email '{email}' is already registered")

    # Validate invite code if provided
    if invite_code is not None:
        result = await db.execute(
            select(InviteCode).where(InviteCode.code == invite_code)
        )
        invite: InviteCode | None = result.scalar_one_or_none()
        if invite is None:
            raise ValueError("Invalid invite code")
        if invite.is_used:
            raise ValueError("Invite code has already been used")
        if invite.expires_at is not None and invite.expires_at < datetime.now(
            timezone.utc
        ):
            raise ValueError("Invite code has expired")

    # Hash password and create user
    hashed = hash_password(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed,
    )

    db.add(user)
    await db.flush()

    # Mark invite code as used if applicable
    if invite_code is not None:
        invite.is_used = True
        invite.used_by = user.id

    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    """Authenticate a user by email and password.

    Args:
        db: Database async session.
        email: User email address.
        password: Plain-text password.

    Returns:
        The authenticated User, or None if credentials are invalid.
    """
    user = await get_user_by_email(db, email)
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """Look up a user by primary key.

    Args:
        db: Database async session.
        user_id: User ID.

    Returns:
        The matching User, or None if not found.
    """
    return await db.get(User, user_id)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Look up a user by email address.

    Args:
        db: Database async session.
        email: Email address.

    Returns:
        The matching User, or None if not found.
    """
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """Look up a user by username.

    Args:
        db: Database async session.
        username: Username.

    Returns:
        The matching User, or None if not found.
    """
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def update_user(
    db: AsyncSession,
    user_id: int,
    data: UserUpdate,
) -> User:
    """Update an existing user's fields.

    Only updates the fields that are explicitly set (not None).
    Re-checks username uniqueness if username is being changed.

    Args:
        db: Database async session.
        user_id: User ID.
        data: UserUpdate instance with fields to change.

    Returns:
        The updated User instance.

    Raises:
        ValueError: If the new username is already taken.
    """
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise ValueError(f"User with id {user_id} not found")

    update_fields = data.model_dump(exclude_unset=True)

    # Re-check username uniqueness if changing
    if "username" in update_fields and update_fields["username"] != user.username:
        existing = await get_user_by_username(db, update_fields["username"])
        if existing is not None:
            raise ValueError(
                f"Username '{update_fields['username']}' is already taken"
            )

    for field, value in update_fields.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


async def change_password(
    db: AsyncSession,
    user_id: int,
    old_password: str,
    new_password: str,
) -> User:
    """Change a user's password.

    Validates the old password before updating to the new one.

    Args:
        db: Database async session.
        user_id: User ID.
        old_password: Current plain-text password for verification.
        new_password: New plain-text password (validated for strength).

    Returns:
        The updated User instance.

    Raises:
        ValueError: If old password is incorrect or user not found.
    """
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise ValueError("User not found")

    if not verify_password(old_password, user.hashed_password):
        raise ValueError("Old password is incorrect")

    _validate_password_strength(new_password)
    user.hashed_password = hash_password(new_password)

    await db.commit()
    await db.refresh(user)
    return user


async def list_users(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
    org_tag: Optional[str] = None,
) -> tuple[list[User], int]:
    """List users with pagination and optional org_tag filter.

    Args:
        db: Database async session.
        page: Page number (1-indexed, default 1).
        size: Page size (default 20).
        org_tag: Optional organization tag to filter by.

    Returns:
        A tuple of (list of User, total count).
    """
    query = select(User)
    count_query = select(User)

    if org_tag is not None:
        query = query.where(User.org_tags == org_tag)
        count_query = count_query.where(User.org_tags == org_tag)

    # Get total count
    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())

    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    users = list(result.scalars().all())

    return users, total
