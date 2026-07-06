"""Pydantic schemas for User CRUD operations."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.user import UserRole


def _validate_password_strength(password: str) -> str:
    """Validate password strength: min 8 chars, at least one letter and one digit."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    return password


class UserCreate(BaseModel):
    """Request schema for creating a new user."""

    username: str
    email: Optional[str] = None
    password: str
    invite_code: Optional[str] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters long")
        if len(v) > 50:
            raise ValueError("Username must be at most 50 characters long")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserLogin(BaseModel):
    """Request schema for user login."""

    email: str
    password: str


class UserResponse(BaseModel):
    """Response schema for user data (excludes hashed_password)."""

    id: int
    username: str
    email: Optional[str] = None
    role: UserRole
    is_active: bool
    org_tags: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    """Request schema for updating an existing user."""

    username: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if v is not None and len(v) > 50:
            raise ValueError("Username must be at most 50 characters long")
        return v


class PasswordChange(BaseModel):
    """Request schema for changing a user's password."""

    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class RefreshRequest(BaseModel):
    """Request schema for refreshing an access token."""

    refresh_token: str


class UserList(BaseModel):
    """Response schema for a paginated list of users."""

    items: list[UserResponse]
    total: int
    page: int
    size: int
