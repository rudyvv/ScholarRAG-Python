"""ModelProviderConfig CRUD API."""

import logging
import time
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from app.core.deps import get_current_user, get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.core.security import decrypt_api_key, encrypt_api_key
from app.models.provider_config import ModelProviderConfig
from app.models.user import User
from app.schemas.provider import (
    ModelProviderConfigCreate,
    ModelProviderConfigResponse,
    ModelProviderConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_response(cfg: ModelProviderConfig) -> ModelProviderConfigResponse:
    """Convert ORM model to response schema, masking the API key."""
    prefix = None
    if cfg.api_key_ciphertext:
        try:
            plain = decrypt_api_key(cfg.api_key_ciphertext)
            prefix = plain[:8] + "..." if len(plain) > 8 else plain
        except Exception:
            prefix = "[decrypt error]"
    return ModelProviderConfigResponse(
        id=cfg.id,
        provider_name=cfg.provider_name,
        api_base_url=cfg.api_base_url,
        api_key_prefix=prefix,
        model_name=cfg.model_name,
        embedding_model=cfg.embedding_model,
        embedding_dim=cfg.embedding_dim,
        is_active=cfg.is_active,
        org_tag=cfg.org_tag,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )  # type: ignore[call-arg]


@router.get("/")
async def list_models(
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """List all provider configurations."""
    result = await db.execute(
        select(ModelProviderConfig).order_by(ModelProviderConfig.created_at.desc())
    )
    configs = result.scalars().all()
    items = [_to_response(c) for c in configs]
    return success_response(
        {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}
    )


@router.get("/{model_id}")
async def get_model(
    model_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Get a single provider configuration by ID."""
    cfg = await db.get(ModelProviderConfig, model_id)
    if not cfg:
        raise NotFoundException("Model provider config not found")
    return success_response(_to_response(cfg).model_dump(mode="json"))


@router.post("/", status_code=201)
async def create_model(
    body: ModelProviderConfigCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Create a new provider configuration. API key is encrypted at rest."""
    ciphertext = encrypt_api_key(body.api_key) if body.api_key else None
    cfg = ModelProviderConfig(
        provider_name=body.provider_name,
        api_base_url=body.api_base_url,
        api_key_ciphertext=ciphertext,
        model_name=body.model_name,
        embedding_model=body.embedding_model,
        embedding_dim=body.embedding_dim,
        is_active=body.is_active,
        org_tag=body.org_tag,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return success_response(_to_response(cfg).model_dump(mode="json"), status_code=201)


@router.put("/{model_id}")
async def update_model(
    model_id: int,
    body: ModelProviderConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Update an existing provider configuration."""
    cfg = await db.get(ModelProviderConfig, model_id)
    if not cfg:
        raise NotFoundException("Model provider config not found")

    update_data = body.model_dump(exclude_unset=True)
    # Handle api_key specially — encrypt it
    if "api_key" in update_data:
        api_key = update_data.pop("api_key")
        cfg.api_key_ciphertext = encrypt_api_key(api_key) if api_key else None

    for field, value in update_data.items():
        setattr(cfg, field, value)

    await db.commit()
    await db.refresh(cfg)
    return success_response(_to_response(cfg).model_dump(mode="json"))


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Delete a provider configuration."""
    cfg = await db.get(ModelProviderConfig, model_id)
    if not cfg:
        raise NotFoundException("Model provider config not found")
    await db.delete(cfg)
    await db.commit()
    return success_response({"message": "Model provider config deleted"})


@router.post("/{model_id}/test")
async def test_model_connection(
    model_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Test connection to a model provider.

    Decrypts the stored API key and makes a test ``GET {base_url}/models``
    request with Bearer authentication. Returns success status, detected
    model name, and response latency.
    """
    cfg = await db.get(ModelProviderConfig, model_id)
    if not cfg:
        raise NotFoundException("Model provider config not found")

    if not cfg.api_key_ciphertext:
        return success_response(
            data={
                "success": False,
                "model_name": cfg.model_name,
                "latency_ms": None,
                "error": "No API key configured",
            },
        )

    # Decrypt the Fernet-encrypted API key
    try:
        api_key = decrypt_api_key(cfg.api_key_ciphertext)
    except Exception as exc:
        return success_response(
            data={
                "success": False,
                "model_name": cfg.model_name,
                "latency_ms": None,
                "error": f"Failed to decrypt API key: {exc}",
            },
        )

    start = time.monotonic()
    try:
        # Use /chat/completions with a minimal ping-pong request (this is the
        # endpoint actually used by the RAG pipeline, so it's a real test).
        url = f"{cfg.api_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": cfg.model_name or "Qwen/Qwen3-8B",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5,
        }
        logger.info("Testing connection to %s (model=%s)", url, cfg.model_name)
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
        ) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Response: status=%s, elapsed=%dms", resp.status_code, elapsed_ms
            )

            if resp.status_code != 200:
                return success_response(
                    data={
                        "success": False,
                        "model_name": cfg.model_name,
                        "latency_ms": elapsed_ms,
                        "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    },
                )

            return success_response(
                data={
                    "success": True,
                    "model_name": cfg.model_name,
                    "latency_ms": elapsed_ms,
                },
            )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error_msg = str(exc)[:200] or "Unknown error (no exception message)"
        logger.exception("Connection test exception for model %d", model_id)
        return success_response(
            data={
                "success": False,
                "model_name": cfg.model_name,
                "latency_ms": elapsed_ms,
                "error": error_msg,
            },
        )
