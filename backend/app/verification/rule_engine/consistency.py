"""The GENERIC cross-source CONSISTENCY evaluator (LP-325) — the third rule shape.

AS-1 is per-transaction; OC-2 is loan-level. A large family of rules is instead "gather fact T for
subject S across ALL sources, compare, judge agreement" (ID-1/2/3/4/7; later IN-1/IN-3, CR-1,
PC-3/PR-7). This runs ANY such rule from its ``consistency`` spec block, with ZERO per-rule Python.

The EXACT BOOKEND → AI-FUZZY RESIDUE design (mirrors LP-314 candidate-then-judge — deterministic does
the mechanical part; AI judges only the small ambiguous set):

    enumerate subjects → GATHER tag T across the declared source scope (applying the declared filter)
    → absent≠empty / <2-instances → couldnt_check → the fail-closed gate (LP-315, over the gathered
    instances) → EXACT compare after declared normalization (all equal → AGREE, NO AI) → if they
    DIFFER: ``exact`` mode → a discrepancy (NO AI); ``fuzzy`` mode → the AI judges the SMALL differing
    set ONLY (never the file) benign-variance vs real-discrepancy → the declared outcome.

The absent≠disagreeing rules (§3D, critical): a source that simply LACKS the fact is EXCLUDED (not a
mismatch) — the tag is absent OR an AI perceiver returned ``"unknown"`` (it states no value), which is
absent-for-comparison, NOT a value that agrees/disagrees; fewer than two STATED instances after
filtering → couldnt_check (a single source is not "agreement").

Reuses ``evaluate_gate`` + ``reason_rule_judgment`` (LP-313/314) + the LP-319 armor as-is; a fuzzy
verdict is ratification-pending (the AI made the call) — the exact bookend never is.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.ai.client import AIClientError
from app.ai.extraction.parsing import coerce_date
from app.ai.rule_judgment import Reasoner, RuleJudgmentResult, reason_rule_judgment
from app.core.logging import get_logger
from app.verification.rule_engine.enumerators import enumerate_subjects
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.reasons import document_label, enum_label, fact_label
from app.verification.rule_engine.result import (
    VERDICT_BY_NAME,
    LoadBearingTag,
    RuleEvaluation,
    Verdict,
)
from app.verification.rules.specs import (
    KNOWN_NORMALIZERS,
    ConsistencyEval,
    ConsistencyOutcome,
    RuleSpec,
    TagCondition,
)
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.tag import Tag

logger = get_logger(__name__)

_UNKNOWN = "unknown"

# The AI seam is the shared ``Reasoner`` alias (keyless tests supply a stub; None → the real model
# with the spec prompt). The AI is called ONLY on the differing residue of a fuzzy rule.


# --------------------------------------------------------------------------- #
# Declared normalization — DATA, not code-per-rule (applied before the exact compare)
# --------------------------------------------------------------------------- #
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _date(value: str) -> str:
    """Canonicalize a common date rendering to ISO so a pure FORMAT difference is not a false
    discrepancy (03/04/1985 and 1985-03-04 are the same date). LP-323-ID-B / ID-3.

    Reuses the shared ``coerce_date`` (ISO-first, 2-digit years, date objects) so extraction and
    comparison share ONE format list. US MM/DD order is assumed for numeric slash/dash dates (the US
    mortgage-document norm); a value ``coerce_date`` cannot parse — a non-US DD/DD order, an unusual
    separator, or a month name under a non-English process locale — is returned VERBATIM and compared
    LITERALLY. Literal comparison can SURFACE a false discrepancy for a human to resolve but NEVER
    MASKS a real one (two different date strings never collapse to the same ISO). A locale-robust,
    ambiguity-aware TYPED date comparison is the deferred GAP-A / ID-5."""
    d = coerce_date(value)
    return d.isoformat() if d is not None else value.strip()


# LP-340: a corporate ENTITY SUFFIX (Inc / LLC / Corp / Co / Ltd …) is FORMAT, not content, for the
# purpose of matching an employer across a borrower's documents — a suffix change is a restructuring, not
# an employer change (Geet's decision, ADR-281). This is a DECLARED normalizer a rule opts into on its
# `normalization` chain (currently IN-5 only); the TAG keeps reporting what the document states (LP-335's
# principle — the strip is the RULE's comparison convention, not baked into the tag prompt).
_ENTITY_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "lc",
        "llp",
        "lp",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "pc",
        "plc",
    }
)


def _drop_entity_suffix(value: str) -> str:
    """Strip trailing corporate entity-suffix tokens so ``Acme Logistics Inc`` and ``Acme Logistics LLC``
    (and ``Acme Logistics``) compare equal (LP-340 / ADR-281). Applied AFTER ``drop_punct``/``collapse_ws``,
    so it matches bare lowercase tokens (``inc``, not ``Inc.``) — the spec loader enforces that ordering.

    GREEDY on purpose: it peels EVERY trailing suffix token, so a full legal name ``Acme Logistics Company
    LLC`` and the short form ``Acme Logistics`` both reduce to ``acme logistics`` (W-2 legal name vs paystub
    short form — the common employer-matching case). The cost is that a real name-WORD that happens to be a
    suffix word is also removed when trailing (``Smith Company`` -> ``smith``). Never strips to empty — a
    firm named by a single token (``Company``, ``Inc``) keeps it. ACCEPTED TRADE-OFF (the Priya item): two
    genuinely different legal entities sharing a base name (``Acme Inc`` vs ``Acme LLC``) then match —
    reversible by removing this one key from a rule's chain."""
    tokens = value.split()
    while len(tokens) > 1 and tokens[-1] in _ENTITY_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


