"""Reporting which phase a running verification is in (LP-590).

A run takes about six and a half minutes and shows a spinner for all of it, which is
indistinguishable from a hung worker — a distinction that has mattered twice.

THE WHOLE DIFFICULTY IS THE TRANSACTION. `run_rule_engine_pass` opens one session and commits once
at the end, so anything the run itself writes is invisible to a poller until the run is over. Each
update therefore opens its OWN short-lived session, writes, and commits immediately.

That makes progress a genuinely best-effort side channel: it must never fail the run it is
describing, and it must never hold a lock the run needs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.verification_progress import VerificationProgress
from app.tasks.base import task_session

logger = get_logger(__name__)

# The session factory, injectable for one specific reason. `task_session()` builds its own engine
# from `settings.database_url` — the DEV database. A test that exercised these functions would
# therefore write progress rows into dev rather than the test database, and because every error here
# is swallowed, it would do so silently. Injecting the factory is what makes this path testable
# against the test database instead of untested and quietly wrong.
SessionFactory = Callable[
    [], AbstractAsyncContextManager[AsyncSession] | AsyncIterator[AsyncSession]
]

# The phases a processor sees, in order. Machine names match `Degradation.stage` so a degradation and
# a progress entry refer to the same thing by the same name.
PHASES: tuple[str, ...] = ("build", "stage_a", "stage_b", "rules", "cross_source")

# Written once at the end rather than left on the last phase: "Cross-source review" frozen on screen
# after a run finished reads as stuck.
DONE = "done"


async def report_phase(
    verification_id: UUID, phase: str, *, session_factory: SessionFactory | None = None
) -> None:
    """Record the phase this run has reached. Never raises.

    Best-effort by construction. A progress write that failed the run it was describing would be a
    grotesque trade, so every error is swallowed with a log — the caller is mid-verification and has
    nothing useful to do about it.
    """
    try:
        index = PHASES.index(phase) + 1 if phase in PHASES else len(PHASES)
        factory = session_factory or task_session
        async with factory() as db:  # type: ignore[union-attr]
            # UPSERT: one row per run, replaced in place. A plain insert would collide on the second
            # phase, and a select-then-update would race two workers on a retried task.
            await db.execute(
                insert(VerificationProgress)
                .values(
                    verification_id=verification_id,
                    phase=phase,
                    phase_index=index,
                    phase_total=len(PHASES),
                    updated_at=utcnow(),
                )
                .on_conflict_do_update(
                    index_elements=["verification_id"],
                    set_={
                        "phase": phase,
                        "phase_index": index,
                        "phase_total": len(PHASES),
                        "updated_at": utcnow(),
                    },
                )
            )
            await db.commit()
    except Exception as exc:
        logger.warning(
            "verification_progress_failed",
            verification_id=str(verification_id),
            phase=phase,
            error=type(exc).__name__,
        )


async def clear_progress(
    verification_id: UUID, *, session_factory: SessionFactory | None = None
) -> None:
    """Drop the row once the run is over, so a finished run shows no phase. Never raises."""
    try:
        factory = session_factory or task_session
        async with factory() as db:  # type: ignore[union-attr]
            await db.execute(
                delete(VerificationProgress).where(
                    VerificationProgress.verification_id == verification_id
                )
            )
            await db.commit()
    except Exception as exc:
        logger.warning(
            "verification_progress_clear_failed",
            verification_id=str(verification_id),
            error=type(exc).__name__,
        )
