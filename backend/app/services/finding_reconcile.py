"""Re-run reconciliation of findings against the current detections (LP-94).

A verification re-run compares the freshly-detected findings against the file's existing ones
and reconciles them — by LP-93's **normalized-substance identity** — into four outcomes:

* **still detected** (a fresh detection matches an existing live finding) → **KEEP** the existing
  row: a true merge that preserves its id, its notes/history, and its resolution. The fresh
  duplicate is discarded. (Before LP-94 the emission superseded + re-created every open finding,
  so a still-detected finding was churned into a NEW row each run and lost any notes added while
  it was open — that history is now preserved.)
* **newly detected** (no existing match) → **ADD** the fresh finding.
* **no longer detected + OPEN** → **DROP** (soft-delete). The underlying issue is gone, so the
  finding is gone — the list stays honest to the current state. This is the Q4 decision that
  REVERSES LP-81's implicit keep-and-recreate: an open finding that no longer reproduces is
  removed, not retained.
* **no longer detected + RESOLVED** (applied / overridden / accepted / …) → **RETAIN**. A resolved
  finding is a *completed processor action*, not clutter: the ``applied_record`` (the data change
  an APPLIED finding made), the audit trail, and LP-98's Undo all depend on that record surviving.
  Dropping it would erase a real decision. So "drop no-longer-detected" targets OPEN findings only.

Within-run duplicate fresh detections collapse (the first wins — LP-93). ``external_identities``
lets one pass dedup against findings it does NOT own (e.g. the AI pass deferring to the
deterministic set) without ever dropping them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.finding import Finding, FindingResolutionStatus, FindingStatus
from app.services.finding_identity import FindingIdentity, finding_identity


@dataclass
class ReconcileOutcome:
    """The result of a reconcile — what was added / kept / dropped / retained, plus counts."""

    added: list[Finding] = field(default_factory=list)  # newly-detected → persisted
    kept: list[Finding] = field(default_factory=list)  # still-detected existing → merged (kept)
    dropped: int = 0  # no-longer-detected OPEN → soft-deleted
    retained_resolved: int = 0  # no-longer-detected RESOLVED → kept (Undo/audit depend on it)
    red: int = 0  # live OPEN red findings after reconcile (this scope)
    yellow: int = 0  # live OPEN yellow findings after reconcile (this scope)


def reconcile_findings(
    db: AsyncSession,
    *,
    existing: Sequence[Finding],
    fresh: Sequence[Finding],
    external_identities: Iterable[FindingIdentity] = (),
) -> ReconcileOutcome:
    """Reconcile ``fresh`` detections against the ``existing`` (owned) findings — LP-94.

    ``existing`` are the live findings this pass OWNS (it may keep or drop them). ``fresh`` are
    freshly-constructed :class:`Finding` objects not yet in the session. ``external_identities``
    are identities of live findings owned by ANOTHER pass — a fresh finding matching one is
    dropped as a duplicate (not added), but those findings are never dropped here.

    Mutates the session (adds new findings, soft-deletes dropped ones); the caller flushes.
    """
    existing_by_identity: dict[FindingIdentity, Finding] = {}
    for finding in existing:
        existing_by_identity.setdefault(finding_identity(finding), finding)
    external = set(external_identities)

    outcome = ReconcileOutcome()
    seen: set[FindingIdentity] = set()
    for finding in fresh:
        identity = finding_identity(finding)
        if identity in seen:
            continue  # within-run duplicate (LP-93) — the first wins
        seen.add(identity)
        match = existing_by_identity.get(identity)
        if match is not None:
            outcome.kept.append(match)  # still detected → keep the existing row (merge)
            continue
        if identity in external:
            continue  # owned by another pass (e.g. the deterministic set) — defer, don't add
        db.add(finding)  # newly detected
        outcome.added.append(finding)

    for finding in existing:
        if finding_identity(finding) in seen:
            continue  # still detected → already kept above
        if finding.resolution_status is FindingResolutionStatus.OPEN:
            finding.deleted_at = utcnow()  # DROP: no-longer-detected open finding
            outcome.dropped += 1
        else:
            outcome.retained_resolved += 1  # RETAIN: a resolved finding is a completed action

    # Counts reflect the live OPEN findings for this scope after reconcile (kept-open + added).
    live_open = [
        f
        for f in (*outcome.kept, *outcome.added)
        if f.resolution_status is FindingResolutionStatus.OPEN
    ]
    outcome.red = sum(1 for f in live_open if f.status is FindingStatus.RED)
    outcome.yellow = sum(1 for f in live_open if f.status is FindingStatus.YELLOW)
    return outcome
