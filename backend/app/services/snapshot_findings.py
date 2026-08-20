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
        # RE-OBSERVED. The disposition is deliberately untouched — that is the processor's, not the
        # model's. The WORDING is refreshed because the same observation may be expressed better,
        # and because refusing to update it would freeze a sentence written against an older file.
        row.snapshot_fingerprint = fingerprint
        row.last_seen_at = now
        row.title = draft.title
        row.detail = draft.detail
        row.sources = draft.sources

    # NO LONGER OBSERVED. Dropped only when still OPEN: a finding a processor acted on is a record of
    # that action, and deleting it would erase their work the first time the file moved. An open one
    # that the model no longer sees is genuinely gone, and keeping it would be the stale-finding
    # problem this pass exists to avoid.
    for row in existing:
        if row.finding_key not in seen and row.disposition == "open":
            await db.delete(row)

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
