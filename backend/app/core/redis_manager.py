"""Async Redis connection manager.

Provides a ``RedisManager`` class that wraps ``redis.asyncio.Redis``
and module-level helpers for application lifespan management.
"""

import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisManager:
    """Manages an async Redis connection.

    Usage::

        manager = RedisManager("redis://:password@host:6379/0")
        await manager.connect()
        await manager.set_key("foo", "bar")
        val = await manager.get_key("foo")
        await manager.close()
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis | None = None

    async def connect(self) -> None:
        """Open the async Redis connection and verify reachability."""
        self._client = Redis.from_url(self._url, decode_responses=True)
        await self.ping()
        logger.info("Redis connected at %s", self._url)

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Redis connection closed")

    async def ping(self) -> bool:
        """Check whether Redis is reachable."""
        if self._client is None:
            return False
        try:
            return await self._client.ping()
        except Exception:
            return False

    async def set_key(self, key: str, value: str, expire: int | None = None) -> None:
        """Set a key-value pair with optional TTL (seconds)."""
        await self._client.set(key, value, ex=expire)  # type: ignore[union-attr]

    async def get_key(self, key: str) -> str | None:
        """Retrieve the value for *key*, or ``None`` if missing."""
        return await self._client.get(key)  # type: ignore[union-attr]

    async def delete_key(self, key: str) -> None:
        """Delete *key*."""
        await self._client.delete(key)  # type: ignore[union-attr]

    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists."""
        result = await self._client.exists(key)  # type: ignore[union-attr]
        return bool(result)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Return all fields and values of a hash at *key*."""
        return await self._client.hgetall(key)  # type: ignore[union-attr]

    async def rpush(self, key: str, value: str) -> int:
        """Append *value* to the list at *key*."""
        return await self._client.rpush(key, value)  # type: ignore[union-attr]

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        """Trim the list at *key* to the specified range."""
        await self._client.ltrim(key, start, stop)  # type: ignore[union-attr]

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return a range of elements from the list at *key*."""
        return await self._client.lrange(key, start, stop)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Module-level singleton helpers (used by lifespan / deps)
# ---------------------------------------------------------------------------

redis_manager: RedisManager | None = None


async def init_redis(url: str) -> RedisManager:
    """Initialize the global ``RedisManager`` singleton.

    Args:
        url: Redis connection URL (e.g. ``redis://:password@host:6379/0``).

    Returns:
        The initialized ``RedisManager`` instance.
    """
    global redis_manager  # noqa: PLW0603
    manager = RedisManager(url)
    await manager.connect()
    redis_manager = manager
    return manager


async def close_redis() -> None:
    """Close the global ``RedisManager`` singleton."""
    global redis_manager  # noqa: PLW0603
    if redis_manager is not None:
        await redis_manager.close()
        redis_manager = None
