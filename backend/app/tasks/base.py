"""Task base: running async code from sync Celery tasks (LP-41).

Celery tasks are traditionally **sync**, but this codebase is **async** (async
SQLAlchemy, the async AI wrapper, async storage). LP-42's tasks must call that
async code, so this module bridges the two:

  * :func:`run_async` runs a coroutine to completion from a sync task. The V1
    approach is **a fresh event loop per task** (``asyncio.run``) — the simplest
    correct option. Caveat: a new loop (and new DB connections) per task;
    acceptable at V1 volume, revisit loop/pool reuse if throughput grows.
  * :func:`task_session` yields an async SQLAlchemy session backed by a **fresh
    engine created inside the current event loop**, with ``NullPool``. This is
    deliberate: the app's module-level ``engine`` (``app.core.database``) is
    bound to the loop that first used it, so reusing it across the per-task loops
    would raise "attached to a different loop" (asyncpg connections are
    loop-bound). A per-task engine with no pooling sidesteps that entirely; it is
    disposed when the task's coroutine finishes.
  * :class:`BaseTask` binds structured-logging context (task name + id) around
    each run — metadata only, never the task payload.
"""

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import structlog
from celery import Task
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = structlog.get_logger(__name__)


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from a sync Celery task (fresh loop per call)."""
    return asyncio.run(coro)


@asynccontextmanager
async def task_session() -> AsyncIterator[AsyncSession]:
    """An async DB session safe to use inside a worker task.

    Builds a **fresh** async engine in the current (per-task) event loop with
    ``NullPool`` — so no connection is shared across loops — and disposes it when
    done. Use within a coroutine driven by :func:`run_async`::

        async def _work() -> None:
            async with task_session() as db:
                ...
        run_async(_work())
    """
    engine = create_async_engine(str(settings.database_url), poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


class BaseTask(Task):  # type: ignore[misc] # celery ships incomplete type info
    """Base for the project's Celery tasks: logging context + the async bridge.

    Binds ``task_name`` / ``task_id`` into the structlog contextvars for the
    duration of the call (so task logs are attributable) and unbinds afterward.
    Exposes :meth:`run_async` so task bodies can call async code. LP-42's tasks
    use ``@celery_app.task(base=BaseTask, ...)``.
    """

    abstract = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        task_id = getattr(self.request, "id", None)
        structlog.contextvars.bind_contextvars(task_name=self.name, task_id=task_id)
        logger.info("task_started")
        try:
            return super().__call__(*args, **kwargs)
        finally:
            logger.info("task_finished")
            structlog.contextvars.unbind_contextvars("task_name", "task_id")

    @staticmethod
    def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine to completion (see module-level :func:`run_async`)."""
        return run_async(coro)
