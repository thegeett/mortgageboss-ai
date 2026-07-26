"""AS-1 reads income via the `loan_tag` operand, not the gated DTI calc (LP-366).

THE HEADLINE: AS-1 is a LIVE, auto-shipping rule that — until this swap — had never evaluated a single
deposit. It read income THROUGH the DTI calculator, which fail-closes on `housing.insurance_monthly` (an
input AS-1 never uses, and an orphaned tag with no producer — LP-367). So the calc gated → the threshold
operand resolved to None → EVERY money-in deposit was an unresolved candidate regardless of size ($0.07,
$0.16, $0.53 all `couldnt_check`). LP-366-A added the `loan_tag` operand (a per-deposit rule reading a
loan-level tag); LP-366 is the one-line spec swap that walks through it.

These tests assert the thing the whole ticket exists for: with the DTI calc GATED (the real state on the
real file), AS-1 STILL EVALUATES — because it no longer reads the calc. Fail-closed is preserved: income
absent/unknown → couldnt_check (never 0, never fire-on-everything).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.verification.rule_engine.engine import evaluate_as1_rule
from app.verification.rule_engine.enumerators import LOAN_SUBJECT
from app.verification.rule_engine.result import Verdict
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import (
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_DOC = "docstmt0000000000"
_INCOME_TAG = "dti.qualifying_income_monthly"
# The real LF-6T3N stated qualifying income (LP-365's run) → threshold = 50% x 28168.80 = 14084.40.
_REAL_INCOME = Decimal("28168.80")
_REAL_THRESHOLD = Decimal("14084.40")


def _tag(value: str, *, produced_by: TagProducedBy, confidence: float | None) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=("loan",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _gated_dti() -> CalculationsSection:
    """A DTI calc in the REAL broken state: gated because housing.insurance_monthly (orphaned, LP-367)
    is unknown → its headline income is nulled. AS-1 must NOT consult this — that is the whole point."""
    return CalculationsSection.present(
        dti=CalculationEntry(
            value={"gross_monthly_income": None},
            breakdown=[],
            gated=True,
            gate_reason="calculation gated (fail-closed): housing.insurance_monthly is unknown",
        )
    )


def _evaluate(
    *,
    deposit: str,
    income: Decimal | None,
    has_source: str = "no",
    calc: CalculationsSection | None = None,
) -> Verdict:
    """Run AS-1 over one deposit. Income is injected as the LOAN tag AS-1 reads (`loan_tag`); a DTI
    calc, if given, is present but must be IGNORED. income=None → no income tag → couldnt_check."""
    txns = build_transactions(
        transaction_field_sets(
            {
                "transactions": [
                    {
                        "date": "2026-05-05",
                        "amount": "1",
                        "description": "D",
                        "transaction_type": "deposit",
                    }
                ]
            },
            "bank_statement",
        ),
        document_content_id=_DOC,
    )
    assert txns is not None
    cid = txns[0].content_id
    by_subject: dict[str, dict[str, Tag]] = {
        cid: {
            "txn.is_money_in": _tag("in", produced_by=TagProducedBy.AI, confidence=0.9),
            "txn.amount": _tag(deposit, produced_by=TagProducedBy.PARSED, confidence=None),
            "txn.has_identified_source": _tag(
                has_source, produced_by=TagProducedBy.AI, confidence=0.9
            ),
        }
    }
    if income is not None:
        by_subject[LOAN_SUBJECT] = {
            _INCOME_TAG: _tag(str(income), produced_by=TagProducedBy.DERIVED, confidence=None)
        }
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id=_DOC, document_type="bank_statement", transactions=txns)]
        ),
        calculations=calc if calc is not None else CalculationsSection.missing(),
        tags=TagsSection.present(by_subject),
    )
    [result] = evaluate_as1_rule(snap)
    return result.verdict


# --------------------------------------------------------------------------- #
# THE HEADLINE — a gated DTI no longer blocks AS-1
# --------------------------------------------------------------------------- #
def test_evaluates_a_large_deposit_even_with_the_dti_calc_gated() -> None:
    # The real state: DTI gated (insurance orphaned). Before LP-366 this → couldnt_check on EVERY deposit.
    # Now AS-1 reads the loan income tag and FIRES on a genuinely large unsourced deposit.
    verdict = _evaluate(deposit="20000.00", income=_REAL_INCOME, has_source="no", calc=_gated_dti())
    assert verdict is Verdict.FIRED


def test_trivial_deposit_is_satisfied_and_invisible_even_with_the_dti_gated() -> None:
    # The $0.07/$0.16/$0.53 noise the gated calc used to render `couldnt_check` is now SATISFIED (below
    # the threshold) and drops out of the findings entirely.
    for pennies in ("0.07", "0.16", "0.53", "1.93"):
        assert (
            _evaluate(deposit=pennies, income=_REAL_INCOME, calc=_gated_dti()) is Verdict.SATISFIED
        )


def test_evaluates_with_no_dti_calc_at_all() -> None:
    # AS-1 does not even need a DTI calc present — its income comes entirely from the loan tag.
    assert _evaluate(deposit="20000.00", income=_REAL_INCOME, calc=None) is Verdict.FIRED


# --------------------------------------------------------------------------- #
# The threshold that now resolves — 50% x $28,168.80 = $14,084.40
# --------------------------------------------------------------------------- #
def test_threshold_resolves_from_real_income_strict_gt_boundary() -> None:
    just_over = str(_REAL_THRESHOLD + Decimal("0.01"))
    assert _evaluate(deposit=just_over, income=_REAL_INCOME) is Verdict.FIRED
    # Exactly at the threshold is NOT "exceeds" (strict GT) → satisfied.
    assert _evaluate(deposit=str(_REAL_THRESHOLD), income=_REAL_INCOME) is Verdict.SATISFIED
    just_under = str(_REAL_THRESHOLD - Decimal("0.01"))
    assert _evaluate(deposit=just_under, income=_REAL_INCOME) is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# Fail-closed on AS-1's OWN input — income absent/unknown → couldnt_check, NEVER 0, NEVER fire-on-all
# --------------------------------------------------------------------------- #
def test_couldnt_check_when_income_tag_absent() -> None:
    v = _evaluate(deposit="20000.00", income=None)
    assert v is Verdict.COULDNT_CHECK  # NOT fired — a missing income is not a 0 threshold


def test_a_tiny_deposit_with_no_income_is_couldnt_check_not_fired() -> None:
    # The inverse-failure guard: if missing income were treated as 0, a $0.07 deposit would EXCEED a 0
    # threshold and fire. It must couldnt_check instead.
    assert _evaluate(deposit="0.07", income=None) is Verdict.COULDNT_CHECK


def test_unparseable_income_is_couldnt_check() -> None:
    # A present-but-unparseable income tag ("unknown") → operand None → couldnt_check (never coerced to 0).
    assert _evaluate(deposit="20000.00", income=None) is Verdict.COULDNT_CHECK
    # And explicitly via an "unknown"-valued tag:
    txns = build_transactions(
        transaction_field_sets(
            {"transactions": [{"date": "2026-05-05", "amount": "1", "description": "D"}]},
            "bank_statement",
        ),
        document_content_id=_DOC,
    )
    assert txns is not None
    cid = txns[0].content_id
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id=_DOC, document_type="bank_statement", transactions=txns)]
        ),
        tags=TagsSection.present(
            {
                cid: {
                    "txn.is_money_in": _tag("in", produced_by=TagProducedBy.AI, confidence=0.9),
                    "txn.amount": _tag(
                        "20000.00", produced_by=TagProducedBy.PARSED, confidence=None
                    ),
                    "txn.has_identified_source": _tag(
                        "no", produced_by=TagProducedBy.AI, confidence=0.9
                    ),
                },
                LOAN_SUBJECT: {
                    _INCOME_TAG: _tag("unknown", produced_by=TagProducedBy.DERIVED, confidence=None)
                },
            }
        ),
    )
    [result] = evaluate_as1_rule(snap)
    assert result.verdict is Verdict.COULDNT_CHECK