_NORMALIZERS: dict[str, Callable[[str], str]] = {
    "strip": str.strip,
    "casefold": str.casefold,
    "collapse_ws": lambda s: _WS.sub(" ", s),
    "drop_punct": lambda s: _PUNCT.sub("", s),
    "date": _date,
    "drop_entity_suffix": _drop_entity_suffix,
}

# Drift guard: the normalizer functions here must exactly cover the key set specs validate against at
# LOAD (a spec's `normalization` chain can only reference these), so a typo'd key fails loud at load
# rather than as an uncaught KeyError mid-run.
assert set(_NORMALIZERS) == KNOWN_NORMALIZERS, "normalizer registry drifted from KNOWN_NORMALIZERS"


def _normalize(value: object, keys: tuple[str, ...]) -> str:
    """Apply the declared normalizer chain (raises KeyError on an unknown normalizer key)."""
    text = value if isinstance(value, str) else str(value)
    for key in keys:
        normalizer = _NORMALIZERS.get(key)
        if normalizer is None:
            raise KeyError(f"unknown normalization key {key!r} (known: {sorted(_NORMALIZERS)})")
        text = normalizer(text)
    return text


# --------------------------------------------------------------------------- #
# Declared source scopes — where a subject's instances of the fact are gathered from
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Gathered:
    """One gathered instance of the fact: its value-tag + the SOURCE it came from (a content_id).

    LP-607 — ``source_label`` is what a PROCESSOR is shown; ``source_id`` stays for identity and
    evidence. ID-4 shipped "the borrower's current residence differs across sources
    (docdbbe8db1f5a7d9ff, doc6abd650d555473b0, docafdf7653352bf74d, ...)" — five content ids in a
    sentence a person reads. LP-377-B exists to keep exactly those away from them, and the composer's
    identifier guard only matches DOTTED ids, so `doc<hex>` walked straight through.
    """

    source_id: str
    tag: Tag
    source_label: str = ""


@dataclass(frozen=True)
class _GatherResult:
    """A gather over one subject: the INCLUDED instances (to compare) + the classification tags that
    DECIDED inclusion (gated for confidence, so a shaky residence/mailing label cannot silently
    include or exclude a source) + the count of value-bearing candidates (matched or not) + the count
    of candidates whose TYPE was AI-``unknown`` (absent-for-comparison, excluded WITHOUT vetoing —
    LP-372 — but surfaced in the finding so the exclusion is visible)."""

    included: list[_Gathered]
    filter_tags: dict[str, Tag]
    candidate_count: int
    type_undetermined: int = 0


