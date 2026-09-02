"""Persist + reconcile rule-engine evaluations as durable findings (LP-316 + LP-322).

Takes LP-315's in-memory :class:`RuleEvaluation` results (as refined by LP-314a) and writes them as
:class:`Finding` rows on the EXISTING shared model — not a fork. It maps the verdict onto the
evaluation-OUTCOME axis, promotes ``subject_key`` to a stable content-id column (LP-312), carries the
load-bearing tags inline (the §3D provenance move), and drives the per-finding event log.

* **Single-run (LP-316):** :func:`persist_evaluation_findings` INSERTs a finding per evaluated
  subject + a ``created`` event.
* **Cross-run (LP-322):** :func:`reconcile_evaluation_findings` matches THIS run's results against the
  loan file's prior findings by the STABLE identity ``(rule_id, subject_key)`` and reconciles — a
  re-run no longer collides on the uniqueness index; it carries-forward / mints / retires / resolves
  / revives, appending an event for each transition. IMMORTALITY (§9): a no-longer-detected finding
  is RETIRED to ``no_longer_applies`` (visible, labeled, reasoned) — NEVER soft-deleted.

Flush-only; the caller owns the transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.finding_event import FindingEvent, FindingEventType
from app.verification.rule_engine.enumerators import LOAN_SUBJECT
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict

# LP-640 — the identity of the consolidated unidentified-document finding. NOT a rule id: no spec
# file carries it, so the read path must TOLERATE a spec-less id — `schemas.verification._rule_spec`
# returns None for one (it had to be taught to catch `RuleSpecError` to do so; it claimed the
# tolerance and did not have it) and the UI falls back to the id itself. Deliberately not shaped like
# `XX-9` so nobody reads it as a rule that someone forgot to write.
#
# PUBLIC because the caller has to name it: retirement is gated per rule, and this row's eligibility
# is the caller's answer about the DOCUMENT domain's health (see `reconcile_evaluation_findings`).
UNIDENTIFIED_DOCUMENTS_RULE_ID = "UNIDENTIFIED-DOCUMENTS"

_SOURCE_STRENGTH_TAG = "txn.source_strength"
_HAS_SOURCE_TAG = "txn.has_identified_source"
# The sourcing tags whose flip resolves an AS-1 finding (the gift-letter loop) — cited in the
# ``resolved`` event so the history says WHY the rule now passes. A resolve is driven by a TAG flip,
# never by an observation (the LP-320 boundary): an observation only surfaces to a human.
_RESOLVING_TAGS = (_HAS_SOURCE_TAG, _SOURCE_STRENGTH_TAG)

logger = get_logger(__name__)

# Verdict → (evaluation outcome, severity color). NOT_APPLICABLE is absent → not persisted (the
# rule does not apply to that subject). Severity is a COARSE triage color derived from the outcome;
# the evaluation_outcome axis carries the precise signal.
_OUTCOME_BY_VERDICT: dict[Verdict, tuple[EvaluationOutcome, FindingStatus]] = {
    Verdict.FIRED: (EvaluationOutcome.OPEN, FindingStatus.RED),
    Verdict.SATISFIED: (EvaluationOutcome.SATISFIED, FindingStatus.GREEN),
    Verdict.NEEDS_REVIEW: (EvaluationOutcome.NEEDS_REVIEW, FindingStatus.YELLOW),
    Verdict.COULDNT_CHECK: (EvaluationOutcome.COULDNT_CHECK, FindingStatus.YELLOW),
    # LP-391 — a blocked-but-applicable rule's manual-review flag (Tab 1, YELLOW). Its would-be verdict was
    # discarded upstream, so this never carries a satisfied/open — it is not a trusted pass/fail.
    Verdict.PENDING_AUTOMATION: (EvaluationOutcome.PENDING_AUTOMATION, FindingStatus.YELLOW),
}

#: What a retired finding SAYS once it is no longer a concern (bug-004). Deliberately generic: the
#: reconciler knows only that the subject stopped being detected, and inventing a specific reason for
#: that would be a claim nothing checked. Short, and it never reads as an outstanding problem.
_RETIRED_MESSAGE = (
    "This no longer applies to the file — the item it concerned is not among the ones this check "
    "covers any more."
)

# The color a retired finding wears — no_longer_applies is not a live concern (green triage).
_RETIRED_STATUS = FindingStatus.GREEN


def outcome_for_verdict(verdict: Verdict) -> EvaluationOutcome | None:
    """The persisted evaluation-outcome for a verdict, or ``None`` when no finding is persisted
    (``not_applicable``). The SINGLE source of truth for the verdict→outcome mapping — the eval
    harness scores against this, so a change here can never silently diverge from what persists.
    """
    mapping = _OUTCOME_BY_VERDICT.get(verdict)
    return mapping[0] if mapping is not None else None


def _tag_dict(tag: LoadBearingTag) -> dict[str, object]:
    """One load-bearing tag as inline provenance JSON (id + value + confidence + reasoning + facts)."""
    return {
        "tag_id": tag.tag_id,
        "value": tag.value,
        "confidence": tag.confidence,
        "reasoning": tag.reasoning,
        "source_facts": list(tag.source_facts),
    }


def _source_strength(result: RuleEvaluation) -> str | None:
    """The source-strength value (LP-314a) if this evaluation carried one, else None."""
    for tag in result.load_bearing_tags:
        if tag.tag_id == _SOURCE_STRENGTH_TAG and tag.value is not None:
            return str(tag.value)
    return None


def _details(result: RuleEvaluation) -> dict[str, object]:
    """The evaluation metadata + the subject_key the ``finding_identity`` substrate still reads."""
    return {
        "verdict": result.verdict.value,
        "verdict_confidence": result.verdict_confidence,
        "threshold_used": str(result.threshold_used) if result.threshold_used is not None else None,
        "priya_validated": result.priya_validated,
        "gated_pending_signoff": result.gated_pending_signoff,
        # LP-376-B: the engine's authoritative per-finding AI-ratification signal — TRUE for a judgment
        # verdict AND a fuzzy-consistency AI verdict, FALSE for a deterministic/exact-bookend/gate-fail.
        # The public schema reads THIS rather than re-deriving a judgment-only approximation.
        "ratification_pending": result.ratification_pending,
        "how_to_fix": result.how_to_fix,
        # LP-535 — kept out of `message` deliberately, so the composer cannot drop it (see result.py).
        "derivation": result.derivation,
        # LP-626 — the gated AI tag's own reasoning, on its own key for the same reason and rendered
        # differently (it is prose, not a threshold). Never merged into `derivation`.
        "evidence": result.evidence,
        # LP-563 — the structured change Apply performs. Absent when the rule declares none or a
        # value was unresolvable, which is what keeps the button off a finding it cannot act on.
        **({"apply": result.apply} if result.apply else {}),
        # LP-620 — what THIS finding is waiting on, when the spec cannot say it. Absent for every
        # rule whose `requires_documents` already answers correctly, which is nearly all of them.
        **(
            {"requested_documents": list(result.requested_documents)}
            if result.requested_documents
            else {}
        ),
        "source_strength": _source_strength(result),
        # Duplicated into details ONLY so LP-93's finding_identity() (which reads details.subject_key)
        # keeps working alongside the new indexed column. Both are written from the SAME
        # result.subject_id here, so they cannot diverge; this copy is transitional — drop it once
        # finding_identity() reads Finding.subject_key directly. Do NOT set one without the other.
        "subject_key": result.subject_id,
    }


def _resolving_tags(result: RuleEvaluation) -> list[dict[str, object]]:
    """The sourcing tags that explain a resolve (open→satisfied) — PII-safe (tag id + enum value)."""
    return [
        {"tag_id": tag.tag_id, "value": tag.value}
        for tag in result.load_bearing_tags
        if tag.tag_id in _RESOLVING_TAGS
    ]


# The validated (result, outcome, severity, message) tuples ready to persist (not_applicable skipped).
_Persistable = tuple[RuleEvaluation, EvaluationOutcome, FindingStatus, str]


def consolidate_unidentified_documents(results: list[RuleEvaluation]) -> list[RuleEvaluation]:
    """LP-640 — collapse every "we do not know what that document is" abstention into ONE finding.

    A rule that needs a typed field from an unidentified document abstains on it. Every such rule
    abstains on the SAME document, so on LF-ZE9N three unidentified files produced **66 of the 148
    items in the processor's queue** — 22 rules x 3 documents, each row asking the identical question
    and each carrying the identical remedy. To a processor that is one task: identify these files.

    Returns the results with those abstentions replaced by a single loan-level evaluation naming the
    documents and the number of blocked checks. Everything else passes through untouched, in order.

    ⚠️ THE VERDICT IS UNCHANGED — this collapses the QUEUE, never the conclusion. The consolidated
    evaluation is still ``COULDNT_CHECK``, so the file still reads as "these checks did not run". The
    trap on the other side is the one ``pending_checks`` (LP-391) already names: *a BLOCKED rule runs
    NOTHING, so a file that qualifies for it produces SILENCE, which reads as "checked, nothing found"
    when it is really "didn't look"*. Dropping these rows outright would recreate exactly that — IN-8
    would show nothing while the VOE sat unread in an unidentified PDF. One honest blocking row is the
    whole point; zero rows would be a regression, not an improvement.

    STABLE IDENTITY. ``(UNIDENTIFIED_DOCUMENTS_RULE_ID, "loan")`` is one row per loan file under the
    findings uniqueness index, so cross-run reconciliation carries it forward while documents stay
    unidentified and retires it to ``no_longer_applies`` the moment the last one is typed — the same
    lifecycle every other finding gets, with no special-casing in the reconciler.
    """
    blocked = [r for r in results if r.unidentified_document]
    if not blocked:
        return results

    # Distinct documents, order-preserving — the subject of a per-document rule IS its content_id.
    document_ids = tuple(dict.fromkeys(r.subject_id for r in blocked))
    count = len(document_ids)
    noun = "document" if count == 1 else "documents"
    consolidated = RuleEvaluation(
        rule_id=UNIDENTIFIED_DOCUMENTS_RULE_ID,
        subject_id=LOAN_SUBJECT,
        verdict=Verdict.COULDNT_CHECK,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        # Not a threshold rule at all; there is nothing for Priya to have validated, and claiming
        # otherwise would put a false badge on the one finding a processor is most likely to read.
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning=(
            f"{count} {noun} in this file could not be identified, "
            f"so {len(blocked)} checks that need one could not run."
        ),
        how_to_fix=(
            f"Identify {'it' if count == 1 else 'each one'} — set the document type, "
            "or re-upload a clearer copy."
        ),
        # LP-617 — link the actual documents, so the row a processor opens lists the files to fix
        # rather than making them hunt. This is why the consolidated row can be loan-level and still
        # be actionable.
        source_content_ids=document_ids,
    )

    out: list[RuleEvaluation] = [r for r in results if not r.unidentified_document]
    out.append(consolidated)
    return out


def _persistable(results: list[RuleEvaluation]) -> list[_Persistable]:
    """Resolve + validate each result BEFORE any db write, refusing an empty-reasoning verdict.

    A single empty-reasoning verdict (§3D: a verdict must say WHY) refuses the whole batch cleanly
    rather than after partially populating the session. ``not_applicable`` results are dropped (the
    rule does not apply to that subject → no finding).
    """
    persistable: list[_Persistable] = []
    for result in results:
        mapping = _OUTCOME_BY_VERDICT.get(result.verdict)
        if mapping is None:
            continue
        outcome, severity = mapping
        message = (result.reasoning or "").strip()
        if not message:
            raise ValueError(
                f"refusing to persist a finding with empty reasoning "
                f"(rule {result.rule_id}, subject {result.subject_id})"
            )
        persistable.append((result, outcome, severity, message))
    return persistable


def _source_document_ids(
    result: RuleEvaluation, document_id_by_content_id: Mapping[str, UUID]
) -> list[str] | None:
    """The finding's source documents as id strings, or ``None`` when the rule knows of none.

    LP-617. Deliberately RESOLVED rather than stored raw: a content id is a snapshot key, and the map
    only contains documents that are active on the file right now, so a content id that no longer
    resolves (its document was deleted or superseded between runs) is DROPPED rather than written as a
    dangling link. ``None`` for a rule with no document provenance — a loan-level rule over a computed
    tag has no document to point at, and an empty list would read as "we looked and found none".
    """
    ids = [
        str(document_id_by_content_id[content_id])
        for content_id in dict.fromkeys(result.source_content_ids)  # dedupe, order-preserving
        if content_id in document_id_by_content_id
    ]
    return ids or None


def _build_finding(
    *,
    loan_file_id: UUID,
    verification_id: UUID | None,
    result: RuleEvaluation,
    outcome: EvaluationOutcome,
    severity: FindingStatus,
    message: str,
    category: FindingCategory,
    document_id_by_content_id: Mapping[str, UUID],
) -> Finding:
    """A fresh Finding for one evaluated subject (its content-id ``subject_key`` is its identity)."""
    source_ids = _source_document_ids(result, document_id_by_content_id)
    return Finding(
        loan_file_id=loan_file_id,
        verification_id=verification_id,
        rule_id=result.rule_id,
        origin=FindingOrigin.DETERMINISTIC_RULE,  # the rule is deterministic; its tags are ai/derived
        status=severity,
        category=category,
        message=message,
        details=_details(result),
        # None for a deterministic pass AND for a couldnt_check with an absent tag; default 1.0 so a
        # fail-closed outcome is never HIDDEN by a confidence cutoff (open/needs_review/couldnt_check
        # must stay visible). Coarse column; evaluation_outcome carries the precise signal.
        confidence=result.verdict_confidence if result.verdict_confidence is not None else 1.0,
        evaluation_outcome=outcome,
        subject_key=result.subject_id,  # the deposit's stable content_id (LP-312)
        load_bearing_tags=[_tag_dict(tag) for tag in result.load_bearing_tags],
        resolution_status=FindingResolutionStatus.OPEN,
        # LP-617 — WHICH documents this finding is about. `source_document_id` stays the single
        # "primary" the older read paths expect; the set is the honest provenance.
        source_document_ids=source_ids,
        source_document_id=UUID(source_ids[0]) if source_ids else None,
    )


def _update_finding(
    finding: Finding,
    *,
    verification_id: UUID | None,
    result: RuleEvaluation,
    outcome: EvaluationOutcome,
    severity: FindingStatus,
    message: str,
    category: FindingCategory | None,
    document_id_by_content_id: Mapping[str, UUID],
) -> None:
    """Carry a finding forward: refresh its state to THIS run's, keeping its id + resolution history."""
    finding.verification_id = verification_id
    finding.status = severity
    finding.message = message
    finding.details = _details(result)
    finding.confidence = result.verdict_confidence if result.verdict_confidence is not None else 1.0
    finding.evaluation_outcome = outcome
    finding.load_bearing_tags = [_tag_dict(tag) for tag in result.load_bearing_tags]
    # LP-617 — REFRESHED, not set-on-mint-only, for exactly the reason recorded just below: a field
    # written only when minting never reaches a finding that already exists, and on a re-run every
    # finding is carried forward rather than minted. Refreshing also lets a link follow a superseded
    # document to its replacement, and drops one whose document was deleted.
    #
    # LP-620 — REFRESHED TO SOMETHING, NEVER TO NOTHING. Refreshing is right; refreshing to empty on a
    # run that admits it could not look is the false-negative twin of the retire-eligibility guard two
    # arguments away. The documents section degrades, ID-4 still enumerates its borrower subjects (they
    # come from the borrowers section), gathers nothing, returns couldnt_check, is re-detected — and
    # its three stored links were erased with the documents untouched on the file. The same happened
    # when the end-of-run provenance map came back empty, which it now can by design (the lookup is
    # best-effort). Keeping the prior links is the honest degradation: they were true when written, and
    # a document that really did go away is dropped on the next run that CAN resolve one.
    source_ids = _source_document_ids(result, document_id_by_content_id)
    if source_ids:
        finding.source_document_ids = source_ids
        finding.source_document_id = UUID(source_ids[0])
    # LP-598 — THE CATEGORY IS REFRESHED TOO, and it was not. LP-595 fixed the category map, but the
    # map is only read when MINTING, so every finding that already existed kept whatever it was filed
    # under. On LF-3CVT that was all thirty of them: the fix deployed, a run completed, and every
    # finding still read "assets" — a fix that looked applied and was not.
    #
    # Safe to overwrite because a category is DERIVED from the rule id, not chosen by anyone. It is
    # not `resolution_status`, which is a human's decision and is deliberately left alone below.
    if category is not None:
        finding.category = category
    # resolution_status (the HUMAN lifecycle) + subject_key (the identity) are NOT touched here.


