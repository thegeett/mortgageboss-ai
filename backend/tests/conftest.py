"""Pytest fixtures and configuration."""

from collections.abc import AsyncIterator

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client for testing the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
