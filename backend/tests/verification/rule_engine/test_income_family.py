"""LP-323-IN-B — the INCOME family runs from DATA through the GENERIC evaluators (no engine Python).

Minimal per-rule fire / doesn't-fire / couldnt_check through the SAME generic evaluators the ID family
uses (evaluate_deterministic_rule / evaluate_consistency_rule / evaluate_judgment_rule) — proving the
specs + tag declarations + derived recipes are the whole of the authoring (the wave's success criterion).
The FULL 13-point matrix is LP-323-IN-C's job; this is the authoring smoke test.

Covers the two DATA behaviours the doc rests on: (1) the derived-tag ABSTENTION (a feeding tag
absent/unknown → the derived tag is "unknown" with a reason → the rule couldnt_checks — IN-A's case-12
path, finally in play); (2) IN-1's DIRECTION edge (documented ABOVE stated is a raise → satisfied, not
fired); (3) IN-5's exact-match COST property (no AI call).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import ProductionMode, TagDeclaration
from app.verification.tag_materialization.derived import (
    _income_days_since_recent_pay,
    _income_max_employment_gap,
    _income_ytd_annualized_shortfall,
    produce_derived_tags,
)

pytestmark = pytest.mark.anyio

_B1 = uuid4()


def _tag(value: object, *, conf: float | None = 0.9, by: TagProducedBy = TagProducedBy.AI) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _parsed(value: object) -> Tag:
    return _tag(value, conf=None, by=TagProducedBy.PARSED)


def _doc(cid: str, *, dtype: str = "paystub", borrower=_B1) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=borrower, name="Sam"),) if borrower else None,
    )


def _snap(*, docs=None, by_subject=None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        tags=TagsSection.present(by_subject or {}),
    )


class _Reasoner:
    def __init__(self, value: str = "yes") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


# --------------------------------------------------------------------------- #
# The derived recipes — arithmetic + the abstention contract (never a fabricated number)
# --------------------------------------------------------------------------- #


def test_recipe_gap_and_recency_abstain_below_two_or_absent() -> None:
    assert _income_max_employment_gap(_snap(), "loan", None)[0] == "unknown"  # no records
    assert _income_days_since_recent_pay(_snap(), "loan", None)[0] == "unknown"  # no pay date
    paid = _snap(docs=[_doc("d")], by_subject={"d": {"income.pay_date": _parsed("2026-06-01")}})
    val, _ = _income_days_since_recent_pay(paid, "loan", None)
    assert val == "44"  # 2026-07-15 - 2026-06-01


def test_recipe_ytd_uses_most_recent_pay_month_across_a_year_boundary() -> None:
    # LP-323-IN-B review #1: elapsed months = the MOST-RECENT pay date's month (Jan → 1), NOT the max
    # month number (a Dec paystub's 12). A Dec + Jan pair (a January-collected file) must annualize
    # ytd/1, not ytd/12 — else the monthly is understated 12x and a false shortfall fires.
    snap = _snap(
        docs=[_doc("dec"), _doc("jan")],
        by_subject={
            "dec": {"income.pay_date": _parsed("2025-12-31")},  # older; no ytd on this stub
            "jan": {
                "income.ytd_gross": _parsed("6000"),
                "income.documented_monthly": _parsed("6000"),
                "income.pay_date": _parsed("2026-01-20"),  # most recent → month 1
            },
        },
    )
    value, reason = _income_ytd_annualized_shortfall(snap, "loan", None)
    assert (
        value == "0" and "1 month" in reason
    )  # ytd 6000 / 1 month = 6000/mo = documented → no shortfall


def test_recipe_employment_gap_pairs_consecutive_not_spanning_records() -> None:
    # LP-323-IN-B review #2: three back-to-back jobs (A end, B fills the middle, C start). The gap is
    # the largest CONSECUTIVE gap (31 days), NOT job-A-end → job-C-start spanning job B (~1127 days).
    snap = _snap(
        docs=[_doc("a"), _doc("b"), _doc("c")],
        by_subject={
            "a": {"income.employment_end": _parsed("2020-01-01")},
            "b": {
                "income.employment_start": _parsed("2020-02-01"),
                "income.employment_end": _parsed("2023-01-01"),
            },
            "c": {"income.employment_start": _parsed("2023-02-01")},
        },
    )
    value, _ = _income_max_employment_gap(snap, "loan", None)
    assert value == "31"  # the consecutive gap, not the B-spanning 1127-day cartesian pair


def test_recipe_days_since_pay_abstains_on_a_future_pay_date() -> None:
    # LP-323-IN-B review #5: a pay date AFTER the file date → negative age → abstain (a staleness rule
    # must NOT read a future-dated paystub as "ultra-fresh"; couldnt_check surfaces it).
    snap = _snap(
        docs=[_doc("d")], by_subject={"d": {"income.pay_date": _parsed("2026-08-01")}}
    )  # file date is 2026-07-15
    value, reason = _income_days_since_recent_pay(snap, "loan", None)
    assert value == "unknown" and "AFTER the file date" in reason


def test_derived_producer_still_materializes_a_loan_recipe() -> None:
    # LP-332 canary: produce_derived_tags generalized to declared subjects, but a LOAN recipe still
    # materializes under "loan" unchanged (loan- and borrower-level recipes coexist).
    decl = TagDeclaration(
        tag_id="income.days_since_most_recent_pay",
        mode=ProductionMode.DERIVED,
        subject="loan",
        data="income_days_since_recent_pay",
        allowed_values=None,
    )
    snap = _snap(docs=[_doc("d")], by_subject={"d": {"income.pay_date": _parsed("2026-06-01")}})
    out = produce_derived_tags(decl, snap)
    assert out["loan"]["income.days_since_most_recent_pay"].value == "44"


# --------------------------------------------------------------------------- #
# IN-1 — deterministic through the generic evaluator (fire / raise-edge / couldnt_check)
# --------------------------------------------------------------------------- #
def _in1(shortfall: str | None):
    # LP-332: IN-1 is now PER-BORROWER — the shortfall tag keys under a borrower_id, and the per_borrower
    # enumerator finds the borrower via a document's belongs_to.
    tags = (
        {
            str(_B1): {
                "income.documented_income_shortfall_pct": _tag(shortfall, by=TagProducedBy.DERIVED)
            }
        }
        if shortfall
        else {}
    )
    return evaluate_deterministic_rule(
        load_rule_spec("IN-1"), _snap(docs=[_doc("d", borrower=_B1)], by_subject=tags)
    )


def test_in1_fires_on_shortfall_satisfied_on_raise_couldnt_check_on_absent() -> None:
    assert _in1("0.20")[0].verdict is Verdict.FIRED  # 20% shortfall > 5%
    assert _in1("-0.10")[0].verdict is Verdict.SATISFIED  # a raise — the DIRECTION edge
    assert _in1("0.04")[0].verdict is Verdict.SATISFIED  # within 5%
    (cc,) = _in1(None)
    assert (
        cc.verdict is Verdict.COULDNT_CHECK
    )  # the derived tag absent → couldnt_check (case 12 path)


def test_in2_and_in4_deterministic_bounds() -> None:
    def in2(days):
        t = (
            {"loan": {"income.days_since_most_recent_pay": _tag(days, by=TagProducedBy.DERIVED)}}
            if days
            else {}
        )
        return evaluate_deterministic_rule(load_rule_spec("IN-2"), _snap(by_subject=t))

    assert in2("45")[0].verdict is Verdict.FIRED  # beyond 30-day window
    assert in2("20")[0].verdict is Verdict.SATISFIED
    assert in2(None)[0].verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# IN-5 — consistency (fuzzy) through the generic evaluator + the exact-match COST property
# --------------------------------------------------------------------------- #
async def _in5(employers: dict[str, str], reasoner):
    docs = [_doc(cid) for cid in employers]
    by_subject = {
        cid: {"income.employer_normalized": _tag(name)} for cid, name in employers.items()
    }
    return await evaluate_consistency_rule(
        load_rule_spec("IN-5"), _snap(docs=docs, by_subject=by_subject), reasoner=reasoner
    )


async def test_in5_exact_match_satisfies_with_no_ai_call() -> None:
    stub = _Reasoner("disagree")  # would fire if consulted — proves it is NOT
    r = await _in5({"pay": "Acme Corp", "w2": "Acme Corp"}, stub)
    assert [x.verdict for x in r] == [Verdict.SATISFIED] and stub.calls == 0  # COST property


async def test_in5_different_employer_fires_and_single_source_couldnt_check() -> None:
    fire = await _in5({"pay": "Acme Corp", "w2": "Globex Inc"}, _Reasoner("disagree"))
    assert [x.verdict for x in fire] == [Verdict.FIRED]
    lone = await _in5({"pay": "Acme Corp"}, _Reasoner())
    assert [x.verdict for x in lone] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# IN-8 — per_document deterministic with applicability (scope + expected-absence)
# --------------------------------------------------------------------------- #
def test_in8_voe_scope_and_expected_absence() -> None:
    # A VOE doc marked not-present → fired; a non-VOE doc → not_applicable; NO VOE doc → couldnt_check.
    docs = [_doc("voe", dtype="verification_of_employment"), _doc("pay", dtype="paystub")]
    by_subject = {"voe": {"income.voe_present": _tag("no")}}
    by = {
        r.subject_id: r.verdict
        for r in evaluate_deterministic_rule(
            load_rule_spec("IN-8"), _snap(docs=docs, by_subject=by_subject)
        )
    }
    assert by["voe"] is Verdict.FIRED and by["pay"] is Verdict.NOT_APPLICABLE
    # A file with NO VOE document — a VOE is expected (LP-330) → couldnt_check, never not_applicable.
    only_pay = evaluate_deterministic_rule(
        load_rule_spec("IN-8"), _snap(docs=[_doc("pay", dtype="paystub")])
    )
    assert any(v.verdict is Verdict.COULDNT_CHECK for v in only_pay)


def test_in10_declining_scoped_to_w2() -> None:
    docs = [_doc("w2", dtype="w2")]
    fired = evaluate_deterministic_rule(
        load_rule_spec("IN-10"),
        _snap(docs=docs, by_subject={"w2": {"income.is_declining": _tag("yes")}}),
    )
    assert fired[0].verdict is Verdict.FIRED


# --------------------------------------------------------------------------- #
# IN-7 / IN-13 / IN-14 — judgment through the generic evaluator (armor + fail-closed)
# --------------------------------------------------------------------------- #
async def test_judgment_rules_are_ratification_pending_and_gate_fail_closed() -> None:
    for rule_id, reasoned in [
        ("IN-7", {"income.same_line_of_work": _tag("yes")}),
        ("IN-13", {"income.continuance_3yr": _tag("yes"), "income.type": _tag("other")}),
        (
            "IN-14",
            {"income.continuance_3yr": _tag("yes"), "occupancy.rental_support": _tag("adequate")},
        ),
    ]:
        docs = [_doc("d", borrower=_B1)]
        evals = await evaluate_judgment_rule(
            load_rule_spec(rule_id),
            _snap(docs=docs, by_subject={str(_B1): reasoned}),
            reasoner=_Reasoner("yes"),
        )
        assert (
            evals and evals[0].evaluation.ratification_pending
        )  # ARMOR: every verdict ratification-pending
        assert evals[0].evaluation.verdict is Verdict.NEEDS_REVIEW

        # Fail-closed: the gated tag absent → couldnt_check, NO AI call.
        stub = _Reasoner("yes")
        gated = await evaluate_judgment_rule(
            load_rule_spec(rule_id),
            _snap(docs=[_doc("d", borrower=_B1)], by_subject={str(_B1): {}}),
            reasoner=stub,
        )
        assert gated and gated[0].evaluation.verdict is Verdict.COULDNT_CHECK and stub.calls == 0


# --------------------------------------------------------------------------- #
# The wave criterion — every authored IN rule runs from a spec through a GENERIC evaluator
# --------------------------------------------------------------------------- #
def test_all_authored_in_rules_load_and_route_to_a_generic_evaluator() -> None:
    authored = [
        "IN-1",
        "IN-2",
        "IN-3",
        "IN-4",
        "IN-5",
        "IN-7",
        "IN-8",
        "IN-9",
        "IN-10",
        "IN-11",
        "IN-12",
        "IN-13",
        "IN-14",
    ]
    for rid in authored:
        spec = load_rule_spec(rid)
        assert (
            sum(x is not None for x in (spec.deterministic, spec.consistency, spec.judgment)) == 1
        )
    # IN-6 is deferred (D3) — no spec.
    from app.verification.rules.specs import RuleSpecNotFound

    with pytest.raises(RuleSpecNotFound):
        load_rule_spec("IN-6")
