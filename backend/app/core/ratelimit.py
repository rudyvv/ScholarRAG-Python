"""Rate-limiting configuration using slowapi.

Provides a shared ``Limiter`` instance keyed by client IP, and
convenience limit strings for common endpoint groups.

Usage in route handlers::

    from app.core.ratelimit import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    async def login(request: Request, ...):
        ...

For class-based views decorate the method *and* pass ``request``.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# ── Shared limiter instance (Redis-backed for multi-worker support) ────
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=f"{settings.REDIS_URL}/1",  # Use DB 1 to avoid key conflicts
)

# ── Named limits (reusable strings) ──────────────────────────────────────
LOGIN_LIMIT = "10/minute"  # POST /auth/login
REGISTER_LIMIT = "5/minute"  # POST /auth/register
CHAT_LIMIT = "30/minute"  # POST /chat/ask
DEFAULT_LIMIT = "100/minute"  # All other authenticated endpoints
