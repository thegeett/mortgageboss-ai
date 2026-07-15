"""LP-332 — borrower-keyed materialization + the borrower_id ↔ MISMO-index resolution.

The resolution: MISMO keys borrowers `borrower.{n}` where n is a re-derived SORT POSITION (not durable);
LP-332 emits `borrower.{n}.borrower_id` so a `belongs_to` UUID maps back to the MISMO group — the ONLY
non-name-matching resolution (BorrowerRef rejects name-matching). The "borrower" production subject reads
that link and keys tags under the borrower_id, MEETING the LP-331 consumer (`_per_borrower` reads
`by_subject[borrower_id]`).

THE FAILURE MODE (the heart of the ticket): an unresolvable/ambiguous mapping → the borrower is SKIPPED →
its borrower-keyed tags are ABSENT → the rule couldnt_checks. NEVER a name-guessed attribution
(misattributing a fact fabricates or hides a discrepancy — worse than not attributing it).
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
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import ProductionMode, TagDeclaration
from app.verification.tag_materialization.derived import (
    _app_required_fields_present,
    produce_derived_tags,
)
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import subject_type

pytestmark = pytest.mark.anyio

_A = uuid4()
_B = uuid4()


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


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


def _doc(cid: str, *, borrower) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type="paystub",
        belongs_to=(BorrowerRef(borrower_id=borrower, name="Sam"),),
    )


def _snap(*, mismo: dict, docs=None, tags=None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present(tags or {}),
    )


class _Reasoner:
    def __init__(self, value: str = "yes") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


# --------------------------------------------------------------------------- #
# THE RESOLUTION — the borrower subject enumerates by borrower_id
# --------------------------------------------------------------------------- #
def test_borrower_subject_resolves_each_borrower_by_id() -> None:
    snap = _snap(
        mismo={
            "borrower.1.borrower_id": _f(str(_A)),
            "borrower.1.citizenship": _f("us_citizen"),
            "borrower.2.borrower_id": _f(str(_B)),
            "borrower.2.citizenship": _f("permanent_resident"),
        }
    )
    subjects = subject_type("borrower").enumerate(snap)
    assert [sid for sid, _ in subjects] == [
        str(_A),
        str(_B),
    ]  # keyed by borrower_id, in MISMO order


# --------------------------------------------------------------------------- #
# THE FAILURE MODE — unresolvable/ambiguous → skip → couldnt_check, never a guess
# --------------------------------------------------------------------------- #
def test_missing_id_link_skips_the_borrower_never_guesses() -> None:
    # A borrower group with NO borrower_id fact → not enumerated (no safe attribution). The list ends at
    # the first gap; a later group is not reached (contiguous-from-1 contract).
    snap = _snap(mismo={"borrower.1.citizenship": _f("us_citizen")})  # no borrower_id
    assert subject_type("borrower").enumerate(snap) == []


def test_duplicate_id_link_skips_the_ambiguous_borrower() -> None:
    # Two groups claiming the SAME borrower_id is ambiguous → the duplicate is skipped (fail-closed), not
    # attributed to one arbitrarily.
    snap = _snap(
        mismo={
            "borrower.1.borrower_id": _f(str(_A)),
            "borrower.2.borrower_id": _f(str(_A)),  # duplicate — unsafe
        }
    )
    assert [sid for sid, _ in subject_type("borrower").enumerate(snap)] == [str(_A)]


# --------------------------------------------------------------------------- #
# PER-SUBJECT FAIL-CLOSED — one borrower's gap never fails another
# --------------------------------------------------------------------------- #
def test_per_borrower_shortfall_isolated_and_fixes_pin1() -> None:
    snap = _snap(
        mismo={
            "borrower.1.borrower_id": _f(str(_A)),
            "borrower.1.income.1.monthly_amount": _f("5000"),
            "borrower.2.borrower_id": _f(str(_B)),
            "borrower.2.income.1.monthly_amount": _f("5000"),
        },
        docs=[_doc("aStub", borrower=_A), _doc("bStub", borrower=_B)],
        tags={
            "aStub": {"income.documented_monthly": _tag("3000")},  # A: 40% short
            "bStub": {"income.documented_monthly": _tag("7000")},  # B: a raise
        },
    )
    decl = TagDeclaration(
        "income.documented_income_shortfall_pct",
        ProductionMode.DERIVED,
        "borrower",
        "income_documented_shortfall",
        None,
    )
    produced = produce_derived_tags(decl, snap)
    assert produced[str(_A)]["income.documented_income_shortfall_pct"].value == "0.4"  # A fires
    assert str(produced[str(_B)]["income.documented_income_shortfall_pct"].value).startswith("-")

    # Per-subject fail-closed: borrower B's income absent → B abstains (unknown), A still computes.
    snap_b_absent = _snap(
        mismo={
            "borrower.1.borrower_id": _f(str(_A)),
            "borrower.1.income.1.monthly_amount": _f("5000"),
            "borrower.2.borrower_id": _f(str(_B)),  # no income
        },
        docs=[_doc("aStub", borrower=_A)],
        tags={"aStub": {"income.documented_monthly": _tag("3000")}},
    )
    p2 = produce_derived_tags(decl, snap_b_absent)
    assert p2[str(_A)]["income.documented_income_shortfall_pct"].value == "0.4"
    assert (
        p2[str(_B)]["income.documented_income_shortfall_pct"].value == "unknown"
    )  # B abstains, A unaffected


# --------------------------------------------------------------------------- #
# THE LOAN CANARY — a loan-level recipe is unchanged
# --------------------------------------------------------------------------- #
def test_loan_recipe_unchanged_regression_canary() -> None:
    snap = _snap(
        mismo={
            "borrower.1.name": _f("Sam"),
            "borrower.1.ssn": _f("x"),
            "loan.amount": _f("100"),
            "property.address": _f("1 Main"),
        }
    )
    # _app_required_fields_present ignores the subject args (LP-332) — logic identical.
    value, _ = _app_required_fields_present(snap, "loan", None)
    assert value == "complete"
    missing_value, _ = _app_required_fields_present(
        _snap(mismo={"borrower.1.name": _f("Sam")}), "loan", None
    )
    assert missing_value == "incomplete + list"


# --------------------------------------------------------------------------- #
# ACTIVATION — id.citizenship materializes under borrower_id; ID-8 evaluates
# --------------------------------------------------------------------------- #
async def test_id_citizenship_materializes_under_borrower_id() -> None:
    snap = _snap(
        mismo={"borrower.1.borrower_id": _f(str(_A)), "borrower.1.citizenship": _f("us_citizen")},
        docs=[_doc("d", borrower=_A)],
    )
    out = await materialize_tags(snap, only_subjects=frozenset({"borrower"}))
    assert out.tags.by_subject[str(_A)]["id.citizenship"].value == "us_citizen"
    assert out.tags.by_subject[str(_A)]["id.citizenship"].produced_by is TagProducedBy.PARSED


async def test_id8_activates_per_borrower_with_armor() -> None:
    # id.citizenship (borrower) + program.type (loan) materialize → ID-8's per-borrower judgment runs.
    snap = _snap(
        mismo={
            "borrower.1.borrower_id": _f(str(_A)),
            "borrower.1.citizenship": _f("non_permanent_resident"),
            "loan.program": _f("conventional"),
        },
        docs=[_doc("d", borrower=_A)],
    )
    materialized = await materialize_tags(snap, only_subjects=frozenset({"borrower", "loan"}))
    assert materialized.tags.by_subject["loan"]["program.type"].value == "conventional"
    stub = _Reasoner("yes")
    evals = await evaluate_judgment_rule(load_rule_spec("ID-8"), materialized, reasoner=stub)
    assert evals and evals[0].evaluation.subject_id == str(_A)
    assert evals[0].evaluation.verdict is Verdict.NEEDS_REVIEW  # a judgment never auto-fires
    assert evals[0].evaluation.ratification_pending  # ARMOR — every verdict ratification-pending
    assert stub.calls == 1  # the gate passed (citizenship + program present) → the AI was consulted


async def test_id8_couldnt_check_when_the_id_link_is_missing() -> None:
    # No borrower_id link → id.citizenship cannot materialize under the borrower → ID-8 couldnt_checks,
    # NEVER a guessed citizenship attribution (the failure mode, end-to-end).
    snap = _snap(
        mismo={
            "borrower.1.citizenship": _f("us_citizen"),
            "loan.program": _f("conventional"),
        },  # no id link
        docs=[_doc("d", borrower=_A)],
    )
    materialized = await materialize_tags(snap, only_subjects=frozenset({"borrower", "loan"}))
    stub = _Reasoner("yes")
    evals = await evaluate_judgment_rule(load_rule_spec("ID-8"), materialized, reasoner=stub)
    assert (
        evals and evals[0].evaluation.verdict is Verdict.COULDNT_CHECK and stub.calls == 0
    )  # gated, no AI


# --------------------------------------------------------------------------- #
# IN-1 activates through the deterministic evaluator (per_borrower, end-to-end)
# --------------------------------------------------------------------------- #
def test_in1_fires_for_the_fraud_borrower_end_to_end() -> None:
    snap = _snap(
        mismo={
            "borrower.1.borrower_id": _f(str(_A)),
            "borrower.1.income.1.monthly_amount": _f("5000"),
        },
        docs=[_doc("aStub", borrower=_A)],
        tags={
            str(_A): {
                "income.documented_income_shortfall_pct": _tag("0.4", by=TagProducedBy.DERIVED)
            },
        },
    )
    (ev,) = evaluate_deterministic_rule(load_rule_spec("IN-1"), snap)
    assert ev.subject_id == str(_A) and ev.verdict is Verdict.FIRED