async def persist_evaluation_findings(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    verification_id: UUID | None,
    results: list[RuleEvaluation],
    category: FindingCategory = FindingCategory.ASSETS,
    document_id_by_content_id: Mapping[str, UUID] | None = None,  # LP-617
) -> list[Finding]:
    """Persist evaluated subjects as findings + a ``created`` event each (single-run, LP-316).

    One finding per subject whose verdict is persisted (``not_applicable`` is skipped). ``open`` /
    ``satisfied`` / ``needs_review`` / ``couldnt_check`` all persist. Refuses empty reasoning. This
    is the SINGLE-RUN path; a re-run into the same loan file collides on the uniqueness index — use
    :func:`reconcile_evaluation_findings` for cross-run runs (LP-322).
    """
    doc_id_map = document_id_by_content_id or {}
    outcomes: list[tuple[Finding, EvaluationOutcome]] = []
    for result, outcome, severity, message in _persistable(
        consolidate_unidentified_documents(results)
    ):
        finding = _build_finding(
            loan_file_id=loan_file_id,
            verification_id=verification_id,
            result=result,
            outcome=outcome,
            severity=severity,
            message=message,
            # LP-640 — the consolidated row is about DOCUMENTS wherever it is written. This path takes
            # one category for the whole batch, so without this it files under the caller's default
            # (ASSETS) while the reconciler files the identical row under DOCUMENTATION.
            category=(
                FindingCategory.DOCUMENTATION
                if result.rule_id == UNIDENTIFIED_DOCUMENTS_RULE_ID
                else category
            ),
            document_id_by_content_id=doc_id_map,
        )
        db.add(finding)
        outcomes.append((finding, outcome))

    await db.flush()  # assign finding ids before logging their creation
    for finding, outcome in outcomes:
        db.add(
            FindingEvent(
                finding_id=finding.id,
                event_type=FindingEventType.CREATED,
                from_outcome=None,
                to_outcome=outcome,
                detail={},
            )
        )
    await db.flush()
    return [finding for finding, _ in outcomes]


