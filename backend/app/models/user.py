"""User and InviteCode models."""

import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models.conversation import ConversationSession
    from app.models.document import Document

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(StrEnum):
    """User role enumeration."""

    USER = "user"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.USER,
        nullable=False,
    )
    org_tags: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="owner", passive_deletes=True
    )
    conversation_sessions: Mapped[list["ConversationSession"]] = relationship(
        "ConversationSession", back_populates="user", passive_deletes=True
    )
    invite_codes: Mapped[list["InviteCode"]] = relationship(
        "InviteCode", back_populates="used_by_user", passive_deletes=True
    )
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username!r}, role={self.role})>"


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    used_by_user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="invite_codes", foreign_keys=[used_by]
    )

    def __repr__(self) -> str:
        return f"<InviteCode(id={self.id}, code={self.code!r}, is_used={self.is_used})>"
