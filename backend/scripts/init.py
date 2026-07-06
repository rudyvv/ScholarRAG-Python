"""Standalone bootstrap script.

Run::

    uv run python scripts/init.py

or::

    cd backend && uv run python scripts/init.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")  # allow running from backend/


async def main() -> None:
    """Execute bootstrap and print results."""
    from app.db.session import async_session_factory
    from app.services.bootstrap_service import run_bootstrap

    async with async_session_factory() as session:
        result = await run_bootstrap(session)
        print(f"Bootstrap complete: {result}")


if __name__ == "__main__":
    asyncio.run(main())