# A borrower_id -> its documents index, built ONCE per run (not re-scanned per subject — that was
# O(borrowers x documents)).
_DocIndex = dict[str, list[DocumentEntry]]


def _index_borrower_documents(snapshot: Snapshot) -> _DocIndex:
    """Group every document under each borrower it belongs to — a single O(documents) pass so the
    per-subject gather is O(that borrower's docs), not a full rescan."""
    index: _DocIndex = {}
    if snapshot.documents.absent:
        return index
    for entry in snapshot.documents.entries:
        if entry.belongs_to is None:
            continue
        for ref in entry.belongs_to:
            index.setdefault(str(ref.borrower_id), []).append(entry)
    return index


def _tag_holds(cond: TagCondition, tags: dict[str, Tag]) -> bool:
    """Whether a source's tags satisfy a gather filter — an ABSENT filter tag is a non-match (the
    source is not of the required type, so it is excluded, not counted as disagreeing)."""
    tag = tags.get(cond.tag_id)
    if tag is None:
        return False
    observed = str(tag.value)
    return (observed == cond.value) if cond.op == "eq" else (observed != cond.value)


def _borrower_documents(
    snapshot: Snapshot,
    subject_id: str,
    gather_tag: str,
    gather_filter: TagCondition | None,
    index: _DocIndex,
) -> _GatherResult:
    """Gather ``gather_tag`` from every document belonging to the borrower (filtered).

    A document that lacks the fact is ABSENT → not a candidate (absent≠empty). A value-bearing
    document that fails the filter is excluded (a mailing/prior address is not a residence), but a
    PRESENT, CONCRETE filter tag is still returned so the evaluator can gate the confidence of that
    inclusion/exclusion decision — a shaky classification must not silently drive the compare set."""
    if snapshot.tags.absent:
        return _GatherResult([], {}, 0)
    included: list[_Gathered] = []
    filter_tags: dict[str, Tag] = {}
    candidate_count = 0
    type_undetermined = 0
    for entry in index.get(subject_id, []):
        source_tags = snapshot.tags.by_subject.get(entry.content_id, {})
        tag = source_tags.get(gather_tag)
        # absent≠unknown≠empty: a source that does not STATE the fact is EXCLUDED — the tag was never
        # produced (None), OR an AI perceiver returned "unknown" (it looked and found no value: a bank
        # statement has no address). Neither is a value to compare; counting it would inflate the
        # candidate count and poison the filter gate with a non-stated source's classification.
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        candidate_count += 1
        if gather_filter is not None:
            filter_tag = source_tags.get(gather_filter.tag_id)
            # LP-372: an AI-``unknown`` TYPE is ABSENT-FOR-COMPARISON. The source states an address but
            # no determinable TYPE, so — exactly like an ABSENT filter tag (no branch below adds it), and
            # like the gather-tag ``unknown`` above — it is EXCLUDED from the compare and must NOT poison
            # the confidence gate (an honest "I can't type this" is not evidence the classifier is
            # unreliable on the sources it COULD type; on a purchase file the subject-property address is
            # correctly ``unknown`` on every file, so vetoing on it uniformly couldnt_checks — LP-333).
            # Only a PRESENT, CONCRETE type is gated for confidence. The exclusion is COUNTED so the
            # finding can SURFACE it — a residence hiding behind ``unknown`` is not silently dropped (the
            # false-green the plain-exclude option would risk).
            if filter_tag is not None and str(filter_tag.value) == _UNKNOWN:
                type_undetermined += 1
            elif filter_tag is not None:  # gate its confidence/known-ness (absent → excluded below)
                filter_tags[entry.content_id] = filter_tag
            if not _tag_holds(gather_filter, source_tags):
                continue
        included.append(
            _Gathered(
                entry.content_id,
                tag,
                # The document TYPE, which is what the reader needs — "pay stub, W-2, W-2" tells them
                # which sources disagree; a content id tells them nothing and leaks an internal key.
                document_label(entry.document_type) if entry.document_type else "a document",
            )
        )
    return _GatherResult(included, filter_tags, candidate_count, type_undetermined)


