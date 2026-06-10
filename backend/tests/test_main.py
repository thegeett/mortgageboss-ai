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
    """Health check returns healthy status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
