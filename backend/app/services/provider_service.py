"""Query helpers for active LLM / embedding provider configs from the DB.

Provides async functions that return the first active
``ModelProviderConfig`` for LLM chat and embedding respectively,
falling back to ``None`` when no DB record is found — callers should
then fall back to environment-variable defaults.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_config import ModelProviderConfig

logger = logging.getLogger(__name__)


async def get_active_llm_provider(
    db: AsyncSession,
) -> ModelProviderConfig | None:
    """Return the first active provider with a configured LLM *model_name*.

    Args:
        db: An active async database session.

    Returns:
        The ``ModelProviderConfig`` row, or ``None`` if none match.
    """
    result = await db.execute(
        select(ModelProviderConfig)
        .where(
            ModelProviderConfig.is_active.is_(True),
            ModelProviderConfig.model_name.isnot(None),
        )
        .order_by(ModelProviderConfig.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_embedding_provider(
    db: AsyncSession,
) -> ModelProviderConfig | None:
    """Return the first active provider with a configured *embedding_model*.

    Args:
        db: An active async database session.

    Returns:
        The ``ModelProviderConfig`` row, or ``None`` if none match.
    """
    result = await db.execute(
        select(ModelProviderConfig)
        .where(
            ModelProviderConfig.is_active.is_(True),
            ModelProviderConfig.embedding_model.isnot(None),
        )
        .order_by(ModelProviderConfig.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
