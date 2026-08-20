"""Snapshot-based AI cross-source findings — orchestration (LP-586).

THE STABILITY CONTRACT, which is the whole point of this service:

  * unchanged snapshot  -> the model is NOT asked; the stored findings are returned as they are
  * changed snapshot    -> the model is asked, and the result is RECONCILED against what is stored
  * a processor's disposition survives both, because identity is content (`finding_key`)

The second and third points matter as much as the first. A pass that re-asked and replaced would
give a stable count on an unchanged file and still lose a dismissal the moment anything moved —
which trains a processor to stop dismissing things, and is worse than a drifting number.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.snapshot_cross_source import (
    SnapshotFindingDraft,
    reason_over_snapshot,
    snapshot_payload,
)
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.snapshot_finding import SnapshotFinding
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot_findings.fingerprint import snapshot_fingerprint

logger = get_logger(__name__)

# The dispositions. OPEN and RESOLVED are the SYSTEM's — it sets both from what the model observed.
# SIGNED_OFF and NOT_AN_ISSUE are the PROCESSOR's, and nothing here overwrites them.
OPEN = "open"
RESOLVED = "resolved"

Reasoner = Callable[[str], Awaitable[list[SnapshotFindingDraft]]]


async def _stored(db: AsyncSession, loan_file_id: UUID) -> list[SnapshotFinding]:
    rows = await db.execute(
        select(SnapshotFinding).where(SnapshotFinding.loan_file_id == loan_file_id)
    )
    return list(rows.scalars().all())


async def refresh_snapshot_findings(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    snapshot: Snapshot,
    reasoner: Reasoner | None = None,
) -> list[SnapshotFinding]:
    """Bring this file's snapshot findings up to date. Flush-only; the caller owns the transaction.

    Returns everything stored for the file, whether or not the model ran.
    """
    fingerprint = snapshot_fingerprint(snapshot)
    existing = await _stored(db, loan_file_id)

    # THE CACHE HIT. Every stored finding was observed in THIS snapshot, so there is nothing to
    # re-derive and no reason to pay for a call. `all()` on an empty list is True — a file that
    # genuinely produced no findings stays quiet instead of being re-asked every run.
    if existing and all(f.snapshot_fingerprint == fingerprint for f in existing):
        logger.info(
            "snapshot_findings_cache_hit",
            loan_file_id=str(loan_file_id),
            findings=len(existing),
        )
        return existing

    run = reasoner or reason_over_snapshot
    drafts = await run(snapshot_payload(snapshot))

    by_key = {f.finding_key: f for f in existing}
    now = utcnow()
    seen: set[str] = set()
    for draft in drafts:
        key = draft.finding_key
        seen.add(key)
        row = by_key.get(key)
        if row is None:
            db.add(
                SnapshotFinding(
                    loan_file_id=loan_file_id,
                    finding_key=key,
                    snapshot_fingerprint=fingerprint,
                    kind=draft.kind,
                    title=draft.title,
                    detail=draft.detail,
                    sources=draft.sources,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            continue
        # RE-OBSERVED. A processor's disposition is deliberately untouched — that is theirs, not the
        # model's. The WORDING is refreshed because the same observation may be expressed better,
        # and freezing it would keep a sentence written against an older file.
        #
        # ⚠️ EXCEPT `resolved`, WHICH IS OURS AND NOT THEIRS. We set that when the finding stopped
        # being observed; seeing it again means it did not stay resolved, and leaving the label on a
        # live finding would tell a processor something was fixed while it sits in front of them.
        if row.disposition == RESOLVED:
            row.disposition = OPEN
        row.snapshot_fingerprint = fingerprint
        row.last_seen_at = now
        row.title = draft.title
        row.detail = draft.detail
        row.sources = draft.sources

    # NO LONGER OBSERVED — three different things, and they are not the same.
    for row in existing:
        if row.finding_key in seen:
            continue
        if row.disposition == OPEN:
            # SHOWN AS RESOLVED, ONCE. Deleting outright is honest about the current file but gives a
            # processor NO FEEDBACK that their work landed — they upload the appraisal and the
            # finding simply vanishes, indistinguishable from a bug. Marking it resolved says the
            # file moved and this is why. It carries the CURRENT fingerprint, so it survives exactly
            # as long as the snapshot that resolved it.
            row.disposition = RESOLVED
            row.snapshot_fingerprint = fingerprint
            row.last_seen_at = now
        elif row.disposition == RESOLVED:
            # It was already shown as resolved against an EARLIER snapshot and is still not observed.
            # It has served its purpose; keeping it would silt the tab up with old good news.
            await db.delete(row)
        # signed_off / not_an_issue are RETAINED indefinitely: a processor's action is a record, and
        # deleting it would erase their work the first time the file moved (ADR-061's reasoning).

    await db.flush()
    return await _stored(db, loan_file_id)


async def list_snapshot_findings(db: AsyncSession, *, loan_file_id: UUID) -> list[SnapshotFinding]:
    """Read-only: everything stored for the file, newest observation first."""
    rows = await db.execute(
        select(SnapshotFinding)
        .where(SnapshotFinding.loan_file_id == loan_file_id)
        .order_by(SnapshotFinding.first_seen_at.desc())
    )
    return list(rows.scalars().all())
