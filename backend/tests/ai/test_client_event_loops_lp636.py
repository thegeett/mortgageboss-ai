"""LP-636 defect 1 — a cached HTTP client must not outlive the event loop that opened its pool.

``get_anthropic_client`` is ``lru_cache``d, while ``run_async`` (``app/tasks/base.py``) is
``asyncio.run``: a FRESH event loop per Celery task, closed when the task ends. A pooled
keep-alive connection outlives the loop it was opened on, and the next task that takes it from the
pool fails instantly with ``RuntimeError: Event loop is closed`` — surfaced by the SDK as
``APIConnectionError``, at 1-5ms, without reaching the network. On staging that cost 5 of 44
documents in a single upload.

THE FIX IS AT THE TASK BOUNDARY, NOT IN THE CLIENT. Pooling is correct and valuable WITHIN a task
— one verification run makes hundreds of calls on one loop — so it stays on. ``run_async`` closes
and clears the client inside the loop, before that loop ends. These tests pin both halves: that
the underlying hazard is real, and that the boundary neutralises it.

WHY A REAL SOCKET. The failure is in the transport, so a mocked transport cannot show it. The
claim these tests replace was measured as "three separate ``asyncio.run()`` loops returned 200
each time" — which passes even with the bug present, because the SDK pool sets
``keepalive_expiry=5.0`` and three sequential calls each clear five seconds. So these drive calls
BACK TO BACK inside that window, which is the burst condition that actually breaks.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading
from collections.abc import Iterator
from functools import lru_cache

import httpx
import pytest
import structlog
from app.ai import client as client_module
from app.tasks import base as base_module
from app.tasks.base import run_async


class _Handler(http.server.BaseHTTPRequestHandler):
    """Minimal keep-alive JSON endpoint. HTTP/1.1 so the connection is offered for reuse —
    without that the pool has nothing to hold and the hazard cannot appear."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # BaseHTTPRequestHandler's required spelling
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr access log."""


@pytest.fixture
def keepalive_server() -> Iterator[str]:
    # THREADING, not plain TCPServer. With HTTP/1.1 keep-alive a handler stays in its read loop
    # waiting for the next request on that connection; a single-threaded server therefore never
    # gets back to accept(), and the next connection blocks until its timeout. That hangs the
    # file rather than failing it, which is a much worse test to inherit.
    #
    # It binds and listens in the constructor, before the thread starts, so a request arriving
    # early queues on the backlog rather than being refused — no readiness race.
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/x"
    finally:
        server.shutdown()
        server.server_close()


class _SdkShapedClient:
    """An httpx client wearing the Anthropic client's surface.

    The SDK spells its async shutdown ``close()``; httpx spells it ``aclose()``. The production
    code awaits ``close()``, so a stand-in must too — otherwise the test passes or fails on the
    wrong interface."""

    def __init__(self, inner: httpx.AsyncClient) -> None:
        self._inner = inner

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        return await self._inner.post(url, **kwargs)  # type: ignore[arg-type]

    async def close(self) -> None:
        await self._inner.aclose()

    @property
    def is_closed(self) -> bool:
        return self._inner.is_closed


def test_the_hazard_is_real_a_pooling_client_breaks_across_closed_loops(
    keepalive_server: str,
) -> None:
    """The bug itself, with no boundary in the way.

    Kept deliberately: without it, the boundary test below proves nothing the day httpx changes
    its pool behaviour — it would pass for the wrong reason and nobody would know."""
    pooling = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=30.0),
        limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100),
    )
    outcomes: list[str] = []
    for _ in range(8):

        async def _one() -> int:
            return (await pooling.post(keepalive_server, json={})).status_code

        try:
            asyncio.run(_one())
            outcomes.append("ok")
        except Exception as exc:  # broad on purpose — the exception TYPE is the assertion
            outcomes.append(type(exc).__name__)

    assert "RuntimeError" in outcomes, (
        "Expected a closed-loop failure with keep-alive ON and no boundary, got none. Either "
        f"httpx changed its pool behaviour or the server stopped offering keep-alive: {outcomes}"
    )


def test_run_async_does_not_leak_a_client_across_loops(
    monkeypatch: pytest.MonkeyPatch, keepalive_server: str
) -> None:
    """The fix. ``run_async`` closes and clears the cached client inside each task's own loop.

    Driven through the REAL ``run_async`` rather than a hand-rolled ``asyncio.run``, because the
    boundary is the thing under test — a test that reimplemented it would pass regardless of what
    the shipped one does."""
    built: list[_SdkShapedClient] = []

    # An lru_cache-shaped stand-in, so close_anthropic_client() exercises its REAL path —
    # cache_info().currsize, then the cached call, then cache_clear(), then close(). A plain
    # function would have no cache_info and the test would prove something else.
    #
    # It exposes ``close()``, not httpx's ``aclose()``, because that is the Anthropic client's
    # spelling and the production code awaits ``close()``. Using a bare httpx client here would
    # fail on an interface the real one has — which is what the first draft of this test did.
    @lru_cache(maxsize=1)
    def _fake_client() -> _SdkShapedClient:
        made = _SdkShapedClient(
            httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )
        )
        built.append(made)
        return made

    monkeypatch.setattr(client_module, "get_anthropic_client", _fake_client)

    async def _call() -> int:
        return (
            await client_module.get_anthropic_client().post(keepalive_server, json={})
        ).status_code

    for _ in range(8):
        assert run_async(_call()) == 200

    assert len(built) == 8, "expected one client per task, got reuse across loops"
    assert all(c.is_closed for c in built), "a client survived the loop that built it"


async def test_close_anthropic_client_is_a_no_op_when_none_was_built() -> None:
    """The many tasks that make no AI call must not pay for one — and must not CONSTRUCT a client
    merely to close it, which a naive implementation does by calling the cached factory first."""
    client_module.get_anthropic_client.cache_clear()

    await client_module.close_anthropic_client()

    assert client_module.get_anthropic_client.cache_info().currsize == 0


def test_a_failing_close_does_not_replace_the_tasks_own_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup in a ``finally`` must never speak over the thing it is cleaning up after.

    An exception raised by ``close_anthropic_client`` would REPLACE whatever the task was failing
    with, so ``retry_or_terminal`` would classify the close error instead of the real one — a
    transient failure could be read as terminal, or the reverse, and the actual cause would never
    reach the log. It is not a remote risk on this path: the client being closed is the one whose
    transports may have just been failing, so it fires exactly when a task is already going
    wrong."""

    async def _boom() -> None:
        raise ValueError("the task's own failure")

    async def _close_explodes() -> None:
        raise RuntimeError("close failed, and must not be what surfaces")

    monkeypatch.setattr(base_module, "close_anthropic_client", _close_explodes)

    with pytest.raises(ValueError, match="the task's own failure"):
        run_async(_boom())


def test_a_failing_close_is_logged_rather_than_lost() -> None:
    """Swallowed is not the same as hidden — the close failure still has to be findable."""

    async def _close_explodes() -> None:
        raise RuntimeError("close failed")

    original = base_module.close_anthropic_client
    base_module.close_anthropic_client = _close_explodes  # type: ignore[assignment]
    try:
        with structlog.testing.capture_logs() as logs:
            run_async(_ok())
    finally:
        base_module.close_anthropic_client = original  # type: ignore[assignment]

    assert any(entry["event"] == "anthropic_client_close_failed" for entry in logs)


async def _ok() -> str:
    return "fine"
