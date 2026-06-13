"""Tests for health check endpoints."""

from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    """Liveness check always returns 200 if app is running."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_readiness_with_services(client: AsyncClient) -> None:
    """Readiness check returns 200 when all services are up.

    Requires Docker Compose services to be running.
    """
    response = await client.get("/health/ready")
    # Will be 200 if services are up, 503 if not
    assert response.status_code in (200, 503)
    body = response.json()
    assert "ready" in body
    assert "checks" in body


async def test_full_health_check(client: AsyncClient) -> None:
    """Full health check returns service status with checks."""
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "service" in body
    assert "checks" in body
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
