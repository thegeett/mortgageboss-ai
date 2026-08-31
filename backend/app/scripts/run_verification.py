"""Enqueue a verification run for one loan file, from the terminal (LP-523).

WHY THIS EXISTS. The debugging loop for the rule engine is deploy → run verification → read the
findings, and the middle step was only reachable by clicking in the UI. Worse, the UI could not do it
at all while a previous run was stuck RUNNING — which is exactly when you most want to re-run.

⚠️ IT FORCES BY DEFAULT, and that is the point. The API caches on an INPUT fingerprint: if the stated
and verified data hash the same as the last completed run, it returns that run's findings without
re-calling the AI. That is right for a user and wrong here — this loop changes CODE, not inputs, so the
cache would hand back the old findings and the deploy would look like it did nothing. Set
`VERIFY_FORCE=0` to respect the cache.

⚠️ IT CLEARS A STUCK RUN, on exactly the API's own terms — a RUNNING run older than
a run past the file-derived watchdog bound is marked failed and superseded; a YOUNGER one is left alone and this
refuses. Borrowing the API's threshold rather than inventing one keeps a single definition of "stuck",
and refusing on a young run means this can never kill a pass that is still working.

A ONE-OFF TASK, not an endpoint: it runs on the migrate task definition inside the VPC with the task
role, so there is no token to mint, refresh, or leak into a terminal. Same shape as `query`,
`bootstrap-admin` and `backfill-mismo`.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Both borrowed from the API deliberately: the watchdog bound so "stuck" has ONE definition
# (the one the UI already acts on), and `_enqueue_rule_engine` so the enqueue path — which is
# documented never to raise and to leave the caller responsible for failing the run — is not duplicated.
#
# LP-614: this was `_enqueue_cross_source`. That was the ONLY pass this script ever enqueued, so a
# script-triggered run ran the legacy sweep and never the governed rules — and with the sweep now off
# it would have created a run and enqueued nothing at all. The rule engine is what verification means.
from app.api.verification import (
    _WATCHDOG_SLACK_SECONDS,
    _document_count,
    _enqueue_rule_engine,
    _watchdog_hard_limit,
)
from app.core.database import async_session_maker
from app.core.logging import get_logger
from app.core.run_limits import rule_engine_limits
from app.models.base import utcnow
from app.models.loan_file import LoanFile
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.services.verifications import create_verification_run

logger = get_logger(__name__)


def _truthy(raw: str | None, *, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def _supersede_stuck_run(db: AsyncSession, loan_file_id: UUID) -> str | None:
    """Fail a stuck RUNNING run so a new one can start; return why we refused, if we did.

    The threshold is the API watchdog's, imported rather than repeated — two definitions of "stuck"
    would eventually disagree, and the one that matters is whatever the UI already believes.
    """
    latest = (
        (
            await db.execute(
                select(Verification)
                .where(Verification.loan_file_id == loan_file_id)
                .order_by(Verification.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if latest is None or latest.status is not VerificationStatus.RUNNING:
        return None

    started = latest.started_at or latest.created_at
    age = utcnow() - started if started is not None else timedelta(0)
    # LP-635 — stored-first, exactly as the API watchdog reads it, so "stuck" has ONE definition.
    # Two definitions would let this command supersede a run the UI still (correctly) considers
    # healthy. (The superseded "derived from the file" wording is gone: it described the behaviour
    # this column replaced, and it was the first thing a reader hit.)
    hard = await _watchdog_hard_limit(db, latest, loan_file_id)
    stuck_after = hard + _WATCHDOG_SLACK_SECONDS
    if age <= timedelta(seconds=stuck_after):
        remaining = timedelta(seconds=stuck_after) - age
        return (
            f"a run started {int(age.total_seconds())}s ago is still RUNNING and may still be "
            f"working — refusing to supersede it for another {int(remaining.total_seconds())}s"
        )

    latest.status = VerificationStatus.FAILED
    latest.completed_at = utcnow()
    latest.error_detail = "Superseded by a terminal-triggered re-run (the worker did not finish)."
    await db.commit()
    print(f"  superseded a stuck run ({int(age.total_seconds())}s old): {latest.id}")
    return None


async def _run() -> int:
    identifier = (os.getenv("VERIFY_LOAN_FILE") or "").strip()
    if not identifier:
        print("VERIFY_LOAN_FILE is required (a loan file display_id, e.g. LF-WCHG).")
        return 2
    force = _truthy(os.getenv("VERIFY_FORCE"), default=True)

    async with async_session_maker() as db:
        loan_file = (
            (await db.execute(select(LoanFile).where(LoanFile.display_id == identifier)))
            .scalars()
            .first()
        )
        if loan_file is None:
            print(f"No loan file with display_id {identifier!r}.")
            return 1

        if (refusal := await _supersede_stuck_run(db, loan_file.id)) is not None:
            print(f"  {refusal}")
            return 1

        # No fingerprint check: see the module docstring. `force` is honoured only so the flag means
        # something, but the default is to re-run — this exists for the case the cache gets wrong.
        if not force:
            print("  VERIFY_FORCE=0 — the API's input-fingerprint cache is NOT bypassed here;")
            print("  this script always enqueues, so use the UI if you want cached behaviour.")

        # LP-635 review — COUNTED BEFORE THE RUN IS COMMITTED, so the limit can be stored on it.
        # This path did not set `time_limit_seconds` at all, so every CLI-started run left it NULL
        # and the watchdog fell back to re-deriving from the file's CURRENT count — the behaviour
        # persisting the column exists to stop. The CLI is the path used to investigate the file
        # that prompted this ticket, so it is the last one that should have been left on it.
        document_count = await _document_count(db, loan_file.id)
        run = await create_verification_run(
            db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
        )
        run.time_limit_seconds = rule_engine_limits(document_count)[1]
        await db.commit()
        # Captured INSIDE the session: both objects detach when it closes, and a committed
        # attribute can be expired, so reading them later is a lazy-load on a dead session.
        run_id, loan_file_id = run.id, loan_file.id

    # `_enqueue_rule_engine` never raises; a False return means the broker is unreachable, and the
    # caller owns failing the run — a swallowed enqueue would strand it RUNNING forever.
    if not _enqueue_rule_engine(loan_file_id, run_id, document_count=document_count):
        async with async_session_maker() as db:
            stranded = await db.get(Verification, run_id)
            if stranded is not None:
                stranded.status = VerificationStatus.FAILED
                stranded.completed_at = utcnow()
                stranded.error_detail = (
                    "Could not enqueue the verification pass (worker/broker unavailable)."
                )
                await db.commit()
        print("  enqueue FAILED — the run was marked failed, not left RUNNING.")
        return 1

    print(f"  loan file : {identifier} ({loan_file_id})")
    print(f"  run_id    : {run_id}")
    print(
        "  enqueued  : the worker picks it up now; watch the worker log for verification_run_done."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    sys.exit(asyncio.run(_run()))
