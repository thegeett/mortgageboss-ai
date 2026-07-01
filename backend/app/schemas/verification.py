"""Verification schemas (LP-78) — the run + the cross-source status/findings.

The minimal shapes the trigger/staleness UI needs: a verification run summary, the
uniform finding shape (deterministic + AI findings look identical), and the file's
verification status (the staleness flag + the latest run + the findings). The rich
findings UI + resolution flow is LP-81.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.finding import Finding
from app.models.verification import Verification
from app.verification.confidence import AggressionLevel
from app.verification.finding_guidance import resolve_guidance


class OverrideRequest(BaseModel):
    """Dismiss a finding with a **required** recorded reason (LP-81 resolution)."""

    reason: str = Field(min_length=1)


class NoteRequest(BaseModel):
    """Add a free-text note to a finding without changing its resolution (LP-81)."""

    note: str = Field(min_length=1)


class AcceptRiskRequest(BaseModel):
    """Acknowledge a finding as an accepted risk (LP-88) — an optional rationale.

    DISTINCT from override: accept-risk acknowledges a REAL finding the processor proceeds
    with (the FHA compensating-factors / subject-to-repair conditional model). The reason
    (e.g. the documented compensating factor) is optional but recommended.
    """

    reason: str | None = None


class RequestDocsRequest(BaseModel):
    """Request documents from a finding (LP-88) — create a needs item; optional note."""

    note: str | None = None


class AggressionUpdate(BaseModel):
    """Set (or clear) a file's per-file aggression override (LP-79).

    ``level = null`` clears the override so the file reverts to the user's default;
    a level pins this file to that thoroughness. Re-filters the stored findings —
    it never re-runs the AI.
    """

    level: AggressionLevel | None


class VerificationRunPublic(BaseModel):
    """A verification run summary (status + counts + AI cost)."""

    id: UUID
    status: str
    trigger: str
    started_at: datetime | None
    completed_at: datetime | None
    red_count: int
    yellow_count: int
    green_count: int
    total_cost_estimate: float | None

    @classmethod
    def from_model(cls, run: Verification) -> VerificationRunPublic:
        return cls(
            id=run.id,
            status=run.status.value,
            trigger=run.trigger.value,
            started_at=run.started_at,
            completed_at=run.completed_at,
            red_count=run.red_count,
            yellow_count=run.yellow_count,
            green_count=run.green_count,
            total_cost_estimate=run.total_cost_estimate,
        )


class FindingPublic(BaseModel):
    """One finding in the uniform shape (deterministic or AI — same shape, LP-75)."""

    id: UUID
    rule_id: str
    origin: str
    status: str
    category: str
    message: str
    confidence: float
    source_page: int | None
    source_snippet: str | None
    resolution_status: str
    resolution_note: str | None  # the recorded reason for an OVERRIDDEN finding (LP-81)
    details: dict[str, Any]

    @classmethod
    def from_model(cls, finding: Finding) -> FindingPublic:
        # AI-generated why/fix (LP-96) — resolved deterministically (a dict lookup, NO model call)
        # and merged into details so the card's LP-95 slots render it. Grounded-starter; absent →
        # the card degrades gracefully. Guidance stored on a novel finding takes precedence.
        guidance = resolve_guidance(finding.details, category=finding.category.value)
        details = {**finding.details, **guidance} if guidance else finding.details
        return cls(
            id=finding.id,
            rule_id=finding.rule_id,
            origin=finding.origin.value,
            status=finding.status.value,
            category=finding.category.value,
            message=finding.message,
            confidence=finding.confidence,
            source_page=finding.source_page,
            source_snippet=finding.source_snippet,
            resolution_status=finding.resolution_status.value,
            resolution_note=finding.resolution_note,
            details=details,
        )


class AggressionPublic(BaseModel):
    """The aggression dial's state for a file (LP-79) — the confidence-cutoff filter.

    ``level`` is the *active* level (the per-file ``override`` if set, else the
    user's ``default``); ``cutoff`` is the confidence threshold it applies. ``cutoffs``
    maps every level to its cutoff so the client can re-filter the (already-returned)
    findings **instantly** when the dial moves — no AI re-run, no round-trip needed
    to recompute the displayed set.
    """

    level: str
    default: str
    override: str | None
    cutoff: float
    cutoffs: dict[str, float]


class VerificationStatusPublic(BaseModel):
    """The file's verification status — staleness + run + findings + the dial (LP-79).

    ``findings`` is the full stored cross-source set (each carries its confidence);
    the client shows only those at/above the active cutoff (display gating). ``blocked``
    and ``in_scope_open_count`` are the **authoritative** server-side blocking computation
    at the active cutoff (over all findings, deterministic + AI) — "resolve all" means
    "resolve all in-scope at the chosen thoroughness".
    """

    stale: bool
    program: str | None  # the file's loan program (conventional / fha) — drives the rule set
    latest_run: VerificationRunPublic | None
    findings: list[FindingPublic]
    aggression: AggressionPublic
    blocked: bool
    in_scope_open_count: int
