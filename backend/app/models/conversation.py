"""ConversationSession and ConversationMessage models."""

import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="conversation_sessions"
    )
    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage", back_populates="session", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<ConversationSession(id={self.id}, title={self.title!r})>"


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("idx_msg_session_id", "session_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversation_sessions.id"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="messages"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage(id={self.id}, session_id={self.session_id}, "
            f"role={self.role})>"
        )
