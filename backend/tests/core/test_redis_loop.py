"""The Redis client must survive Celery's fresh-event-loop-per-task model.

Regression for the worker bug where ``get_redis_client`` returned a process-global
client bound to the first task's event loop, so the *next* task (a new loop, via
``asyncio.run``) crashed with ``RuntimeError: Event loop is closed`` when it touched
the per-file needs lock. The client is now keyed on the running loop and rebuilt when
it changes.

These run a coroutine via ``asyncio.run`` directly (NOT the pytest-asyncio loop) to
reproduce the per-task loop lifecycle. They need a reachable Redis (the same one the
lock tests use).
"""

import asyncio

import pytest
from app.core import redis as redis_module
from app.core.redis import get_redis_client


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module client/loop around each test so loop A actually creates it."""
    redis_module._redis_client = None
    redis_module._redis_loop = None
    yield
    redis_module._redis_client = None
    redis_module._redis_loop = None


def test_client_usable_across_fresh_task_loops() -> None:
    """Two ``asyncio.run`` loops (like two Celery tasks) both ping — no closed-loop crash."""

    async def _ping() -> bool:
        return bool(await get_redis_client().ping())

    # Loop A creates the client; loop A then closes (asyncio.run tears it down).
    assert asyncio.run(_ping()) is True
    # Loop B is fresh — before the fix this raised "RuntimeError: Event loop is closed"
    # because the cached client's connection was bound to the closed loop A.
    assert asyncio.run(_ping()) is True


def test_client_is_rebuilt_for_a_new_loop() -> None:
    """The cached client is rebuilt (not reused) when the running loop changes."""

    async def _client_and_loop() -> tuple[int, int]:
        # The loop the client is bound to, and the client identity.
        client = get_redis_client()
        await client.ping()
        return id(client), id(redis_module._redis_loop)

    _, loop_a = asyncio.run(_client_and_loop())
    _, loop_b = asyncio.run(_client_and_loop())
    assert loop_a != loop_b  # bound to a different (new) loop each task


async def test_same_loop_reuses_one_client() -> None:
    """Within one loop (the API case) repeated calls return the SAME client."""
    first = get_redis_client()
    second = get_redis_client()
    assert first is second