_Scope = Callable[[Snapshot, str, str, "TagCondition | None", "_DocIndex"], _GatherResult]
_SOURCE_SCOPES: dict[str, _Scope] = {
    "borrower_documents": _borrower_documents,
}


# --------------------------------------------------------------------------- #
# The evaluator
# --------------------------------------------------------------------------- #
def _load_bearing(gathered: list[_Gathered], gather_tag: str) -> tuple[LoadBearingTag, ...]:
    """Each gathered value WITH ITS SOURCE, inline — so a human sees WHAT disagreed and WHERE."""
    return tuple(
        LoadBearingTag(
            gather_tag,
            inst.tag.value,
            inst.tag.confidence,
            inst.tag.reasoning,
            (inst.source_id, *inst.tag.source_facts),
        )
        for inst in gathered
    )


def _result(
    spec: RuleSpec,
    subject_id: str,
    verdict: Verdict,
    reasoning: str,
    gathered: list[_Gathered],
    *,
    verdict_confidence: float | None = None,
    how_to_fix: str | None = None,
    ratification_pending: bool = False,
) -> RuleEvaluation:
    assert spec.consistency is not None
    return RuleEvaluation(
        rule_id=spec.rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_load_bearing(gathered, spec.consistency.gather_tag),
        threshold_used=None,  # a consistency rule has no numeric threshold
        priya_validated=spec.reference_values.priya_validated,
        gated_pending_signoff=not spec.reference_values.priya_validated,
        reasoning=reasoning,
        how_to_fix=how_to_fix,
        ratification_pending=ratification_pending,
    )


def _outcome_result(
    spec: RuleSpec,
    subject_id: str,
    outcome: ConsistencyOutcome,
    gathered: list[_Gathered],
    *,
    verdict_confidence: float | None,
    ratification_pending: bool,
    reason_suffix: str = "",
) -> RuleEvaluation:
    """Build the RuleEvaluation for a declared outcome, formatting its reasoning over the gathered set.

    ``reason_suffix`` (LP-372) appends a note about candidates that were excluded because their filter
    TYPE was AI-``unknown`` — so a satisfied/fired verdict SURFACES what it could not compare."""
    labels = [inst.source_label or inst.source_id for inst in gathered]
    # DEDUPED, order-preserving, WHEN THE SOURCES AGREE: five documents of two kinds read
    # "pay stub, W-2" rather than "pay stub, pay stub, W-2, W-2, W-2", and `{count}` carries the number.
    #
    # LP-613 — NOT when they disagree. Deduping by document TYPE erases the multiplicity a disagreement
    # IS: two pay stubs carrying different SSNs rendered "the SSN differs across sources (pay stub)",
    # which reads as one document contradicting itself and names neither of the two to compare. The
    # fired templates carry no `{count}` either, so the number was not recovering it. Keeping every
    # source on a disagreement says "pay stub, pay stub" — odd-looking and true, and no content id
    # reaches the sentence, which is what LP-607 was actually protecting.
    disagrees = VERDICT_BY_NAME[outcome.verdict] is not Verdict.SATISFIED
    fields = {
        "values": ", ".join(str(inst.tag.value) for inst in gathered),
        "sources": ", ".join(labels if disagrees else dict.fromkeys(labels)),
        "count": str(len(gathered)),
    }
    return _result(
        spec,
        subject_id,
        VERDICT_BY_NAME[outcome.verdict],
        outcome.reasoning.format(**fields) + reason_suffix,
        gathered,
        verdict_confidence=verdict_confidence,
        how_to_fix=outcome.how_to_fix,
        ratification_pending=ratification_pending,
    )