# --------------------------------------------------------------------------- #
# Cross-run reconciliation (LP-322)
# --------------------------------------------------------------------------- #


@dataclass
class ReconcileRunResult:
    """The transitions one cross-run reconcile produced (§8/§9 lifecycle)."""

    minted: list[Finding] = field(default_factory=list)  # new subject → new finding
    carried_forward: list[Finding] = field(default_factory=list)  # re-detected, outcome unchanged
    resolved: list[Finding] = field(default_factory=list)  # open → satisfied (rule now passes)
    outcome_changed: list[Finding] = field(default_factory=list)  # other outcome change
    revived: list[Finding] = field(default_factory=list)  # no_longer_applies → detected again
    retired: list[Finding] = field(default_factory=list)  # not detected → no_longer_applies

    @property
    def detected(self) -> list[Finding]:
        """The findings THIS run detected (everything but the retired)."""
        return [
            *self.minted,
            *self.carried_forward,
            *self.resolved,
            *self.outcome_changed,
            *self.revived,
        ]


async def _load_prior_findings(
    db: AsyncSession, loan_file_id: UUID, rule_ids: frozenset[str]
) -> list[Finding]:
    """The loan file's live, subject-keyed findings for the evaluated rules (incl. retired ones).

    Retired findings are still live (``deleted_at`` NULL — immortality never soft-deletes), so they
    are loaded here: a subject that reappears matches its retired finding and REVIVES the same row.
    """
    result = await db.execute(
        select(Finding).where(
            Finding.loan_file_id == loan_file_id,
            Finding.rule_id.in_(rule_ids),
            Finding.subject_key.isnot(None),
            Finding.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def reconcile_evaluation_findings(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    verification_id: UUID | None,
    run_id: UUID,
    results: list[RuleEvaluation],
    evaluated_rule_ids: frozenset[str],
    category_by_rule: dict[str, FindingCategory],
    default_category: FindingCategory = FindingCategory.ASSETS,
    retire_eligible_rule_ids: frozenset[str] | None = None,
    # LP-617 — content_id -> documents.id, from `document_id_by_content_id`. Defaults to empty so a
    # caller that has no map (a test, a path with no documents) simply produces findings with no
    # links, rather than needing to construct one.
    document_id_by_content_id: Mapping[str, UUID] | None = None,
) -> ReconcileRunResult:
    """Reconcile THIS run's evaluations against the loan file's prior findings (LP-322, §9).

    Matches by the STABLE identity ``(rule_id, subject_key)``. For each subject detected this run:
    CARRY-FORWARD the prior finding (keep id + history; REVIVE if it was retired; RESOLVE if
    open→satisfied; OUTCOME_CHANGED otherwise) or MINT a new one. Each prior finding of a
    RETIRE-ELIGIBLE rule that is NOT detected this run and is still OPEN (no human action) is RETIRED
    to ``no_longer_applies`` — VISIBLE, labeled, reasoned; NEVER soft-deleted (immortality). Every
    transition appends an event carrying the run_id. Flush-only.

    ``retire_eligible_rule_ids`` (default: every evaluated rule) is the subset whose subject domain
    was HEALTHILY enumerated this run. A rule whose enumeration input DEGRADED (e.g. AS-1 when the
    documents section is absent, so it saw zero transactions) must be EXCLUDED: a degraded run is not
    "the subject is gone", and retiring on it would flip real open findings to green (false-closed).
    """
    doc_id_map = document_id_by_content_id or {}
    # LP-640 — consolidate BEFORE validation/matching, so the suppressed per-rule abstentions are
    # simply "not detected this run" and the reconciler retires their prior findings through the
    # ordinary immortality path (visible, labeled `no_longer_applies`) with no special case here.
    persistable = _persistable(
        consolidate_unidentified_documents(results)
    )  # validate all BEFORE any write (empty-reasoning refusal)
    this_by_identity: dict[tuple[str, str], _Persistable] = {
        (result.rule_id, result.subject_id): (result, outcome, severity, message)
        for result, outcome, severity, message in persistable
    }

    # LP-640 — the consolidated finding must live the SAME lifecycle as every other one, and three
    # collaborators here are keyed by rule id, so its synthetic id has to join all three.
    #
    # Each of the three fails differently if skipped, so none is redundant:
    #   * `evaluated_rule_ids` gates `_load_prior_findings` — omitted, the prior row is never loaded,
    #     so every run MINTS a new one and the second collides on `uq_findings_loan_file_rule_subject`.
    #     UNCONDITIONAL: the run that must RETIRE the row is precisely the run that consolidates
    #     nothing (the processor typed the last document), and it has to be LOADED to be retired.
    #   * `retire_eligible` gates the retire loop — but NOT unconditionally, which is the one place
    #     this row must not differ from a per-document rule. "Nothing consolidated" has two causes and
    #     they are opposites: the documents got typed (retire), or the DOCUMENTS SECTION FAILED TO
    #     BUILD, so every per-document rule saw zero subjects and nothing could be attributed
    #     (do not retire). `_retire_eligible_rules` excludes every per_document rule on exactly that
    #     run for exactly that reason; retiring this row there would turn "3 documents could not be
    #     identified" green on a run that never looked at a document — the false-closed the whole
    #     `retire_eligible_rule_ids` mechanism exists to prevent. So the CALLER decides, the same way
    #     it decides for the rules this row stands in for; the no-argument default (every evaluated
    #     rule is eligible) keeps the id in, unchanged.
    #   * `category_by_rule` — omitted, it files under the ASSETS fallback AND trips LP-595's
    #     `finding_category_unresolved` warning, which exists to catch exactly this kind of misfiling.
    evaluated_rule_ids = evaluated_rule_ids | {UNIDENTIFIED_DOCUMENTS_RULE_ID}
    retire_eligible = (
        retire_eligible_rule_ids if retire_eligible_rule_ids is not None else evaluated_rule_ids
    )
    category_by_rule = {
        **category_by_rule,
        UNIDENTIFIED_DOCUMENTS_RULE_ID: FindingCategory.DOCUMENTATION,
    }

    prior = await _load_prior_findings(db, loan_file_id, evaluated_rule_ids)
    prior_by_identity = {(f.rule_id, str(f.subject_key)): f for f in prior}

    res = ReconcileRunResult()
    # (finding, event_type, from_outcome, to_outcome, detail) — minted findings get ids on the flush.
    events: list[
        tuple[
            Finding,
            FindingEventType,
            EvaluationOutcome | None,
            EvaluationOutcome,
            dict[str, object],
        ]
    ] = []
    run_detail: dict[str, object] = {"run_id": str(run_id)}

    # --- detected this run: carry-forward / mint / resolve / revive ---------- #
    for identity, (result, outcome, severity, message) in this_by_identity.items():
        prior_finding = prior_by_identity.get(identity)
        if prior_finding is None:
            # LP-595 — the fallback is now a LOUD last resort. `category_for_rule` covers every
            # active rule and a test pins that, so reaching this line means a rule was filed under
            # someone else's category: the failure that hid sixty-nine misfiled rules in ASSETS.
            category = category_by_rule.get(result.rule_id, default_category)
            if result.rule_id not in category_by_rule:
                logger.warning(
                    "finding_category_unresolved",
                    rule_id=result.rule_id,
                    filed_under=default_category.value,
                )
            finding = _build_finding(
                loan_file_id=loan_file_id,
                verification_id=verification_id,
                result=result,
                outcome=outcome,
                severity=severity,
                message=message,
                category=category,
                document_id_by_content_id=doc_id_map,
            )
            db.add(finding)
            res.minted.append(finding)
            events.append((finding, FindingEventType.CREATED, None, outcome, dict(run_detail)))
            continue

        was = prior_finding.evaluation_outcome
        _update_finding(
            prior_finding,
            verification_id=verification_id,
            category=category_by_rule.get(result.rule_id),
            result=result,
            outcome=outcome,
            severity=severity,
            message=message,
            document_id_by_content_id=doc_id_map,
        )
        if was is EvaluationOutcome.NO_LONGER_APPLIES:
            res.revived.append(prior_finding)
            events.append((prior_finding, FindingEventType.REVIVED, was, outcome, dict(run_detail)))
        elif was == outcome:
            res.carried_forward.append(prior_finding)
            events.append(
                (prior_finding, FindingEventType.CARRIED_FORWARD, was, outcome, dict(run_detail))
            )
        elif was is EvaluationOutcome.OPEN and outcome is EvaluationOutcome.SATISFIED:
            # RESOLVE (the gift-letter loop): the rule now PASSES for this subject — driven by the
            # sourcing tag flip, cited in the event. Distinct from RETIRE (the subject is still here).
            res.resolved.append(prior_finding)
            events.append(
                (
                    prior_finding,
                    FindingEventType.RESOLVED,
                    was,
                    outcome,
                    {**run_detail, "resolving_tags": _resolving_tags(result)},
                )
            )
        else:
            res.outcome_changed.append(prior_finding)
            events.append(
                (prior_finding, FindingEventType.OUTCOME_CHANGED, was, outcome, dict(run_detail))
            )

    # --- not detected this run: RETIRE (never delete) ------------------------ #
    for identity, prior_finding in prior_by_identity.items():
        if identity in this_by_identity:
            continue  # matched above
        if prior_finding.rule_id not in retire_eligible:
            continue  # this rule's domain was NOT healthily enumerated → a degraded run must not
            # retire (that would flip a real open finding to green); leave the prior untouched
        if prior_finding.evaluation_outcome is EvaluationOutcome.NO_LONGER_APPLIES:
            continue  # already retired — stays retired (immortality)
        if prior_finding.resolution_status.is_resolved:
            continue  # a completed human action → RETAIN (Undo/audit depend on it), do not retire
        was = prior_finding.evaluation_outcome or EvaluationOutcome.OPEN
        # bug-004 — THE TEXT MUST LEAVE WITH THE VERDICT. Retiring set the outcome, the status and the
        # run id and left `message` alone, so a green row went on reading as the concern it no longer
        # is. On LF-AWBB twenty CR-1 findings retired correctly and still said "the credit report
        # reports this debt but the application does not state it — an undisclosed liability that
        # changes the debt-to-income picture". A processor scanning the list sees twenty undisclosed
        # liabilities on a file that has none.
        #
        # Same defect LP-625 fixed for `reason`: a sentence that no longer describes the state is
        # residue, and residue that reads as an open problem is worse than none.
        #
        # The old text is not lost — it goes into the event's detail, which is where a finding's
        # history lives and where an Undo or an audit would look for it.
        superseded = prior_finding.message
        prior_finding.message = _RETIRED_MESSAGE
        prior_finding.evaluation_outcome = EvaluationOutcome.NO_LONGER_APPLIES
        prior_finding.status = _RETIRED_STATUS
        prior_finding.verification_id = verification_id
        res.retired.append(prior_finding)
        events.append(
            (
                prior_finding,
                FindingEventType.RETIRED,
                was,
                EvaluationOutcome.NO_LONGER_APPLIES,
                {
                    **run_detail,
                    "reason": "subject no longer detected in this run",
                    "superseded_message": superseded,
                },
            )
        )

    await db.flush()  # assign ids to minted findings before logging their events
    for finding, event_type, from_outcome, to_outcome, detail in events:
        db.add(
            FindingEvent(
                finding_id=finding.id,
                event_type=event_type,
                from_outcome=from_outcome,
                to_outcome=to_outcome,
                detail=detail,
            )
        )
    await db.flush()
    return res


async def repair_retired_finding_text(db: AsyncSession, loan_file_id: UUID) -> int:
    """Rewrite the text of findings retired BEFORE bug-004 shipped. Returns rows touched (bug-005).

    PREVENTING A DEFECT DOES NOT UNDO IT — the lesson LP-625 wrote down, and the one bug-004 walked
    straight back into. Its fix rewrites `message` at the MOMENT of retirement, and the retire loop
    skips anything already retired (`if prior_finding.evaluation_outcome is NO_LONGER_APPLIES:
    continue`), so it only ever reached findings retired after it deployed.

    On LF-AWBB the four CR-1 rows retired after the deploy read correctly and the nineteen retired
    before it still said "the credit report reports this debt but the application does not state it —
    an undisclosed liability that changes the debt-to-income picture": twenty-three rows, one
    behaviour, two texts, and the older ones are the ones a processor has been looking at longest.

    Idempotent; a file with nothing to repair reports zero. The superseded wording goes to the event
    history exactly as the retire path sends it, so nothing is lost here either.
    """
    stale = (
        await db.scalars(
            select(Finding).where(
                Finding.loan_file_id == loan_file_id,
                Finding.deleted_at.is_(None),
                Finding.evaluation_outcome == EvaluationOutcome.NO_LONGER_APPLIES,
                Finding.message != _RETIRED_MESSAGE,
            )
        )
    ).all()
    for finding in stale:
        db.add(
            FindingEvent(
                finding_id=finding.id,
                event_type=FindingEventType.RETIRED,
                from_outcome=EvaluationOutcome.NO_LONGER_APPLIES,
                to_outcome=EvaluationOutcome.NO_LONGER_APPLIES,
                detail={
                    "reason": "retired-text repair (bug-005): the message still described the "
                    "verdict this finding no longer holds",
                    "superseded_message": finding.message,
                },
            )
        )
        finding.message = _RETIRED_MESSAGE
    if stale:
        await db.flush()
        logger.info(
            "retired_finding_text_repaired", loan_file_id=str(loan_file_id), repaired=len(stale)
        )
    return len(stale)


__all__ = [
    "UNIDENTIFIED_DOCUMENTS_RULE_ID",
    "ReconcileRunResult",
    "consolidate_unidentified_documents",
    "outcome_for_verdict",
    "persist_evaluation_findings",
    "reconcile_evaluation_findings",
    "repair_retired_finding_text",
]
