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

from app.models.finding import EvaluationOutcome, Finding
from app.models.verification import Verification
from app.verification.confidence import AggressionLevel
from app.verification.finding_guidance import resolve_guidance
from app.verification.rules.specs import RuleSpec, load_rule_spec


def _rule_spec(rule_id: str) -> RuleSpec | None:
    """The rule's SPEC — the gate of record for its guideline + category — or None for a retired/legacy
    rule_id with no spec file."""
    try:
        return load_rule_spec(rule_id)
    except (OSError, KeyError, ValueError):
        return None


def _ratification_pending(finding: Finding, spec: RuleSpec | None) -> bool:
    """Whether this finding's verdict rests on an AI JUDGMENT a human must ratify (LP-376-B).

    Prefers the ENGINE's own per-finding signal (``details.ratification_pending``) — authoritative for
    BOTH a judgment verdict AND a fuzzy-consistency AI verdict (the engine set it; the schema does not
    re-derive it). Falls back to the judgment heuristic ONLY for a legacy finding persisted before that
    field existed (it is re-persisted on the next run).

    NOT ``details.gated_pending_signoff`` — that is ``not priya_validated`` (the rule's THRESHOLDS await
    domain sign-off; true for nearly every rule) and has nothing to do with AI ratification."""
    details = finding.details or {}
    persisted = details.get("ratification_pending")
    if isinstance(persisted, bool):
        return persisted
    # Legacy fallback: a JUDGMENT rule that actually reached its verdict (always needs_review; a
    # couldnt_check/gate-fail never invoked the AI, so it does not ratify).
    return (
        spec is not None
        and spec.judgment is not None
        and finding.evaluation_outcome is EvaluationOutcome.NEEDS_REVIEW
    )


def _rule_category(finding: Finding, spec: RuleSpec | None) -> str:
    """The rule's OWN category (Identity / Income / Occupancy / …) from its SPEC — the gate of record
    (``rule_kinds.csv``). NOT the persisted ``FindingCategory`` enum, which lacks Identity/Occupancy and
    coerces them to the wrong legacy value (ID-8 Identity → 'assets'). The two systems' taxonomies are
    separate (LP-375); the governed findings carry their own family, not the sweep's."""
    if spec is not None and spec.category:
        return spec.category
    return finding.category.value  # a legacy/retired rule with no spec → its stored category


def _as_uuid(value: str) -> UUID | None:
    """Parse a stored source-document-id string to UUID, or None (graceful)."""
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


class SourceDocument(BaseModel):
    """One document a finding was derived from (LP-114.1) — id (to open it) + readable filename."""

    id: UUID
    filename: str


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
    #: Why a FAILED run failed. The run marks itself failed with a reason (an un-enqueued pass, a
    #: dead AI call, a governed pass exhausted after retries), and without this field none of that
    #: reached the client: a failed run looked to the processor exactly like a run that never
    #: happened. Null on every non-failed run.
    error_detail: str | None

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
            error_detail=run.error_detail,
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
    # LP-114: WHICH document grounds the finding — the id (for a link) + its readable filename, so
    # the processor can verify the judgment against the actual document. Null when no single source
    # document (a file-level / computed rule, or an AI finding whose type didn't resolve unambiguously).
    source_document_id: UUID | None
    source_document_filename: str | None
    # LP-114.1: ALL documents this finding was derived from (a cross-source finding spans several) —
    # the primary above is one of these. Empty when no source could be attributed (graceful).
    source_documents: list[SourceDocument] = Field(default_factory=list)
    resolution_status: str
    resolution_note: str | None  # the recorded reason for an OVERRIDDEN finding (LP-81)
    applied_record: (
        dict[str, Any] | None
    )  # what an APPLIED finding changed (the effect + Undo, LP-98)
    details: dict[str, Any]

    @classmethod
    def from_model(
        cls, finding: Finding, *, document_names: dict[UUID, str] | None = None
    ) -> FindingPublic:
        # AI-generated why/fix (LP-96) — resolved deterministically (a dict lookup, NO model call)
        # and merged into details so the card's LP-95 slots render it. Grounded-starter; absent →
        # the card degrades gracefully. Guidance stored on a novel finding takes precedence.
        guidance = resolve_guidance(finding.details, category=finding.category.value)
        details = {**finding.details, **guidance} if guidance else finding.details
        # LP-114.1: name ALL the finding's source documents from its stored id set + the file's
        # document names (loaded once by the caller — no N+1). Skips ids whose document is gone.
        names = document_names or {}
        source_documents = [
            SourceDocument(id=doc_id, filename=names[doc_id])
            for raw_id in (finding.source_document_ids or [])
            if (doc_id := _as_uuid(raw_id)) is not None and doc_id in names
        ]
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
            source_document_id=finding.source_document_id,
            # The readable filename (LP-105-style name), from the eager-loaded source_document.
            source_document_filename=(
                finding.source_document.original_filename
                if finding.source_document is not None
                else None
            ),
            source_documents=source_documents,
            resolution_status=finding.resolution_status.value,
            resolution_note=finding.resolution_note,
            applied_record=finding.applied_record,
            details=details,
        )


