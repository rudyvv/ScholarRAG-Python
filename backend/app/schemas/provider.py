"""Pydantic schemas for ModelProviderConfig."""

import datetime

from pydantic import BaseModel


class ModelProviderConfigCreate(BaseModel):
    """Schema for creating a provider config. ``api_key`` is plaintext
    and will be encrypted at rest via ``Fernet``."""

    provider_name: str
    api_base_url: str
    api_key: str | None = None
    model_name: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    is_active: bool = True
    org_tag: str | None = None


class ModelProviderConfigUpdate(BaseModel):
    """Partial-update schema; all fields optional."""

    provider_name: str | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    is_active: bool | None = None
    org_tag: str | None = None


class ModelProviderConfigResponse(BaseModel):
    """Response schema — masks the stored API key with a prefix."""

    id: int
    provider_name: str
    api_base_url: str
    api_key_prefix: str | None = None
    model_name: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    is_active: bool
    org_tag: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
