"""Redis connection management."""

from redis.asyncio import Redis, from_url

from app.core.config import settings

# Module-level client (created on first access)
_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    """Get or create the async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(  # type: ignore[no-untyped-call]
            str(settings.redis_url),
            decode_responses=True,
            health_check_interval=30,
        )
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
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