async def _judge_residue(
    con: ConsistencyEval, gathered: list[_Gathered], reason_fn: Reasoner
) -> tuple[str, float | None]:
    """Ask the AI about the DIFFERING residue only (values + sources — never the file). Returns a
    (signal, confidence) where signal is 'agree' / 'disagree' / 'cannot_tell'."""
    assert con.judge is not None
    # BOUNDED context: the DISTINCT gathered values (byte-identical duplicates collapsed) each with
    # the sources that reported it — the differing residue only, never the whole file / transactions.
    by_value: dict[str, list[str]] = {}
    for inst in gathered:
        by_value.setdefault(str(inst.tag.value), []).append(inst.source_id)
    context = {
        "values": [{"value": value, "sources": sources} for value, sources in by_value.items()]
    }
    try:
        result = await reason_fn(json.dumps(context))
    except AIClientError:
        logger.warning("consistency_ai_failed", rule=con.gather_tag)
        return "ai_failed", None
    if result.truncated:
        return "truncated", None
    judgment = result.judgment
    if judgment is None or judgment.value not in con.judge.value_domain:
        return (
            "cannot_tell",
            None,
        )  # malformed / off-domain → honest cannot-tell (never a default agree)
    if judgment.value == con.judge.consistent_value:
        return "agree", judgment.confidence
    if judgment.value == con.judge.inconsistent_value:
        return "disagree", judgment.confidence
    return "cannot_tell", judgment.confidence  # an in-domain "unknown"


