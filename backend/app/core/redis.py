"""Redis connection management.

The async Redis client's connections are bound to the event loop that created them.
The API runs on one long-lived loop, but Celery runs each task on a **fresh** loop
(``asyncio.run`` per task — see :mod:`app.tasks.base`), so a process-global singleton
would carry connections bound to an earlier, now-closed loop and raise
``RuntimeError: Event loop is closed`` on the next task. We therefore key the cached
client on the **running event loop** and rebuild when it changes — mirroring
``task_session``'s per-loop engine. Under the API's single loop the same client is
reused (no behaviour change); under the worker each task gets a loop-local client.
"""

import asyncio

from redis.asyncio import Redis, from_url

from app.core.config import settings

# Module-level client, cached per event loop (created on first access).
_redis_client: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def get_redis_client() -> Redis:
    """Get or create the async Redis client bound to the running event loop.

    Rebuilds the client when the running loop differs from the one the cached client
    was created on (the Celery per-task loop case), so a client bound to a closed loop
    is never reused. Outside a running loop, returns/creates a client as before.
    """
    global _redis_client, _redis_loop
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _redis_client is None or (loop is not None and loop is not _redis_loop):
        # Drop any stale client (its connections are bound to a now-closed loop, so it
        # cannot be awaited-closed from here). The new one binds to the current loop.
        _redis_client = from_url(  # type: ignore[no-untyped-call]
            str(settings.redis_url),
            decode_responses=True,
            health_check_interval=30,
        )
        _redis_loop = loop
    return _redis_client


async def check_redis_connection() -> bool:
    """Verify Redis is reachable. Used by health checks."""
    try:
        client = get_redis_client()
        await client.ping()
        return True
    except Exception:
        return False


async def close_redis_connections() -> None:
    """Close Redis connections. Called on application shutdown."""
    global _redis_client, _redis_loop
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        _redis_loop = None
