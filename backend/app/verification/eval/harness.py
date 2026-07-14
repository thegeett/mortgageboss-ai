"""The two-level scoring engine (LP-317 Phase 1) - runs the real pipeline, scores vs labels.

For each golden case it builds a snapshot (or loads a frozen real one), runs Stage A → Stage B →
AS-1 with either the KEYLESS stub reasoners (deterministic CI scoring) or the LIVE model
(calibration), and scores actual vs LABELED-expected at two levels:

* TAG level - ``is_money_in`` / ``apparent_category`` / ``has_identified_source`` / ``source_strength``.
* FINDING level - the AS-1 evaluation outcome per subject.

Plus the §3D Move-1 provenance check: a FIRED / NEEDS_REVIEW verdict must carry its load-bearing
tags inline with non-empty reasoning. The harness EVALUATES - a mismatch is a reported regression,
never a reason to edit rule/tag logic.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.services.rule_findings import outcome_for_verdict
from app.verification.eval.cases import EvalCase, FixtureTxn
from app.verification.eval.stubs import StubStageAReasoner, StubStageBReasoner
from app.verification.rule_engine.engine import evaluate_as1_rule
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import (
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)

_FIXTURES = (
    Path(__file__).resolve().parent.parent.parent.parent / "tests/verification/eval/fixtures"
)
_DOC = "docstmt0000000000"
_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

_TAG_IS_MONEY_IN = "txn.is_money_in"
_TAG_CATEGORY = "txn.apparent_category"
_TAG_HAS_SOURCE = "txn.has_identified_source"
_TAG_STRENGTH = "txn.source_strength"

# The harness scores the FINDING level against production's ACTUAL verdict→outcome mapping
# (rule_findings.outcome_for_verdict), never a local copy — so a persistence-mapping change can
# never diverge unnoticed from what the eval validates. NOT_APPLICABLE → None (no finding).


@dataclass(frozen=True)
class TagObservation:
    """One scored tag value - an (expected, actual) pair for a dimension (feeds calibration)."""

    dimension: str  # is_money_in | apparent_category | has_identified_source | source_strength
    expected: str
    actual: str | None


@dataclass(frozen=True)
class Mismatch:
    """A single scored difference - the subject, what was expected, and what was produced."""

    subject: str  # the transaction description (crafted) or content_id (real)
    dimension: str  # a tag dimension, "outcome", or "provenance"
    expected: str
    actual: str | None


@dataclass
class CaseResult:
    """The scored outcome of one golden case."""

    case_id: str
    title: str
    level: str
    passed: bool
    tag_mismatches: list[Mismatch] = field(default_factory=list)
    finding_mismatches: list[Mismatch] = field(default_factory=list)
    provenance_failures: list[Mismatch] = field(default_factory=list)
    observations: list[TagObservation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def all_mismatches(self) -> list[Mismatch]:
        return [*self.tag_mismatches, *self.finding_mismatches, *self.provenance_failures]


def _build_snapshot(case: EvalCase) -> Snapshot:
    """A one-document bank-statement snapshot from the case's labeled transactions + DTI income.

    Enforces the two fixture invariants the description→label keying relies on (documented in
    cases.py): descriptions are UNIQUE within a case, and they survive snapshot redaction unchanged
    (no 9+-digit runs). A violation raises here with a clear message rather than a later cryptic
    KeyError / silent mis-score.
    """
    keys = [t.key for t in case.txns]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise ValueError(
            f"case {case.case_id}: duplicate fixture description(s) {dupes} — the eval keys labels "
            f"on description, so they must be UNIQUE within a case"
        )
    raw = [
        {
            "date": t.date,
            "amount": t.amount,
            "description": t.key,
            "transaction_type": t.transaction_type,
        }
        for t in case.txns
    ]
    field_sets = transaction_field_sets({"transactions": raw}, "bank_statement")
    txns = build_transactions(field_sets, document_content_id=_DOC)
    assert txns is not None
    for fx, built in zip(case.txns, txns, strict=True):
        if str(built.description.value) != fx.key:
            raise ValueError(
                f"case {case.case_id}: fixture description {fx.key!r} was rewritten by snapshot "
                f"redaction to {built.description.value!r} — the eval keys labels on description, "
                f"so avoid 9+-digit runs (LP-302a redaction)"
            )
    entry = DocumentEntry(content_id=_DOC, document_type="bank_statement", transactions=txns)
    calculations = (
        CalculationsSection.present(
            dti=CalculationEntry(value={"gross_monthly_income": case.income}, breakdown=[])
        )
        if case.income is not None
        else CalculationsSection.missing()
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present([entry]),
        calculations=calculations,
        tags=TagsSection.present({}),
    )


def _tag_value(snapshot: Snapshot, content_id: str, tag_id: str) -> str | None:
    tag = snapshot.tags.by_subject.get(content_id, {}).get(tag_id)
    return None if tag is None else str(tag.value)


def _subjects_by_description(snapshot: Snapshot) -> dict[str, str]:
    """content_id → description, to map results/tags back to the labeled fixture rows."""
    out: dict[str, str] = {}
    for doc in snapshot.documents.entries:
        for txn in doc.transactions or ():
            out[txn.content_id] = str(txn.description.value)
    return out


async def run_case(case: EvalCase, *, live: bool = False) -> CaseResult:
    """Run + score one golden case (keyless by default; ``live=True`` uses the real model)."""
    if case.fixture_snapshot is not None:
        return _score_real_case(case)

    snapshot = _build_snapshot(case)
    reasoner_a = None if live else StubStageAReasoner(case.txns)
    reasoner_b = None if live else StubStageBReasoner(case.txns)
    from app.services.tag_correlation import produce_stage_b_sourcing_tags
    from app.services.tag_production import produce_stage_a_transaction_tags

    snapshot = await produce_stage_a_transaction_tags(snapshot, reasoner=reasoner_a)
    snapshot = await produce_stage_b_sourcing_tags(snapshot, reasoner=reasoner_b)
    results = evaluate_as1_rule(snapshot)
    return _score_case(case, snapshot, results)


def _score_case(case: EvalCase, snapshot: Snapshot, results: list[RuleEvaluation]) -> CaseResult:
    """Score a crafted case at both levels + the provenance check."""
    result = CaseResult(case_id=case.case_id, title=case.title, level=case.level, passed=True)
    cid_to_desc = _subjects_by_description(snapshot)
    by_key = {t.key: t for t in case.txns}

    # --- TAG level ---------------------------------------------------------- #
    for content_id, desc in cid_to_desc.items():
        fx = by_key[desc]
        _score_tags(result, snapshot, content_id, fx)

    # --- FINDING level + provenance ----------------------------------------- #
    for evaluation in results:
        desc = cid_to_desc.get(evaluation.subject_id, evaluation.subject_id)
        matched = by_key.get(desc)
        expected = matched.expect_outcome if matched is not None else None
        actual_outcome = outcome_for_verdict(evaluation.verdict)
        actual = None if actual_outcome is None else actual_outcome.value
        if expected != actual:
            result.finding_mismatches.append(Mismatch(desc, "outcome", str(expected), actual))
        _score_provenance(result, evaluation, desc)

    result.passed = not result.all_mismatches
    return result


def _score_tags(result: CaseResult, snapshot: Snapshot, content_id: str, fx: FixtureTxn) -> None:
    """Score the four tag dimensions for one subject; record observations for calibration."""
    checks: list[tuple[str, str, str | None]] = [
        (_TAG_IS_MONEY_IN, fx.is_money_in, _tag_value(snapshot, content_id, _TAG_IS_MONEY_IN)),
        (_TAG_CATEGORY, fx.apparent_category, _tag_value(snapshot, content_id, _TAG_CATEGORY)),
    ]
    if fx.has_source is not None:
        checks.append(
            (_TAG_HAS_SOURCE, fx.has_source, _tag_value(snapshot, content_id, _TAG_HAS_SOURCE))
        )
    if fx.expect_strength is not None:
        checks.append(
            (_TAG_STRENGTH, fx.expect_strength, _tag_value(snapshot, content_id, _TAG_STRENGTH))
        )
    for dimension, expected, actual in checks:
        result.observations.append(TagObservation(dimension, expected, actual))
        if expected != actual:
            result.tag_mismatches.append(Mismatch(fx.key, dimension, expected, actual))


def _score_provenance(result: CaseResult, evaluation: RuleEvaluation, subject: str) -> None:
    """§3D Move 1: a FIRED / NEEDS_REVIEW verdict must carry inline provenance with a WHY."""
    if evaluation.verdict not in (Verdict.FIRED, Verdict.NEEDS_REVIEW):
        return
    if not evaluation.load_bearing_tags:
        result.provenance_failures.append(
            Mismatch(subject, "provenance", "load-bearing tags present", "none")
        )
        return
    if not any((tag.reasoning or "").strip() for tag in evaluation.load_bearing_tags):
        result.provenance_failures.append(
            Mismatch(subject, "provenance", "a tag with non-empty reasoning", "all empty")
        )


def _score_real_case(case: EvalCase) -> CaseResult:
    """Score the frozen real (LF-6T3N) snapshot: 0 fired + the sourcing strength distinction."""
    result = CaseResult(case_id=case.case_id, title=case.title, level=case.level, passed=True)
    snapshot = load_fixture_snapshot(case.fixture_snapshot or "")
    results = evaluate_as1_rule(snapshot)

    verdicts = Counter(r.verdict for r in results)
    fired = verdicts[Verdict.FIRED]
    expect_fired = case.expect_real.get("fired", 0)
    if fired != expect_fired:
        result.finding_mismatches.append(
            Mismatch("LF-6T3N", "fired_count", str(expect_fired), str(fired))
        )

    strengths = Counter(
        _tag_value(snapshot, cid, _TAG_STRENGTH)
        for cid in snapshot.tags.by_subject
        if _TAG_STRENGTH in snapshot.tags.by_subject[cid]
    )
    for key, dimension in (("min_verified", "verified"), ("min_self_asserted", "self_asserted")):
        floor = case.expect_real.get(key, 0)
        if strengths[dimension] < floor:
            result.finding_mismatches.append(
                Mismatch("LF-6T3N", f"count[{dimension}]", f">={floor}", str(strengths[dimension]))
            )

    result.notes.append(
        f"verdicts={{{', '.join(f'{v.value}:{n}' for v, n in sorted(verdicts.items(), key=lambda kv: kv[0].value))}}}"
    )
    result.notes.append(
        f"strengths={{{', '.join(f'{k}:{n}' for k, n in sorted(strengths.items(), key=lambda kv: str(kv[0])))}}}"
    )
    result.passed = not result.all_mismatches
    return result


def load_fixture_snapshot(name: str) -> Snapshot:
    """Load a frozen tagged snapshot fixture by file name (deterministic; no AI, no key)."""
    return Snapshot.model_validate(json.loads((_FIXTURES / name).read_text()))


async def run_suite(cases: tuple[EvalCase, ...], *, live: bool = False) -> list[CaseResult]:
    """Run + score every case (sequentially - live mode makes real model calls)."""
    return [await run_case(case, live=live) for case in cases]


def format_report(results: list[CaseResult]) -> str:
    """A human-legible pass/fail summary + every mismatch - the GO/NO-GO artifact."""
    lines = ["=" * 78, "GOLDEN EVAL - tag-level + finding-level (LP-317)", "=" * 78]
    passed = sum(1 for r in results if r.passed)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"[{mark}] case {r.case_id:>2} ({r.level:<7}) - {r.title}")
        for note in r.notes:
            lines.append(f"        · {note}")
        for m in r.all_mismatches:
            lines.append(
                f"        ✗ {m.dimension} @ {m.subject}: expected {m.expected!r}, got {m.actual!r}"
            )
    lines.append("-" * 78)
    lines.append(f"{passed}/{len(results)} cases passed")
    return "\n".join(lines)
