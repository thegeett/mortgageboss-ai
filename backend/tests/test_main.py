"""Tests for main application endpoints."""

from httpx import AsyncClient


async def test_root_endpoint(client: AsyncClient) -> None:
    """Root endpoint returns service info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "mortgageboss-ai"
    assert "version" in data


async def test_health_check(client: AsyncClient) -> None:
    """Health check returns service status with dependency checks.

    Returns 200 when all dependencies are up, 503 otherwise.
    """
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["service"] == "mortgageboss-ai"
    assert "version" in body
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
