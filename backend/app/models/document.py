"""Document and DocumentChunk models."""

import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocStatus(StrEnum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("file_md5", "user_id", name="uk_md5_user"),
        Index("idx_doc_user_id", "user_id"),
        Index("idx_doc_org_tag", "org_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_md5: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    doc_status: Mapped[DocStatus] = mapped_column(
        SAEnum(DocStatus, values_callable=lambda x: [e.value for e in x]),
        default=DocStatus.UPLOADING,
        nullable=False,
    )
    org_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    owner: Mapped["User"] = relationship(
        "User", back_populates="documents", foreign_keys=[user_id]
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename={self.filename!r}, status={self.doc_status})>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uk_doc_id_chunk_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Milvus vector ID reference
    chunk_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    # Relationships
    document: Mapped["Document"] = relationship(
        "Document", back_populates="chunks", foreign_keys=[document_id]
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk(id={self.id}, doc_id={self.document_id}, "
            f"chunk_idx={self.chunk_index})>"
        )