async def evaluate_consistency_rule(
    spec: RuleSpec,
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    confidence_floor: float | None = None,
) -> list[RuleEvaluation]:
    """Evaluate a cross-source consistency rule over its subjects, entirely from ``spec.consistency``."""
    con = spec.consistency
    assert con is not None, f"{spec.rule_id} is not a consistency rule"
    floor = confidence_floor if confidence_floor is not None else con.confidence_floor
    scope = _SOURCE_SCOPES.get(con.source_scope)
    if scope is None:
        raise KeyError(
            f"unknown source_scope {con.source_scope!r} (known: {sorted(_SOURCE_SCOPES)})"
        )

    doc_index = _index_borrower_documents(snapshot)  # built ONCE, not re-scanned per subject
    results: list[RuleEvaluation] = []
    for subject_id, _subject_tags in enumerate_subjects(con.subject, snapshot):
        result = scope(snapshot, subject_id, con.gather_tag, con.gather_filter, doc_index)
        gathered = result.included

        # LP-372: a note SURFACING candidates dropped because their filter TYPE was AI-``unknown``
        # (absent-for-comparison — excluded, not vetoed). Appended to EVERY verdict this subject can
        # reach so a value hiding behind ``unknown`` is never silently dropped, whatever the outcome.
        # Empty for the common case and for every filterless rule (ID-1/2/3, IN-5) → their reasons are
        # unchanged. Wording stays rule-generic (over any ``gather_filter``, not just ID-4's address).
        n_undetermined = result.type_undetermined
        excluded_note = (
            f" ({n_undetermined} other {'document' if n_undetermined == 1 else 'documents'} could not "
            f"be confirmed as a {enum_label(con.gather_filter.value)} and "
            f"{'was' if n_undetermined == 1 else 'were'} set aside)"
            if n_undetermined and con.gather_filter is not None
            else ""
        )

        # 1. GATE THE INCLUSION DECISION — when ≥2 value-bearing sources could be compared, a shaky
        #    filter classification (a below-floor CONCRETE residence/mailing label — an ``unknown`` type
        #    is now excluded upstream, LP-372) means we cannot trust WHICH sources are in scope → fail
        #    closed rather than silently include or exclude one. Only present, concrete filter tags are
        #    checked (an absent OR unknown one → excluded, absent≠empty).
        #    Skipped when <2 candidates exist (nothing could be compared regardless of classification).
        if result.candidate_count >= 2 and result.filter_tags:
            filter_gate = evaluate_gate(result.filter_tags, confidence_floor=floor)
            if filter_gate.status is not GateStatus.PASS:
                verdict = (
                    Verdict.COULDNT_CHECK
                    if filter_gate.status is GateStatus.COULDNT_CHECK
                    else Verdict.NEEDS_REVIEW
                )
                results.append(
                    _result(
                        spec,
                        subject_id,
                        verdict,
                        f"the {fact_label(con.gather_filter.tag_id)} could not be established reliably, "  # type: ignore[union-attr]
                        f"so we cannot tell which documents to compare — {filter_gate.reason}"
                        + excluded_note,
                        gathered,
                        verdict_confidence=filter_gate.verdict_confidence,
                    )
                )
                continue

        # 2. absent≠empty / a single source is not agreement → couldnt_check (nothing to compare).
        if len(gathered) < 2:
            # LP-376-C: name the mortgage FACT + what a consistency check needs, not the tag id.
            of_type = (
                f" (as a {enum_label(con.gather_filter.value)})"
                if con.gather_filter is not None
                else ""
            )
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    f"only {len(gathered)} document(s) in the file state the "
                    f"{fact_label(con.gather_tag)}{of_type} — a consistency check needs at least two "
                    f"to compare" + excluded_note,
                    gathered,
                )
            )
            continue

        # 4. The generic fail-closed gate over the gathered instances (unknown value → couldnt_check
        #    distinct; a below-floor confidence → needs_review; verdict_confidence = min).
        # ⚠️ ``distrust_tag_ids`` is REQUIRED here: the map is keyed by document content_id (the gathered
        # instances are the SAME tag across many documents, so tag ids would collide), which meant the
        # gate's distrust check compared a document id against tag ids and never matched. Pass the tag
        # actually gathered — ID-3 gathers ``id.dob``, which IS on the distrust list.
        gate = evaluate_gate(
            {inst.source_id: inst.tag for inst in gathered},
            confidence_floor=floor,
            distrust_tag_ids=(con.gather_tag,),
        )
        if gate.status is GateStatus.COULDNT_CHECK:
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    (gate.reason or "") + excluded_note,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
            continue
        if gate.status is GateStatus.NEEDS_REVIEW:
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.NEEDS_REVIEW,
                    (gate.reason or "") + excluded_note,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
            continue

        # 5. THE EXACT BOOKEND — all equal after declared normalization → AGREE. NO AI CALL.
        normalized = {_normalize(inst.tag.value, con.normalization) for inst in gathered}
        if len(normalized) == 1:
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_agree,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                    # Carry the gate's ratification flag rather than hardcoding False: a distrusted
                    # gathered tag must route for human ratification, as it does on the deterministic path.
                    ratification_pending=gate.ratification_pending,
                    reason_suffix=excluded_note,
                )
            )
            continue

        # 6. They DIFFER. exact mode → a discrepancy (NO AI). fuzzy mode → the AI judges the residue.
        if con.compare_mode == "exact":
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_disagree,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                    # Carry the gate's ratification flag rather than hardcoding False: a distrusted
                    # gathered tag must route for human ratification, as it does on the deterministic path.
                    ratification_pending=gate.ratification_pending,
                    reason_suffix=excluded_note,
                )
            )
            continue

        reason_fn = reasoner if reasoner is not None else _bind_prompt(con)
        signal, ai_confidence = await _judge_residue(con, gathered, reason_fn)
        conf = ai_confidence if ai_confidence is not None else gate.verdict_confidence
        if signal == "agree":
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_agree,
                    gathered,
                    verdict_confidence=conf,
                    ratification_pending=True,
                    reason_suffix=excluded_note,
                )
            )
        elif signal == "disagree":
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_disagree,
                    gathered,
                    verdict_confidence=conf,
                    ratification_pending=True,
                    reason_suffix=excluded_note,
                )
            )
        elif signal == "ai_failed":
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    "the consistency judgment could not be produced (AI call failed) — cannot judge"
                    + excluded_note,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
        elif signal == "truncated":
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    "the consistency judgment response was truncated — cannot trust a partial judgment"
                    + excluded_note,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
        else:  # cannot_tell — an honest AI "unknown", NEVER a defaulted agree
            assert con.on_cannot_tell is not None  # required for fuzzy rules (validated at load)
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_cannot_tell,
                    gathered,
                    verdict_confidence=conf,
                    ratification_pending=True,
                    reason_suffix=excluded_note,
                )
            )

    return results


def _bind_prompt(con: ConsistencyEval) -> Reasoner:
    """The default reasoner — the real model with the fuzzy judge's prompt bound."""
    assert con.judge is not None

    async def _call(context_json: str) -> RuleJudgmentResult:
        assert con.judge is not None
        return await reason_rule_judgment(con.judge.system_prompt, context_json)

    return _call


__all__ = ["Reasoner", "evaluate_consistency_rule"]
