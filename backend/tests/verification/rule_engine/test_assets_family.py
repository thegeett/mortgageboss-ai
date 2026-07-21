"""LP-323-AS-B — the ASSETS family runs from DATA through the GENERIC evaluators (no engine Python).

Minimal per-rule smoke tests (the FULL 13-point matrix is AS-C's job). Proves: the specs + declarations +
recipes are the whole of the authoring (the wave criterion); AS-4's gated `reserves` CALC → couldnt_check
(case 12, the family's first real calc-gate); the derived-tag abstention; the AS-12 judgment armor; and
that NONE of the evaluators / gate / generic producers changed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import (
    _reserves_required_months,
    _stmt_min_account_months,
    _stmt_nsf_count,
)

pytestmark = pytest.mark.anyio

_B = uuid4()


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


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _doc(cid: str, dtype: str = "bank_statement") -> DocumentEntry:
    return DocumentEntry(
        content_id=cid, document_type=dtype, belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),)
    )


def _snap(*, docs=None, by_subject=None, mismo=None, reserves=None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present(by_subject or {}),
        calculations=CalculationsSection.present(reserves=reserves)
        if reserves is not None
        else CalculationsSection.missing(),
    )


# --------------------------------------------------------------------------- #
# The recipes (arithmetic + honest abstention)
# --------------------------------------------------------------------------- #
def test_reserves_required_months_matrix_and_abstention() -> None:
    inv = _snap(mismo={"property.occupancy": _f("investment")})
    assert _reserves_required_months(inv, "loan", None)[0] == "6"  # agency-standard cell
    sh = _snap(mismo={"property.occupancy": _f("second_home")})
    assert _reserves_required_months(sh, "loan", None)[0] == "2"
    # An occupancy not in the encoded map ABSTAINS (Priya-pending) — never a guessed requirement.
    other = _snap(mismo={"property.occupancy": _f("triplex_investment")})
    v, r = _reserves_required_months(other, "loan", None)
    assert v == "unknown" and "Priya-pending" in r


def test_nsf_count_and_min_account_months_recipes() -> None:
    nsf = _snap(
        by_subject={
            "t1": {"txn.is_nsf_or_overdraft": _tag("yes")},
            "t2": {"txn.is_nsf_or_overdraft": _tag("yes")},
            "t3": {"txn.is_nsf_or_overdraft": _tag("no")},
        }
    )
    assert _stmt_nsf_count(nsf, "loan", None)[0] == "2"
    # min_account_months: one account (Chase ****5678) with 2 months → 2.
    docs = [_doc("jan"), _doc("feb")]
    for d in docs:
        d.fields.update(
            {
                "bank_name": _f("Chase"),
                "account_number_masked": Field.present("12345678", source=FieldSource.EXTRACTED),
            }
        )
    snap = _snap(
        docs=docs,
        by_subject={
            "jan": {"stmt.period_end": _tag("2026-05-31")},
            "feb": {"stmt.period_end": _tag("2026-06-30")},
        },
    )
    assert _stmt_min_account_months(snap, "loan", None)[0] == "2"


def test_nsf_count_abstains_when_the_detection_tag_is_absent_everywhere() -> None:
    # PRODUCTION REALITY: txn.is_nsf_or_overdraft has no producer, so no transaction carries it. A concrete
    # "0" would false-green AS-7 (every file reads NSF-clean); the recipe abstains (absent≠no). But when the
    # tag IS present — even all "no" — a concrete 0 is legitimate (detection ran, found none).
    no_tag = _snap(by_subject={"t1": {"txn.is_money_in": _tag("yes")}})  # txns exist, no NSF tag
    v, r = _stmt_nsf_count(no_tag, "loan", None)
    assert v == "unknown" and "has not run" in r
    clean = _snap(by_subject={"t1": {"txn.is_nsf_or_overdraft": _tag("no")}})
    assert _stmt_nsf_count(clean, "loan", None)[0] == "0"


def test_min_account_months_abstains_when_an_account_has_no_parseable_dates() -> None:
    # Account A (Chase) has a dated statement; account B (Wells Fargo) has ONLY an unparseable date. B is
    # uncountable — counting it as 0 months would fire a FALSE recency violation, and the true min is
    # unknowable (B could be the shortest). The recipe abstains rather than report a fabricated 0.
    a, b = _doc("a_jan"), _doc("b_jan")
    a.fields.update(
        {
            "bank_name": _f("Chase"),
            "account_number_masked": Field.present("1111", source=FieldSource.EXTRACTED),
        }
    )
    b.fields.update(
        {
            "bank_name": _f("Wells Fargo"),
            "account_number_masked": Field.present("2222", source=FieldSource.EXTRACTED),
        }
    )
    snap = _snap(
        docs=[a, b],
        by_subject={
            "a_jan": {"stmt.period_end": _tag("2026-05-31")},
            "b_jan": {
                "stmt.period_end": _tag("not-a-date")
            },  # uncountable account → abstain, not 0
        },
    )
    v, r = _stmt_min_account_months(snap, "loan", None)
    assert v == "unknown" and "could not be parsed" in r


# --------------------------------------------------------------------------- #
# AS-4 — the calc + matrix rule; case 12 (a GATED reserves calc → couldnt_check)
# --------------------------------------------------------------------------- #
def _as4(months_available: str | None, required: str | None, *, gated: bool = False):
    reserves = None
    if months_available is not None:
        reserves = CalculationEntry(value={"months_available": months_available}, gated=gated)
    tags = (
        {"loan": {"reserves.required_months": _tag(required, by=TagProducedBy.DERIVED)}}
        if required
        else {}
    )
    return evaluate_deterministic_rule(
        load_rule_spec("AS-4"), _snap(by_subject=tags, reserves=reserves)
    )


def test_as4_fires_satisfies_and_case12_gated_calc_couldnt_check() -> None:
    assert _as4("1", "6")[0].verdict is Verdict.FIRED  # 1 < 6 required
    assert _as4("6", "6")[0].verdict is Verdict.SATISFIED
    # CASE 12 — a GATED reserves calc → the operand is None → couldnt_check (the family's first calc-gate).
    assert _as4("6", "6", gated=True)[0].verdict is Verdict.COULDNT_CHECK
    # required_months absent (a Priya-pending occupancy) → gate → couldnt_check.
    assert _as4("6", None)[0].verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# The deterministic per-rule smoke (fire / clean / gated)
# --------------------------------------------------------------------------- #
def test_as7_nsf_over_tolerance_fires() -> None:
    tags = {"loan": {"stmt.nsf_count": _tag("5", by=TagProducedBy.DERIVED)}}
    assert (
        evaluate_deterministic_rule(load_rule_spec("AS-7"), _snap(by_subject=tags))[0].verdict
        is Verdict.FIRED
    )
    tags2 = {"loan": {"stmt.nsf_count": _tag("1", by=TagProducedBy.DERIVED)}}
    assert (
        evaluate_deterministic_rule(load_rule_spec("AS-7"), _snap(by_subject=tags2))[0].verdict
        is Verdict.SATISFIED
    )


def test_as10_short_account_fires() -> None:
    tags = {"loan": {"stmt.min_account_months": _tag("1", by=TagProducedBy.DERIVED)}}
    assert (
        evaluate_deterministic_rule(load_rule_spec("AS-10"), _snap(by_subject=tags))[0].verdict
        is Verdict.FIRED
    )


def test_as6_owner_mismatch_fires_scoped_to_statements() -> None:
    docs = [_doc("bs", "bank_statement"), _doc("dl", "drivers_license")]
    by = {
        r.subject_id: r.verdict
        for r in evaluate_deterministic_rule(
            load_rule_spec("AS-6"),
            _snap(docs=docs, by_subject={"bs": {"stmt.owner_matches_borrower": _tag("no")}}),
        )
    }
    assert (
        by["bs"] is Verdict.FIRED and by["dl"] is Verdict.NOT_APPLICABLE
    )  # non-statement out of scope


def test_as11_restricted_asset_fires() -> None:
    docs = [_doc("ra", "retirement_account")]
    r = evaluate_deterministic_rule(
        load_rule_spec("AS-11"),
        _snap(docs=docs, by_subject={"ra": {"asset.liquidation_terms": _tag("restricted")}}),
    )
    assert r[0].verdict is Verdict.FIRED


def test_as3_and_as9_bucket_c_couldnt_check() -> None:
    # AS-3: the cash-to-close derived tag abstains (closing_costs not extracted) → couldnt_check.
    assert (
        evaluate_deterministic_rule(load_rule_spec("AS-3"), _snap())[0].verdict
        is Verdict.COULDNT_CHECK
    )
    # AS-9: with NO page-count tags on the statement → couldnt_check (both gated). LP-381 makes the fields
    # extractable; a statement that carries them resolves (test_as9_resolves_when_page_counts_present).
    docs = [_doc("bs", "bank_statement")]
    assert (
        evaluate_deterministic_rule(load_rule_spec("AS-9"), _snap(docs=docs))[0].verdict
        is Verdict.COULDNT_CHECK
    )


def test_as9_resolves_when_page_counts_present() -> None:
    # LP-381: the page-count tags now extract; given them, AS-9 reaches a REAL verdict (not couldnt_check).
    docs = [_doc("bs", "bank_statement")]
    # declared (printed "of 5") > present (3 actual pages) → a page is MISSING → fired.
    fired = evaluate_deterministic_rule(
        load_rule_spec("AS-9"),
        _snap(
            docs=docs,
            by_subject={
                "bs": {"stmt.page_count_declared": _tag(5), "stmt.page_count_present": _tag(3)}
            },
        ),
    )[0]
    assert fired.verdict is Verdict.FIRED
    # declared == present → all pages present → satisfied.
    ok = evaluate_deterministic_rule(
        load_rule_spec("AS-9"),
        _snap(
            docs=docs,
            by_subject={
                "bs": {"stmt.page_count_declared": _tag(5), "stmt.page_count_present": _tag(5)}
            },
        ),
    )[0]
    assert ok.verdict is Verdict.SATISFIED
    # only the deterministic present, no printed "of N" → still couldnt_check (the honest completeness gap).
    no_decl = evaluate_deterministic_rule(
        load_rule_spec("AS-9"),
        _snap(docs=docs, by_subject={"bs": {"stmt.page_count_present": _tag(3)}}),
    )[0]
    assert no_decl.verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# AS-12 — judgment armor (every verdict ratification-pending)
# --------------------------------------------------------------------------- #
class _Reasoner:
    def __init__(self, value: str = "yes") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


async def test_as12_judgment_is_ratification_pending() -> None:
    from app.verification.snapshot.model import TransactionRecord

    txn = TransactionRecord(
        content_id="t1",
        amount=_f("10000"),
        date=_f("2026-05-01"),
        direction=_f("credit"),
        description=_f("wire"),
    )
    doc = DocumentEntry(
        content_id="bs",
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),),
        transactions=(txn,),
    )
    snap = _snap(
        docs=[doc],
        by_subject={
            "t1": {
                "txn.apparent_category": _tag("loan_proceeds"),
                "txn.has_identified_source": _tag("no"),
                "txn.counterparty": _tag("Unknown LLC"),
            }
        },
    )
    stub = _Reasoner("yes")
    evals = await evaluate_judgment_rule(load_rule_spec("AS-12"), snap, reasoner=stub)
    assert (
        evals and evals[0].evaluation.verdict is Verdict.NEEDS_REVIEW
    )  # a judgment never auto-fires
    assert evals[0].evaluation.ratification_pending and stub.calls == 1


# --------------------------------------------------------------------------- #
# The criterion — every authored AS rule loads + routes to a generic evaluator (no engine change)
# --------------------------------------------------------------------------- #
def test_all_authored_as_rules_load_and_route() -> None:
    for rid in ["AS-2", "AS-3", "AS-4", "AS-5", "AS-6", "AS-7", "AS-9", "AS-10", "AS-11", "AS-12"]:
        spec = load_rule_spec(rid)
        assert (
            sum(x is not None for x in (spec.deterministic, spec.consistency, spec.judgment)) == 1
        )
    from app.verification.rules.specs import RuleSpecNotFound

    with pytest.raises(RuleSpecNotFound):
        load_rule_spec("AS-8")  # deferred (pairwise-sequential shape — LP-323-AS-A)
