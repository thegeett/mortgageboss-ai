"""LP-323-IN-C — the INCOME family GOLDEN EVAL (the full case matrix + the three pinned known-wrongs).

Mirrors the LP-323-ID-C harness (the LP-317 harness is AS-1/txn-shaped; this is the dedicated income
harness beside it — same discipline: finding-level verdict + tag-level golden labels + provenance + the
no-AI cost property + the judgment armor + the derived-tag abstention, keyless via the Reasoner stub).

EVALUATE, DON'T FIX. Every rule gets both directions (a must-FIRE + a must-not-fire), the fail-closed
cases, the LP-323-IN-A §4 domain edge, and — NEW for this wave — REAL numeric boundaries (IN-1's 5%) and
case 12 (a derived tag abstaining → couldnt_check, the path ID could never test). N/As are asserted
explicitly. This eval is INDEPENDENT of activation — each rule is exercised by calling its evaluator
directly (activation gates the orchestrator, not the evaluator), so it holds whether or not a rule is in
ACTIVE_RULE_IDS (IN-2 is active as of LP-333; IN-1 was activated by LP-332, then de-activated by LP-333).
IN-6 is DEFERRED (no spec).

THREE KNOWN-WRONG behaviours are PINNED here (asserting the CURRENT behaviour, documented in the doc, NOT
fixed): (1) loan-level aggregate MASKING of per-borrower income fraud — the #1 false-green; (2) IN-11
OVER-FIRES on non-variable income; (3) IN-12 is a MINIMAL 2-year-return check, not a 1084 analysis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import RuleSpecNotFound, load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.declarations import ProductionMode, TagDeclaration
from app.verification.tag_materialization.derived import (
    _income_max_employment_gap,
    produce_derived_tags,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_B1 = uuid4()
_B2 = uuid4()


# --------------------------------------------------------------------------- #
# Fixture builders (realistic snapshot shapes — documents, borrowers, income tags)
# --------------------------------------------------------------------------- #
def _tag(value: object, *, conf: float | None = 0.9, by: TagProducedBy = TagProducedBy.AI) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture-labeled",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _parsed(value: object) -> Tag:
    return _tag(value, conf=None, by=TagProducedBy.PARSED)


def _derived(value: object) -> Tag:
    return _tag(value, conf=None, by=TagProducedBy.DERIVED)


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
    """A keyless stub for the judgment leg — records whether the AI was invoked (the cost property)."""

    def __init__(self, value: str = "yes") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "because"), 1, 1, "stub", False)


def _verdicts(results: list[RuleEvaluation]) -> list[Verdict]:
    return [r.verdict for r in results]


# ================================================================================================= #
# IN-1 — stated-vs-documented shortfall (deterministic, loan, derived tag, 5% threshold)
# ================================================================================================= #
def _in1(shortfall: str | None):
    # LP-332: IN-1 is PER-BORROWER — the shortfall tag keys under a borrower_id; the per_borrower
    # enumerator finds the borrower via a document's belongs_to.
    tags = (
        {str(_B1): {"income.documented_income_shortfall_pct": _derived(shortfall)}}
        if shortfall
        else {}
    )
    return evaluate_deterministic_rule(
        load_rule_spec("IN-1"), _snap(docs=[_doc("d", borrower=_B1)], by_subject=tags)
    )


def test_in1_case1_2_must_fire_and_clean() -> None:
    (fired,) = _in1("0.20")
    assert (
        fired.verdict is Verdict.FIRED and fired.reasoning
    )  # 20% shortfall > 5% + case 9 provenance
    assert _in1("0.02")[0].verdict is Verdict.SATISFIED  # within tolerance


def test_in1_case3_4_real_numeric_boundaries() -> None:
    # NEW THIS WAVE — a REAL over/under boundary (ID's string compares had none).
    assert _in1("0.0501")[0].verdict is Verdict.FIRED  # just OVER 5%
    assert _in1("0.0499")[0].verdict is Verdict.SATISFIED  # just UNDER 5%


def test_in1_case12_derived_abstention_couldnt_check() -> None:
    # NEW THIS WAVE — the derived tag absent → couldnt_check (proves D2 routes around Caveat A).
    (cc,) = _in1(None)
    assert cc.verdict is Verdict.COULDNT_CHECK


def test_in1_case13_raise_between_documents_does_not_fire() -> None:
    # DOMAIN EDGE: documented ABOVE stated (a raise) → a NEGATIVE signed shortfall → satisfied, NOT fired.
    assert _in1("-0.15")[0].verdict is Verdict.SATISFIED


# IN-1 cases 5/6 (absent/unknown feeding tag) live in the RECIPE (test_recipe_abstains, IN-B) → the
# derived tag becomes "unknown" → case 12 path here. Case 7 (low-conf) N/A: a derived tag's confidence
# is None (a passthrough), so it never routes to needs_review. Case 11 (armor) N/A: not a judgment.


# ================================================================================================= #
# PIN #1 (THE #1 FALSE-GREEN) — loan-level aggregate MASKS per-borrower income fraud
# ================================================================================================= #
def _mismo_borrower(idx: int, bid, monthly: str) -> dict:
    return {
        f"borrower.{idx}.borrower_id": Field.present(str(bid), source=FieldSource.EXTRACTED),
        f"borrower.{idx}.income.1.monthly_amount": Field.present(
            monthly, source=FieldSource.EXTRACTED
        ),
    }


def test_pin1_now_fixed_per_borrower_fires_for_the_fraud_borrower() -> None:
    # LP-332 FIXES PIN #1 (this test previously asserted SATISFIED — the loan-level masking). The shortfall
    # is now PER BORROWER: a 2-borrower file where borrower A's documented income is 40% SHORT of stated
    # (the fraud signal) and borrower B's EXCEEDS stated → borrower A FIRES, borrower B is satisfied — A
    # is no longer masked by B. The pin's fix ticket has landed (borrower-keyed materialization, LP-332).
    facts = {**_mismo_borrower(1, _B1, "5000"), **_mismo_borrower(2, _B2, "5000")}
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(
            [_doc("aStub", borrower=_B1), _doc("bStub", borrower=_B2)]
        ),
        mismo=MismoSection.present(facts),
        tags=TagsSection.present(
            {
                "aStub": {"income.documented_monthly": _tag("3000")},  # A: 40% short of stated
                "bStub": {"income.documented_monthly": _tag("7000")},  # B: a raise
            }
        ),
    )
    decl = TagDeclaration(
        tag_id="income.documented_income_shortfall_pct",
        mode=ProductionMode.DERIVED,
        subject="borrower",
        data="income_documented_shortfall",
        allowed_values=None,
    )
    produced = produce_derived_tags(decl, snap)
    assert produced[str(_B1)]["income.documented_income_shortfall_pct"].value == "0.4"  # A fires
    assert str(produced[str(_B2)]["income.documented_income_shortfall_pct"].value).startswith(
        "-"
    )  # B raise

    # IN-1 (per_borrower) now FIRES for borrower A and is satisfied for borrower B — no masking.
    merged = {**snap.tags.by_subject}
    for sid, tags in produced.items():
        merged.setdefault(sid, {}).update(tags)
    evals = evaluate_deterministic_rule(
        load_rule_spec("IN-1"), snap.model_copy(update={"tags": TagsSection.present(merged)})
    )
    by = {e.subject_id: e.verdict for e in evals}
    assert by[str(_B1)] is Verdict.FIRED and by[str(_B2)] is Verdict.SATISFIED


# ================================================================================================= #
# IN-2 — paystub recency (deterministic, loan, derived days, 30-day window)
# ================================================================================================= #
def _in2(days: str | None):
    tags = {"loan": {"income.days_since_most_recent_pay": _derived(days)}} if days else {}
    return evaluate_deterministic_rule(load_rule_spec("IN-2"), _snap(by_subject=tags))


def test_in2_fire_clean_boundaries_abstention() -> None:
    (fired,) = _in2("45")
    assert fired.verdict is Verdict.FIRED and fired.reasoning  # 1 + 9
    assert _in2("20")[0].verdict is Verdict.SATISFIED  # 2
    assert _in2("31")[0].verdict is Verdict.FIRED  # 3 just OVER
    assert _in2("30")[0].verdict is Verdict.SATISFIED  # 4 at/under
    assert _in2(None)[0].verdict is Verdict.COULDNT_CHECK  # 12 abstention
    # case 13 (partial-period paystub): a mid-cycle stub's pay DATE is recent → small age → satisfied.
    assert _in2("5")[0].verdict is Verdict.SATISFIED


# ================================================================================================= #
# IN-3 — YTD consistency (deterministic, loan, derived, 10% tolerance)
# ================================================================================================= #
def _in3(shortfall: str | None):
    tags = (
        {"loan": {"income.ytd_annualized_shortfall_pct": _derived(shortfall)}} if shortfall else {}
    )
    return evaluate_deterministic_rule(load_rule_spec("IN-3"), _snap(by_subject=tags))


def test_in3_fire_clean_boundary_abstention() -> None:
    assert _in3("0.30")[0].verdict is Verdict.FIRED  # YTD 30% short of documented
    assert _in3("0.05")[0].verdict is Verdict.SATISFIED
    assert _in3("0.1001")[0].verdict is Verdict.FIRED  # 3 just OVER 10%
    assert _in3("0.0999")[0].verdict is Verdict.SATISFIED  # 4 just UNDER
    assert _in3(None)[0].verdict is Verdict.COULDNT_CHECK  # 12
    # case 13 (mid-year start): a short YTD → the recipe abstains upstream (a partial period is expected);
    # here a NEGATIVE shortfall (YTD annualized exceeds documented) → satisfied, not fired.
    assert _in3("-0.05")[0].verdict is Verdict.SATISFIED


# ================================================================================================= #
# IN-4 — employment gap (deterministic, loan, derived days, 30-day window)
# ================================================================================================= #
def _in4(gap: str | None):
    tags = {"loan": {"income.max_employment_gap_days": _derived(gap)}} if gap else {}
    return evaluate_deterministic_rule(load_rule_spec("IN-4"), _snap(by_subject=tags))


def test_in4_fire_clean_boundary_abstention_and_recipe() -> None:
    assert _in4("120")[0].verdict is Verdict.FIRED  # 4-month gap
    assert _in4("0")[0].verdict is Verdict.SATISFIED
    assert _in4("31")[0].verdict is Verdict.FIRED  # 3 over
    assert _in4("30")[0].verdict is Verdict.SATISFIED  # 4 under
    assert _in4(None)[0].verdict is Verdict.COULDNT_CHECK  # 12
    # case 13 (short explained gap) vs long gap — the recipe measures the largest gap; a single job → unknown.
    assert (
        _income_max_employment_gap(_snap(docs=[_doc("d")]), "loan", None)[0] == "unknown"
    )  # <2 records → abstain


# ================================================================================================= #
# IN-5 — employer consistency (LP-325 fuzzy) — the COST property + ABSENT≠DISAGREEING
# ================================================================================================= #
async def _in5(employers: dict[str, str], reasoner):
    docs = [_doc(cid) for cid in employers]
    by_subject = {
        cid: {"income.employer_normalized": _tag(name)} for cid, name in employers.items()
    }
    return await evaluate_consistency_rule(
        load_rule_spec("IN-5"), _snap(docs=docs, by_subject=by_subject), reasoner=reasoner
    )


async def test_in5_full() -> None:
    # 1 must-fire (genuinely different employers), 9 provenance.
    fire = await _in5({"pay": "Acme Corp", "w2": "Globex Inc"}, _Reasoner("disagree"))
    assert _verdicts(fire) == [Verdict.FIRED] and fire[0].reasoning
    # 2 exact match → satisfied + THE COST PROPERTY (no AI call).
    stub = _Reasoner("disagree")
    exact = await _in5({"pay": "Acme Corp", "w2": "Acme Corp"}, stub)
    assert _verdicts(exact) == [Verdict.SATISFIED] and stub.calls == 0
    # 5 <2 sources → couldnt_check (ABSENT≠DISAGREEING).
    lone = await _in5({"pay": "Acme Corp"}, _Reasoner())
    assert _verdicts(lone) == [Verdict.COULDNT_CHECK] and "needs at least two" in lone[0].reasoning
    # 13a (LP-340): "Acme Corporation" vs "Acme" is now a benign SUFFIX difference — drop_entity_suffix
    # collapses it at the EXACT bookend → satisfied, NO AI call (the case the convention optimises for).
    suffix = _Reasoner("agree")
    suffix_diff = await _in5({"pay": "Acme Corporation", "w2": "Acme"}, suffix)
    assert _verdicts(suffix_diff) == [Verdict.SATISFIED] and suffix.calls == 0
    # 13b: a genuine common-name/DBA variance that is NOT a suffix still reaches the AI judge, which
    # agrees → satisfied + ratification_pending (the fuzzy leg survives for the real signal).
    dba = _Reasoner("agree")
    benign = await _in5({"pay": "Acme Corporation", "w2": "Acme Trucking"}, dba)
    assert (
        _verdicts(benign) == [Verdict.SATISFIED]
        and dba.calls == 1
        and benign[0].ratification_pending
    )


# ================================================================================================= #
# IN-8 / IN-9 / IN-12 — per_document deterministic with applicability. (IN-10/IN-11 MOVED to per_borrower
# by LP-390-1 — they read income.is_declining / has_2yr_history, which LP-385 produces at the BORROWER
# subject; see _det_borrower + the per-borrower section below. IN-12 reads has_2yr_history per_document too
# — the SAME latent mismatch, deferred to LP-390-2 by scope; its test still hand-places the tag.)
# ================================================================================================= #
def _det_doc(rule_id: str, docs_tags: dict[str, tuple[str, dict[str, Tag]]]):
    """docs_tags = {content_id: (document_type, {tag_id: Tag})}."""
    docs = [_doc(cid, dtype=dt) for cid, (dt, _) in docs_tags.items()]
    by_subject = {cid: tags for cid, (_, tags) in docs_tags.items() if tags}
    return evaluate_deterministic_rule(
        load_rule_spec(rule_id), _snap(docs=docs, by_subject=by_subject)
    )


def _det_borrower(rule_id: str, borrower_tags: dict[str, Tag], *, borrower=_B1):
    """LP-390-1 — a per-BORROWER deterministic read: the tag lives under by_subject[borrower_id] (where the
    income_stability producer puts it, LP-385), with a document belongs_to that borrower so the per_borrower
    enumerator yields it. The TRUE path — NOT hand-placing a borrower-subject tag at the document subject
    (the fiction IN-10/IN-11 passed under before LP-390-1)."""
    docs = [_doc("d", borrower=borrower)]
    return evaluate_deterministic_rule(
        load_rule_spec(rule_id), _snap(docs=docs, by_subject={str(borrower): borrower_tags})
    )


def test_in8_voe_scope_expected_absence_and_verbal_edge() -> None:
    by = {
        r.subject_id: r.verdict
        for r in _det_doc(
            "IN-8",
            {
                "voe": (
                    "voe",  # LP-333: classifier document type
                    {"income.voe_present": _tag("no")},
                ),  # case 1 fire
                "pay": ("paystub", {}),  # scope: not_applicable
            },
        )
    }
    assert by["voe"] is Verdict.FIRED and by["pay"] is Verdict.NOT_APPLICABLE
    # case 2 clean; case 13 (a verbal VOE where written required) — the tag encodes acceptability.
    ok = _det_doc("IN-8", {"voe": ("voe", {"income.voe_present": _tag("yes")})})
    assert ok[0].verdict is Verdict.SATISFIED
    # case 5/12: no VOE document at all — a VOE is EXPECTED (LP-330) → couldnt_check, never not_applicable.
    miss = _det_doc("IN-8", {"pay": ("paystub", {})})
    assert any(v.verdict is Verdict.COULDNT_CHECK for v in miss)


def test_in9_offer_letter_scope_and_fire() -> None:
    fire = _det_doc(
        "IN-9", {"off": ("employment_offer_letter", {"income.offer_letter_present": _tag("no")})}
    )
    assert fire[0].verdict is Verdict.FIRED  # future job, no valid offer letter
    ok = _det_doc(
        "IN-9", {"off": ("employment_offer_letter", {"income.offer_letter_present": _tag("yes")})}
    )
    assert ok[0].verdict is Verdict.SATISFIED
    na = _det_doc("IN-9", {"pay": ("paystub", {})})
    assert na[0].verdict is Verdict.NOT_APPLICABLE  # not expected — offer letters are the exception


# ================================================================================================= #
# IN-10 / IN-11 — PER BORROWER (LP-390-1). Read at the borrower subject through the TRUE path (was read
# per_document, where LP-385's borrower-subject tag never lives → couldnt_check on every file, the sixth
# structural-dead instance). Still INERT (AI-uncalibrated) — the income wave activates them.
# ================================================================================================= #
def test_in10_declining_fires_and_low_confidence_needs_review() -> None:
    fire = _det_borrower("IN-10", {"income.is_declining": _tag("yes")})
    assert fire[0].verdict is Verdict.FIRED and fire[0].reasoning  # fires on the decline
    clean = _det_borrower("IN-10", {"income.is_declining": _tag("no")})
    assert clean[0].verdict is Verdict.SATISFIED
    # low-confidence AI tag → needs_review (an AI enum, unlike the derived rules).
    low = _det_borrower("IN-10", {"income.is_declining": _tag("yes", conf=0.2)})
    assert low[0].verdict is Verdict.NEEDS_REVIEW
    # unknown value → couldnt_check WITH A REASON (distinct at the gate) — never a guessed verdict.
    unk = _det_borrower("IN-10", {"income.is_declining": _tag("unknown")})
    assert unk[0].verdict is Verdict.COULDNT_CHECK and "could not be read" in unk[0].reasoning


def test_in10_11_read_the_borrower_subject_not_the_document() -> None:
    # THE FIX (LP-390-1): the tag placed at the DOCUMENT subject is NOT read (the pre-fix fiction). Placed at
    # the BORROWER subject, it IS. A document with belongs_to but the tag hand-placed on the DOCUMENT →
    # couldnt_check (the borrower's tag is absent), proving the rule no longer reads the document subject.
    at_document = _det_doc("IN-10", {"w2": ("w2", {"income.is_declining": _tag("yes")})})
    assert at_document[0].verdict is Verdict.COULDNT_CHECK  # the borrower-subject tag is absent
    at_borrower = _det_borrower("IN-10", {"income.is_declining": _tag("yes")})
    assert at_borrower[0].verdict is Verdict.FIRED  # read at the subject the tag actually lives on


def test_in10_11_per_borrower_isolation() -> None:
    # B1 declining, B2 not — each judged on their OWN tag; borrower A's trend never feeds borrower B's
    # (the LP-332 masking class). Both borrowers enumerate (each has a document); one verdict each.
    docs = [_doc("d1", borrower=_B1), _doc("d2", borrower=_B2)]
    by_subject = {
        str(_B1): {"income.is_declining": _tag("yes")},
        str(_B2): {"income.is_declining": _tag("no")},
    }
    verdicts = {
        str(r.subject_id): r.verdict
        for r in evaluate_deterministic_rule(
            load_rule_spec("IN-10"), _snap(docs=docs, by_subject=by_subject)
        )
    }
    assert verdicts[str(_B1)] is Verdict.FIRED  # B1's own declining trend
    assert verdicts[str(_B2)] is Verdict.SATISFIED  # B2's own stable trend — not masked, not leaked


# ================================================================================================= #
# PIN #2 — IN-11 OVER-FIRES on non-variable income (no set-membership operand) — now PER BORROWER
# ================================================================================================= #
def test_pin2_in11_overfires_on_salaried_income() -> None:
    # Salaried income with <2yr history (a new base-pay job) → IN-11 FIRES, which is WRONG: the 2-year rule
    # is for VARIABLE income (bonus/overtime/commission). IN-11 reads income.has_2yr_history with no filter
    # on income.type (no set-membership operand). PINNED (a separate ticket). Even with income.type EXPLICITLY
    # salary, IN-11 still fires — proving it has no income.type filter, read per-borrower (LP-390-1).
    salaried = _det_borrower(
        "IN-11", {"income.has_2yr_history": _tag("no"), "income.type": _tag("salary")}
    )
    assert (
        salaried[0].verdict is Verdict.FIRED
    )  # WRONG for salaried base pay — the pinned over-fire
    # a 2-year history present → satisfied (the true-negative path).
    assert (
        _det_borrower("IN-11", {"income.has_2yr_history": _tag("yes")})[0].verdict
        is Verdict.SATISFIED
    )


def test_in10_11_inert_but_now_reach_the_rule() -> None:
    # LP-390-1 does NOT activate: IN-10/IN-11 stay inert (AI-uncalibrated; the income wave calibrates them).
    # But the input now REACHES the rule (per-borrower), so they are calibratable — no longer structurally
    # dead. (Their bars are AI, not-calibratable-yet — the gate holds them on calibration, not the mismatch.)
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

    assert "IN-10" not in ACTIVE_RULE_IDS and "IN-11" not in ACTIVE_RULE_IDS
    for rid in ("IN-10", "IN-11"):
        assert load_rule_spec(rid).subject_enumeration == "per_borrower"


class _StabilityStub:
    """income_stability reasoner reporting a DECLINING trend for every subject — to drive IN-10 end to end."""

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "has_2yr_history": AiTagJudgment("yes", 0.9, "two consecutive years"),
                        "is_declining": AiTagJudgment("yes", 0.9, "wages fell year over year"),
                        "same_line_of_work": AiTagJudgment("yes", 0.9, "same employer"),
                        "continuance_3yr": AiTagJudgment("unknown", 0.5, "no horizon stated"),
                    },
                )
                for s in subjects
            ],
            1,
            1,
            "stub",
            False,
        )


async def test_in10_fires_end_to_end_through_real_income_stability_materialization() -> None:
    # THE DURABLE GUARD (LP-390-1 review): the hand-placed tests above prove IN-10 READS the borrower subject,
    # but not that income_stability WRITES there — the exact producer/consumer alignment whose break made this
    # rule structurally dead. Materialize income.is_declining through the REAL producer (it, not the test,
    # chooses the subject key) and evaluate IN-10 against it, so a future divergence between the production
    # enumerator (MISMO-keyed) and IN-10's per_borrower read (belongs_to-keyed) fails HERE, not silently in prod.
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="w2a",
                    document_type="w2",
                    belongs_to=(BorrowerRef(borrower_id=_B1, name="Sam"),),
                    fields={
                        "tax_year": Field.present("2024", source=FieldSource.EXTRACTED),
                        "employer_name": Field.present("Acme", source=FieldSource.EXTRACTED),
                        "wages_tips_other_comp": Field.present(
                            "90000", source=FieldSource.EXTRACTED
                        ),
                    },
                )
            ]
        ),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": Field.present(str(_B1), source=FieldSource.EXTRACTED)}
        ),
        tags=TagsSection.present({}),
    )
    mat = await materialize_tags(
        snap,
        ai_reasoners={"income_stability": _StabilityStub()},
        only_subjects=frozenset({"borrower"}),
        only_groups=frozenset({"income_stability"}),
    )
    # the producer keyed the signal under the BORROWER subject (borrower_id), not a document content_id ...
    assert mat.tags.by_subject[str(_B1)]["income.is_declining"].value == "yes"
    assert "w2a" not in mat.tags.by_subject
    # ... and IN-10 reads it at that same key → FIRED. Producer key == consumer key, proven end to end.
    verdicts = {
        str(r.subject_id): r.verdict
        for r in evaluate_deterministic_rule(load_rule_spec("IN-10"), mat)
    }
    assert verdicts[str(_B1)] is Verdict.FIRED


# ================================================================================================= #
# PIN #3 — IN-12 is a MINIMAL 2-year-return check, not a 1084 analysis
# ================================================================================================= #
def test_pin3_in12_minimal_check_only() -> None:
    # What it DOES mechanically: fires on self-employment lacking a 2-year return history. NB (LP-390-1
    # review): this hand-places has_2yr_history at the tax_return DOCUMENT subject — the path PRODUCTION no
    # longer feeds, since LP-385 moved the tag to subject:borrower. So this asserts IN-12's evaluator wiring,
    # NOT that IN-12 works on a real file; the structural-death guard is test_in12_..._dead_until_lp390_2 below.
    fire = _det_doc("IN-12", {"tr": ("tax_return", {"income.has_2yr_history": _tag("no")})})
    assert fire[0].verdict is Verdict.FIRED
    # What it does NOT do: a 2-year history present → SATISFIED, even with declining net / missing add-backs
    # (K-1/1099/P&L). The real Form-1084 cash-flow analysis is NOT modeled (compute_self_employed_income
    # is unwired). PINNED (a separate ticket: wire the self-employment calculator).
    passes = _det_doc("IN-12", {"tr": ("tax_return", {"income.has_2yr_history": _tag("yes")})})
    assert passes[0].verdict is Verdict.SATISFIED  # no 1084 analysis — under-covers


@pytest.mark.xfail(
    strict=True,
    reason="LP-390-2: IN-12 still reads income.has_2yr_history per_document at the tax_return subject, but "
    "LP-385 produces that tag at subject:borrower — so on a REAL file IN-12 is structurally dead "
    "(couldnt_check), the same sixth-instance bug LP-390-1 fixed for IN-10/IN-11. The fix is NOT a naive "
    "per_borrower copy (that would duplicate IN-11's has_2yr_history fire — IN-12 must stay self-employment-"
    "specific), which is why it is deferred. When LP-390-2 lands, this XPASSES (strict) and must be rewritten.",
)
def test_in12_self_employment_history_is_structurally_dead_until_lp390_2() -> None:
    # DESIRED production behavior: a self-employed borrower whose tax returns lack a 2-year history → IN-12
    # FIRES. ACTUAL today: has_2yr_history lives at the BORROWER subject (LP-385), invisible to IN-12's
    # per_document tax_return read → couldnt_check. This pin makes the deferred debt VISIBLE and fails loudly
    # (XPASS) the moment IN-12 is fixed, forcing LP-390-2 to be deliberate rather than silently green-while-dead.
    docs = [_doc("tr", dtype="tax_return", borrower=_B1)]
    by_subject = {str(_B1): {"income.has_2yr_history": _tag("no")}}
    verdicts = evaluate_deterministic_rule(
        load_rule_spec("IN-12"), _snap(docs=docs, by_subject=by_subject)
    )
    assert any(
        v.verdict is Verdict.FIRED for v in verdicts
    )  # xfails today; XPASS ⇒ LP-390-2 landed


# ================================================================================================= #
# IN-7 / IN-13 / IN-14 — judgment (per_borrower) — ARMOR + fail-closed + provenance
# ================================================================================================= #
async def _judge(rule_id: str, reasoned: dict[str, Tag], reasoner, borrower=_B1):
    docs = [_doc("d", borrower=borrower)]
    return await evaluate_judgment_rule(
        load_rule_spec(rule_id),
        _snap(docs=docs, by_subject={str(borrower): reasoned}),
        reasoner=reasoner,
    )


async def test_judgment_rules_armor_provenance_failclosed() -> None:
    cases = {
        "IN-7": {
            "income.same_line_of_work": _tag("no"),
            "income.employment_start": _parsed("2026-01-01"),
        },
        "IN-13": {"income.continuance_3yr": _tag("no"), "income.type": _tag("other")},
        "IN-14": {
            "income.continuance_3yr": _tag("no"),
            "occupancy.rental_support": _tag("inadequate"),
        },
    }
    for rule_id, reasoned in cases.items():
        stub = _Reasoner("no")
        (ev,) = await _judge(rule_id, reasoned, stub)
        assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW  # a judgment never auto-fires
        assert (
            ev.evaluation.ratification_pending
        )  # CASE 11 ARMOR — every verdict ratification-pending
        assert (
            ev.evaluation.reasoning and stub.calls == 1
        )  # CASE 9 provenance; the AI was consulted
        # Fail-closed: the gated reasoned-over tag absent → couldnt_check, NO AI call.
        gated_stub = _Reasoner("no")
        (gated,) = await _judge(rule_id, {}, gated_stub)
        assert gated.evaluation.verdict is Verdict.COULDNT_CHECK and gated_stub.calls == 0


async def test_in7_case13_same_field_vs_unrelated() -> None:
    # DOMAIN EDGE: the same-line-of-work signal drives the judgment; both directions reach the AI (the
    # verdict is always needs_review + ratification-pending — the underwriter ratifies).
    same = _Reasoner("yes")
    (s,) = await _judge(
        "IN-7",
        {"income.same_line_of_work": _tag("yes"), "income.employment_start": _parsed("2025-01-01")},
        same,
    )
    assert s.evaluation.ratification_pending and same.calls == 1


# ================================================================================================= #
# IN-6 — DEFERRED (D3: needs LP-331's multi-value gather leg) — assert only that it has no spec
# ================================================================================================= #
def test_in6_is_deferred_no_spec() -> None:
    with pytest.raises(RuleSpecNotFound):
        load_rule_spec("IN-6")


# ================================================================================================= #
# NO EVAL FATIGUE — every in-scope IN rule has a must-FIRE case in this module (the guard test)
# ================================================================================================= #
def test_every_in_scope_in_rule_has_a_must_fire_case_in_this_module() -> None:
    # Checked against the module's LIVE callables (NOT a source-string grep, which would trivially match
    # the marker list itself and could never fail). Each value is the must-fire test FUNCTION's name
    # prefix; deleting that test trips the guard.
    defined = {
        name for name, obj in globals().items() if name.startswith("test_") and callable(obj)
    }
    markers = {
        "IN-1": "test_in1_case1_2_must_fire",
        "IN-2": "test_in2_fire",
        "IN-3": "test_in3_fire",
        "IN-4": "test_in4_fire",
        "IN-5": "test_in5_full",
        "IN-7": "test_judgment_rules_armor",
        "IN-8": "test_in8_voe_scope",
        "IN-9": "test_in9_offer_letter",
        "IN-10": "test_in10_declining_fires",
        "IN-11": "test_pin2_in11_overfires",
        "IN-12": "test_pin3_in12_minimal",
        "IN-13": "test_judgment_rules_armor",
        "IN-14": "test_judgment_rules_armor",
    }
    for rid, prefix in markers.items():
        assert any(name.startswith(prefix) for name in defined), (
            f"{rid} is missing a must-fire case — a rule with no fire case is NOT evaluated"
        )
