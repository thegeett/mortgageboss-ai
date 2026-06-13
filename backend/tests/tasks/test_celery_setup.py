"""Tests for the Celery setup (LP-41) — no running broker/worker.

Covers the app config (incl. JSON-only / no-pickle, UTC), import-without-broker,
task registration, the sync→async bridge, and the ``db_ping`` async DB path
(``SELECT 1``) run directly — proving the bridge + an async session work without
dispatching through Celery. Full broker→worker dispatch is validated **manually**
(see ``app/tasks/health.py`` for the commands); it needs a live Redis/worker.
"""

from app.tasks import health
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.health import _db_ping, db_ping, ping
from celery import Celery
from sqlalchemy import text

# --------------------------------------------------------------------------- #
# App configuration
# --------------------------------------------------------------------------- #


def test_app_is_configured() -> None:
    assert isinstance(celery_app, Celery)
    assert celery_app.conf.broker_url  # broker set (from settings)
    assert celery_app.conf.result_backend  # backend set
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"


def test_no_pickle_serialization() -> None:
    # Security: JSON only — pickle would be an RCE vector if the broker is compromised.
    assert celery_app.conf.accept_content == ["json"]
    assert "pickle" not in celery_app.conf.accept_content


def test_time_limits_set() -> None:
    assert celery_app.conf.task_soft_time_limit == 120
    assert celery_app.conf.task_time_limit == 180
    assert celery_app.conf.task_track_started is True


def test_app_imports_without_a_live_broker() -> None:
    # Creating/importing the app object must not require a Redis connection — this
    # module imported it at the top with no broker running, which is the assertion.
    assert celery_app.main == "mortgageboss"


# --------------------------------------------------------------------------- #
# Task registration
# --------------------------------------------------------------------------- #


def test_health_tasks_registered() -> None:
    assert health is not None  # importing the module registers its tasks
    assert "health.ping" in celery_app.tasks
    assert "health.db_ping" in celery_app.tasks


# --------------------------------------------------------------------------- #
# Sync → async bridge
# --------------------------------------------------------------------------- #


def test_run_async_runs_a_coroutine_to_completion() -> None:
    async def _double(x: int) -> int:
        return x * 2

    assert run_async(_double(21)) == 42


def test_ping_task_returns_pong() -> None:
    # Direct call runs the task body in-process (no broker needed).
    assert ping() == "pong"


async def test_db_ping_async_function_hits_the_db(db_session: object) -> None:
    """The async SELECT 1 path runs against a real DB via a fresh task engine.

    ``_db_ping`` builds its own NullPool engine (the worker pattern), so it uses
    the configured database — proving ``task_session`` works, not just the
    test-fixture session.
    """
    assert await _db_ping() == "db-ok"


async def test_task_session_yields_a_usable_session() -> None:
    async with task_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1


def test_db_ping_task_runs_the_bridge_end_to_end() -> None:
    """The sync task → run_async → task_session → SELECT 1 path (no broker)."""
    assert db_ping() == "db-ok"
