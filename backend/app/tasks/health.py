"""Health/validation tasks (LP-41).

Tiny tasks that prove the whole chain works — app → broker → worker → task — and,
for :func:`db_ping`, that the **sync→async bridge** and an async DB session work
inside the worker (it runs a real ``SELECT 1`` through :func:`task_session`).
These are validation tasks, not part of the document pipeline (LP-42).

Validate manually with a running worker::

    celery -A app.tasks.celery_app worker --loglevel=info
    # then, in a Python shell:
    from app.tasks.health import ping, db_ping
    ping.delay().get(timeout=10)     # -> "pong"
    db_ping.delay().get(timeout=10)  # -> "db-ok"
"""

from sqlalchemy import text

from app.tasks.base import BaseTask, run_async, task_session
from app.tasks.celery_app import celery_app


@celery_app.task(base=BaseTask, name="health.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    """Trivial liveness task — returns ``"pong"`` (no I/O)."""
    return "pong"


async def _db_ping() -> str:
    """Open an async session and run ``SELECT 1`` — proves the async bridge + DB.

    Factored out (not inlined in the task) so it can be unit-tested directly
    against the test database without dispatching through Celery.
    """
    async with task_session() as db:
        result = await db.execute(text("SELECT 1"))
        value = result.scalar_one()
    return "db-ok" if value == 1 else "db-unexpected"


@celery_app.task(base=BaseTask, name="health.db_ping")  # type: ignore[untyped-decorator]
def db_ping() -> str:
    """Run the async ``SELECT 1`` from a sync task via the bridge."""
    return run_async(_db_ping())
