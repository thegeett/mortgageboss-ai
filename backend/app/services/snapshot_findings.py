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
    _normalise,
    reason_over_snapshot,
    snapshot_paths,
    snapshot_payload,
    text_rejection,
)
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.snapshot_finding import SnapshotFinding, SnapshotFindingScan
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot_findings.fingerprint import snapshot_fingerprint

logger = get_logger(__name__)

# The dispositions. OPEN and RESOLVED are the SYSTEM's — it sets both from what the model observed.
# SIGNED_OFF and NOT_AN_ISSUE are the PROCESSOR's, and nothing here overwrites them.
OPEN = "open"
RESOLVED = "resolved"

# LP-604 — takes the payload AND the acceptable addresses. A test stub that ignores the second
# argument still type-checks, which is deliberate: a stub returns fixed drafts and has nothing to
# validate them against.
Reasoner = Callable[[str, frozenset[str]], Awaitable[list[SnapshotFindingDraft]]]


async def _stored(db: AsyncSession, loan_file_id: UUID) -> list[SnapshotFinding]:
    rows = await db.execute(
        select(SnapshotFinding).where(SnapshotFinding.loan_file_id == loan_file_id)
    )
    return list(rows.scalars().all())


def _cited_values(sources: list[dict[str, str]] | None) -> list[str]:
    """The figures a finding cites, normalised and ordered BY PATH (LP-604).

    Ordered by path rather than by position because the model lists its sources in whatever order it
    likes — the probe showed the same finding citing the same two facts in opposite orders on
    consecutive runs. Comparing positionally would read that as a value change and rewrite the text
    for no reason, which is the churn this is meant to end.
    """
    return [
        _normalise(str(s.get("value", "")))
        for s in sorted(sources or [], key=lambda x: str(x.get("path", "")))
    ]


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

    # THE CACHE HIT, decided by a per-file SCAN MARKER rather than by the findings themselves.
    #
    # The first version asked `existing and all(row.fingerprint == current)`, which was wrong twice
    # over. A file that genuinely produced NO findings has no row to carry a fingerprint, so
    # `existing` was falsy and it re-asked every run forever — the very case its comment claimed to
    # handle. And a finding a processor signed off, which the model later stopped seeing, kept its
    # OLD fingerprint, so `all(...)` never held again and that file re-asked forever after. Since the
    # model's answer differs between calls, the tab then moved on a file that had not changed: the
    # exact failure this pass exists to prevent.
    scan = await db.get(SnapshotFindingScan, loan_file_id)
    if scan is not None and scan.snapshot_fingerprint == fingerprint:
        logger.info(
            "snapshot_findings_cache_hit",
            loan_file_id=str(loan_file_id),
            findings=len(existing),
        )
        return existing

    run = reasoner or reason_over_snapshot
    # LP-604 — the acceptable addresses, derived from the SAME payload the model is handed, so a
    # finding citing a place that is not in the file is dropped rather than stored as evidence.
    drafts = await run(snapshot_payload(snapshot), snapshot_paths(snapshot))

    # DE-DUPLICATE BEFORE INSERTING. `finding_key` deliberately ignores the wording, so two drafts
    # describing the same pairing in different words collide — ordinary model output. Both would miss
    # `by_key`, both would be added, and the flush would raise IntegrityError on the unique
    # constraint. That does not degrade gracefully: it poisons the session, so the caller's own
    # commit then raises PendingRollbackError and the rule findings, the persisted snapshot and the
    # COMPLETED status all roll back with it.
    deduped: dict[str, SnapshotFindingDraft] = {}
    for draft in drafts:
        deduped.setdefault(draft.finding_key, draft)
    drafts = list(deduped.values())

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
                    # LP-598 — the NORMALISED kind, so the stored value matches the one identity
                    # hashes. Storing the raw slug would show a processor a category the dedupe does
                    # not use, and re-open the drift this ticket closed.
                    kind=draft.normalised_kind,
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
        # EXCEPT `resolved`, WHICH IS OURS AND NOT THEIRS. We set that when the finding stopped
        # being observed; seeing it again means it did not stay resolved, and leaving the label on a
        # live finding would tell a processor something was fixed while it sits in front of them.
        if row.disposition == RESOLVED:
            row.disposition = OPEN
        row.snapshot_fingerprint = fingerprint
        row.last_seen_at = now

        # LP-604 — THE ORIGINAL WORDING STAYS. Identity is now the snapshot addresses a finding is
        # about, so the same finding is recognised across runs — but the model rewords itself anyway,
        # and rewriting the text on every match made a settled finding LOOK like it had changed. In
        # three probe runs over one unchanged file, the same finding came back with two different
        # titles. Keeping the text means a wording change now MEANS something, and the sentence a
        # processor dismissed is the sentence that stays dismissed.
        #
        # Two exceptions, and both are the difference between stable and stale:
        #
        # 1. A CITED VALUE MOVED. Identity is (kind, paths) and deliberately excludes the figures, so
        #    a finding stays itself when a balance changes — but its text quotes those figures. Frozen
        #    wording would state $451,829 as fact after the file says $398,000.
        # 2. THE STORED TEXT NO LONGER PASSES. LP-601 was this bug one layer over: the composer's
        #    guards ran only on a cache miss, so prose written before a guard existed outlived it.
        #    Re-checking here is what stops retention from recreating that.
        values_moved = _cited_values(row.sources) != _cited_values(draft.sources)
        stale_text = text_rejection(row.title, row.detail, draft.sources) is not None
        if values_moved or stale_text:
            logger.info(
                "snapshot_finding_text_refreshed",
                finding_key=row.finding_key,
                reason="values_moved" if values_moved else "text_rejected",
            )
            row.title = draft.title
            row.detail = draft.detail
        row.sources = draft.sources

    # NO LONGER OBSERVED — three different things, and they are not the same.
    for row in existing:
        if row.finding_key in seen:
            continue
        # A retained disposition keeps its LAST-OBSERVED fingerprint on purpose — that column is
        # provenance ("when did we last actually see this"), and the cache no longer reads it.
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

    # Record WHAT WAS ASKED, so an answer of "nothing" is cacheable like any other.
    if scan is None:
        db.add(SnapshotFindingScan(loan_file_id=loan_file_id, snapshot_fingerprint=fingerprint))
    else:
        scan.snapshot_fingerprint = fingerprint
        scan.scanned_at = now

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
