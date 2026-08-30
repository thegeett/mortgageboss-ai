"""LP-636 defect 1 — a cached HTTP client must not pool a connection across event loops.

``get_anthropic_client`` is ``lru_cache``d, so one client serves the whole process, while
``run_async`` (``app/tasks/base.py``) is ``asyncio.run``: a FRESH event loop per Celery task,
closed when the task ends. A pooled keep-alive connection outlives the loop it was opened on, and
the next task that takes it from the pool fails instantly with ``RuntimeError: Event loop is
closed`` — which the SDK surfaces as ``APIConnectionError``, at 1-5ms, without reaching the
network. On staging that cost 5 of 44 documents in a single upload.

WHY THIS TEST EXISTS IN THIS SHAPE. The claim it replaces was measured as "one client issuing
successful requests across three separate ``asyncio.run()`` loops returned 200 each time" — and
that passes even with the bug present, because the SDK pool sets ``keepalive_expiry=5.0`` and three
sequential calls each clear five seconds. So this test drives calls BACK TO BACK inside that
window, which is the burst condition that actually breaks, and asserts on a real socket rather than
a mock: the failure is in the transport, so a mocked transport cannot show it.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading
from collections.abc import Iterator

import httpx
import pytest
from app.ai.client import _build_http_client


class _Handler(http.server.BaseHTTPRequestHandler):
    """Minimal keep-alive JSON endpoint. HTTP/1.1 so the connection is offered for reuse —
    without that the pool has nothing to hold and the bug cannot appear."""

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
    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/x"
    finally:
        server.shutdown()
        server.server_close()


def _call_across_closed_loops(client: httpx.AsyncClient, url: str, times: int) -> list[str]:
    """Drive ``times`` requests, each in its own ``asyncio.run`` loop, reusing one client.

    Returns one entry per call: ``"ok"`` or the exception type name. Back to back deliberately —
    staying inside ``keepalive_expiry`` is what makes a pooled connection still be there.
    """
    results: list[str] = []
    for _ in range(times):

        async def _one() -> int:
            response = await client.post(url, json={})
            return response.status_code

        try:
            asyncio.run(_one())
            results.append("ok")
        except Exception as exc:  # broad on purpose — the exception TYPE is the assertion
            results.append(type(exc).__name__)
    return results


def test_a_pooling_client_breaks_across_closed_loops(keepalive_server: str) -> None:
    """The bug itself, pinned. If this ever passes, the reproduction has stopped reproducing
    and the guarantee below is no longer evidence of anything."""
    pooling = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=30.0),
        limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100),
    )
    results = _call_across_closed_loops(pooling, keepalive_server, times=8)

    assert "RuntimeError" in results, (
        "Expected a closed-loop failure with keep-alive ON, got none. Either httpx changed its "
        f"pool behaviour or the server stopped offering keep-alive. Results: {results}"
    )


def test_the_shipped_client_survives_closed_loops(keepalive_server: str) -> None:
    """The fix. ``_build_http_client`` disables keep-alive, so no connection outlives its loop.

    This is the assertion that matters: it fails if anyone raises ``max_keepalive_connections``
    above zero, which is the only way defect 1 comes back."""
    results = _call_across_closed_loops(_build_http_client(), keepalive_server, times=8)

    assert results == ["ok"] * 8, f"the shipped client failed across event loops: {results}"


def test_the_shipped_client_keeps_the_sdk_timeouts() -> None:
    """Injecting an ``http_client`` REPLACES the SDK's defaults with httpx's, and httpx's read
    timeout is 5 seconds FLAT.

    These calls stream for minutes, so a bare ``httpx.AsyncClient()`` would break almost every
    extraction while looking like a tidy refactor — and it would look like a model problem, not a
    transport one. Pinned against the SDK's own ``DEFAULT_TIMEOUT``."""
    timeout = _build_http_client().timeout

    assert timeout.read == 600.0, "a 5s read timeout would kill every streaming call"
    assert timeout.write == 600.0
    assert timeout.pool == 600.0
    assert timeout.connect == 5.0