class RuleFindingPublic(BaseModel):
    """One GOVERNED rule-engine finding (LP-316/375) — a DISTINCT shape from :class:`FindingPublic`.

    The rule engine's findings carry an ``evaluation_outcome`` (the §8 axis) and inline provenance; the
    legacy AI sweep / xsrc findings (``FindingPublic``, ``evaluation_outcome`` null) do not. Keeping them
    two DIFFERENT types is the structural guarantee that the two systems' findings cannot be concatenated
    into one list or their counts summed (LP-375 §3 — an ungoverned 75%-confidence AI observation and a
    governed, gated, provenance-carrying rule finding are not the same kind of thing).

    Carries what LP-376 needs to render §8's tabs + a provenance card: the OUTCOME (the tab discriminator),
    the reason, the SPEC's guideline citation (read-time, NEVER AI-recalled), each load-bearing tag with its
    value/confidence/reasoning, and the ratification-pending marker. ``subject_key`` is the STABLE
    content-id (LP-312) — not yet human-legible (a compact "Deposit of $X on D" label needs per-family
    logic that is not uniformly derivable from the stored data; that is a finding for LP-376, not faked)."""

    id: UUID
    rule_id: str
    evaluation_outcome: (
        str  # open | satisfied | needs_review | couldnt_check | no_longer_applies — the tab
    )
    status: str  # the severity color (red / yellow / green) — orthogonal to the outcome
    category: str
    message: str  # the reason — EVERY non-satisfied outcome carries one (§8's honesty contract)
    subject_key: (
        str | None
    )  # the stable per-subject content-id (LP-312) — the reconciler's KEY (LP-322), NOT for display
    subject_label: (
        str  # the processor-facing subject name (LP-377-B) — a filename / amount / borrower /
    )
    # "Loan-level", resolved read-time per subject TYPE; NEVER a content-id, UUID, or dotted tag id
    guideline: str | None  # the rule's guideline citation, from the SPEC (never AI-recalled)
    # Inline provenance (§3D): each {tag_id, value, confidence, reasoning, source_facts} — a human sees WHY.
    load_bearing_tags: list[dict[str, Any]]
    ratification_pending: (
        bool  # a judgment/AI verdict awaits human ratification (gated_pending_signoff)
    )
    how_to_fix: str | None
    confidence: float
    resolution_status: str

    @classmethod
    def from_model(cls, finding: Finding, *, subject_label: str) -> RuleFindingPublic:
        details = finding.details or {}
        spec = _rule_spec(
            finding.rule_id
        )  # the gate of record for category + ratification (LP-376-B)
        return cls(
            id=finding.id,
            rule_id=finding.rule_id,
            # Guaranteed present by the caller's ``evaluation_outcome IS NOT NULL`` filter; empty only if a
            # future caller passes a legacy finding (which would not belong here).
            evaluation_outcome=(
                finding.evaluation_outcome.value if finding.evaluation_outcome is not None else ""
            ),
            status=finding.status.value,
            category=_rule_category(
                finding, spec
            ),  # the rule's OWN family, not the legacy enum (Bug 3)
            message=finding.message,
            subject_key=finding.subject_key,
            # The processor-facing label is resolved by the READ PATH (the one place with the borrower /
            # document DB maps) and passed in — the schema never guesses it from a maps-free subject_key
            # (which could only claim "no longer in this file"). NEVER the raw subject_key (LP-377-B).
            subject_label=subject_label,
            guideline=spec.guideline_reference if spec is not None else None,
            load_bearing_tags=finding.load_bearing_tags or [],
            # An AI judgment verdict a human must ratify — NOT gated_pending_signoff (= not priya_validated;
            # true for nearly every rule). See _ratification_pending (Bug 1).
            ratification_pending=_ratification_pending(finding, spec),
            how_to_fix=details.get("how_to_fix")
            if isinstance(details.get("how_to_fix"), str)
            else None,
            confidence=finding.confidence,
            resolution_status=finding.resolution_status.value,
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
    # The LEGACY quarantine (Tab 5) — the AI cross-source sweep AND the retired xsrc deterministic findings
    # (both carry a null evaluation_outcome). Unchanged shape + behaviour (LP-375 keeps the sweep identical).
    findings: list[FindingPublic]
    # The GOVERNED rule-engine findings (LP-316), a SEPARATE typed list (LP-375) so tabs 1-4 — including
    # `satisfied` (Tab 2, previously dropped) — are reachable and can never be summed with `findings`.
    rule_findings: list[RuleFindingPublic]
    # LP-377-C Fix 3: the latest run did NOT complete (still RUNNING, or FAILED / killed) yet governed
    # findings exist — so they MAY be from an earlier run (carried forward, LP-322). True when the latest run
    # is not COMPLETED AND governed findings exist. Keyed on RUN status (not "the rule engine failed"): a run
    # can also FAIL because the SWEEP failed while the rule pass succeeded, so the findings can even be fresh
    # — the honest statement is "the run didn't complete; results may be out of date, re-run", not a claim
    # about which half failed. NOT a verification_id filter (that would gut carry-forward — all findings still
    # show); this only flags possible staleness.
    rule_findings_stale: bool
    aggression: AggressionPublic
    blocked: bool
    in_scope_open_count: int
