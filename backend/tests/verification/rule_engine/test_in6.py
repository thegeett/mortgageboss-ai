"""IN-6 pay-stub <-> W-2 employer coverage (LP-406-3b). A trivial DETERMINISTIC per-borrower rule that
branches on the derived income.employer_coverage enum (LP-410, which unblocked the LP-406-3 / ADR-323
set-coverage stop). Transitive AI dependency (employer_coverage reads the AI income.employer_normalized,
100% via IN-5) → held pending Priya's sign-off, the IN-3 pattern.

These pin: the branches (covered→satisfied, uncovered→NEEDS_REVIEW, one_sided→NOT_APPLICABLE,
unknown→couldnt_check) — especially uncovered→needs_review (the D2 decision: a short-form employer name is
a known false-positive source, so surface for human confirmation, not fire) and one_sided→not_applicable
at the BORROWER subject (the AS-8 trap in a new place); per-borrower isolation; plain reasons DISTINCT
from IN-5 (the overlap boundary); the subject match; and that IN-6 is written + producing but HELD
(bar validated:false). The coverage tag is computed end-to-end by the real LP-410 producer from injected
income.employer_normalized tags (no AI call), so the rule + producer are exercised together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_SPEC = load_rule_spec("IN-6")


def _emp_tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def _doc(cid: str, dtype: str, bid: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=UUID(bid), name="Sam"),),
    )


def _snap(docs: list[DocumentEntry], employers: dict[str, str], borrowers: list[str]) -> Snapshot:
    tags = {cid: {"income.employer_normalized": _emp_tag(e)} for cid, e in employers.items()}
    mismo: dict[str, Field | PiiField] = {
        f"borrower.{i}.borrower_id": Field.present(bid, source=FieldSource.EXTRACTED)
        for i, bid in enumerate(borrowers, start=1)
    }
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present(tags),
    )


async def _evaluate(
    docs: list[DocumentEntry], employers: dict[str, str], bid: str
) -> list[RuleEvaluation]:
    # Materialize parsed+derived (no AI) — the LP-410 producer computes income.employer_coverage from the
    # injected income.employer_normalized tags, then IN-6 branches on it. Rule + producer exercised together.
    mat = await materialize_tags(_snap(docs, employers, [bid]), only_groups=frozenset())
    return evaluate_deterministic_rule(_SPEC, mat)


# --------------------------------------------------------------------------- #
# The branches — especially uncovered→NEEDS_REVIEW (D2) and one_sided→NOT_APPLICABLE (the trap)
# --------------------------------------------------------------------------- #


async def test_covered_satisfies() -> None:
    # "Acme Corp" (pay stub) and "Acme" (W-2) normalize equal (IN-5's normalizers) → covered → satisfied.
    b = str(uuid4())
    res = await _evaluate(
        [_doc("p", "pay_stub", b), _doc("w", "w2", b)], {"p": "Acme Corp", "w": "Acme"}, b
    )
    assert [r.verdict for r in res] == [Verdict.SATISFIED]


async def test_uncovered_routes_to_needs_review_not_fired() -> None:
    # THE D2 DECISION: a short-form ("Acme") vs a legal name ("Acme Freight Co") normalizes to a mismatch →
    # uncovered — a KNOWN false-positive source. So IN-6 surfaces it for a human to CONFIRM (needs_review),
    # NOT fired (a confident finding would be noisy). needs_review still reaches a human for a genuine gap.
    b = str(uuid4())
    res = await _evaluate(
        [_doc("p", "pay_stub", b), _doc("w", "w2", b)], {"p": "Acme", "w": "Acme Freight Co"}, b
    )
    assert [r.verdict for r in res] == [Verdict.NEEDS_REVIEW]
    assert res[0].verdict is not Verdict.FIRED
    assert res[0].how_to_fix  # tells the processor how to resolve it


async def test_one_sided_w2_only_is_not_applicable() -> None:
    # THE TRAP (at the BORROWER subject): only W-2s, no pay stubs → nothing to cross-check → not_applicable,
    # NOT couldnt_check. Verifies the applicability predicate works per-borrower (not just loan-level, AS-8).
    b = str(uuid4())
    res = await _evaluate(
        [_doc("w1", "w2", b), _doc("w2d", "w2", b)], {"w1": "Acme", "w2d": "Acme"}, b
    )
    assert [r.verdict for r in res] == [Verdict.NOT_APPLICABLE]


async def test_one_sided_paystub_only_is_not_applicable() -> None:
    b = str(uuid4())
    res = await _evaluate([_doc("p", "pay_stub", b)], {"p": "Acme"}, b)
    assert [r.verdict for r in res] == [Verdict.NOT_APPLICABLE]


async def test_unknown_employer_is_couldnt_check() -> None:
    b = str(uuid4())
    res = await _evaluate(
        [_doc("p", "pay_stub", b), _doc("w", "w2", b)], {"p": "unknown", "w": "Acme"}, b
    )
    assert [r.verdict for r in res] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# Per-borrower isolation
# --------------------------------------------------------------------------- #


async def test_per_borrower_isolation() -> None:
    # Borrower A has ONLY a pay stub; borrower B has ONLY a W-2 (same employer). Each is judged on its OWN
    # documents — A's pay stub must NOT cover B's W-2. If coverage pooled, both would be "covered"/satisfied;
    # per-borrower attribution makes each one_sided → not_applicable.
    a, b = str(uuid4()), str(uuid4())
    docs = [_doc("p", "pay_stub", a), _doc("w", "w2", b)]
    mat = await materialize_tags(
        _snap(docs, {"p": "Acme", "w": "Acme"}, [a, b]), only_groups=frozenset()
    )
    by_borrower = {r.subject_id: r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)}
    assert by_borrower[a] is Verdict.NOT_APPLICABLE and by_borrower[b] is Verdict.NOT_APPLICABLE


# --------------------------------------------------------------------------- #
# Reasons: plain language + DISTINCT from IN-5 (the overlap boundary, D5)
# --------------------------------------------------------------------------- #


async def test_reasons_are_plain_and_distinct_from_in5() -> None:
    b = str(uuid4())
    covered = await _evaluate(
        [_doc("p", "pay_stub", b), _doc("w", "w2", b)], {"p": "Acme", "w": "Acme"}, b
    )
    uncovered = await _evaluate(
        [_doc("p", "pay_stub", b), _doc("w", "w2", b)], {"p": "Acme", "w": "Beta"}, b
    )
    for res in (covered, uncovered):
        for r in res:
            assert "income.employer_coverage" not in r.reasoning  # no dotted tag id (LP-376-C)
            # IN-6 is COVERAGE across document types, not IN-5's name-CONSISTENCY — its reason must not read
            # like IN-5's "the employer differs across sources".
            assert "differs across sources" not in r.reasoning
    assert "both" in uncovered[0].reasoning.lower() or "missing" in uncovered[0].reasoning.lower()


# --------------------------------------------------------------------------- #
# The subject match (anti-structural-death) + held pending Priya
# --------------------------------------------------------------------------- #


def test_coverage_tag_is_produced_at_the_subject_in6_reads() -> None:
    assert _SPEC.subject_enumeration == "per_borrower"
    assert load_declarations()["income.employer_coverage"].subject == "borrower"


def test_in6_is_live_after_priya_signoff() -> None:
    # LP-412: Priya signed off the 0.95 bar ("same as IN-5"). Transitive AI dependency
    # (employer_coverage reads AI employer_normalized, measured 100%) → calibratable-now, validated, 1.0 >= 0.95
    # → eligible → ACTIVE.
    bar = load_activation_bars()["IN-6"]
    assert bar.status == "calibratable-now"
    assert bar.load_bearing_ai_tags == ("income.employer_normalized",)
    assert bar.threshold == 0.95 and bar.measured_accuracy == 1.0
    assert bar.validated is True and is_eligible(bar) is True
    assert "IN-6" in ACTIVE_RULE_IDS


async def test_in6_couldnt_checks_on_lf6t3n_no_ai_run() -> None:
    # employer_coverage depends on the AI employer_normalized; a no-AI run does not produce it → unknown →
    # couldnt_check. HONEST (an AI-not-produced gap, like OC-1's fixture), not a bug or structural death.
    mat = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    verdicts = {r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)}
    assert verdicts <= {
        Verdict.COULDNT_CHECK
    }  # every borrower couldnt_check (none satisfied/fired offline)
