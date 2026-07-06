"""ModelProviderConfig model."""

import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModelProviderConfig(Base):
    __tablename__ = "model_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_name: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    api_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_ciphertext: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    org_tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ModelProviderConfig(id={self.id}, provider={self.provider_name!r}, "
            f"model={self.model_name!r})>"
        )
