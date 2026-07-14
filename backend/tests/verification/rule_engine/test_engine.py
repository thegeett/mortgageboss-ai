"""The thin rule engine end-to-end (LP-315) — AS-1 over a tagged snapshot.

Exercises the real path: load_rule_spec("AS-1") (the 50% threshold + priya_validated=false), the
qualifying income from the DTI calculator, per-deposit subject enumeration, and the gate+rule per
subject. No AI, no DB — tags + the DTI calc are provided via fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

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
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_DOC = "docstmt0000000000"


def _tag(
    value: str, *, confidence: float | None, produced_by: TagProducedBy, stage: TagStage, cid: str
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=(cid,),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=stage,
    )


def _snapshot(
    deposits: list[tuple[str, str, str | None, str]],
    *,
    income: str | None = "8000",
    tags_absent: bool = False,
) -> Snapshot:
    """deposits = [(amount, is_money_in, has_identified_source|None, transaction_type)]."""
    raw = [
        {"date": "2026-05-05", "amount": amt, "description": "DEP", "transaction_type": tt}
        for (amt, _mi, _src, tt) in deposits
    ]
    field_sets = transaction_field_sets({"transactions": raw}, "bank_statement")
    txns = build_transactions(field_sets, document_content_id=_DOC)
    assert txns is not None

    by_subject: dict[str, dict[str, Tag]] = {}
    for txn, (_amt, money_in, source, _tt) in zip(txns, deposits, strict=True):
        cid = txn.content_id
        tags = {
            "txn.is_money_in": _tag(
                money_in, confidence=0.9, produced_by=TagProducedBy.AI, stage=TagStage.A, cid=cid
            ),
            "txn.amount": _tag(
                str(txn.amount.value),
                confidence=None,
                produced_by=TagProducedBy.PARSED,
                stage=TagStage.A,
                cid=cid,
            ),
        }
        if source is not None:
            tags["txn.has_identified_source"] = _tag(
                source, confidence=0.8, produced_by=TagProducedBy.AI, stage=TagStage.B, cid=cid
            )
        by_subject[cid] = tags

    entry = DocumentEntry(content_id=_DOC, document_type="bank_statement", transactions=txns)
    calculations = (
        CalculationsSection.present(
            dti=CalculationEntry(value={"gross_monthly_income": income}, breakdown=[])
        )
        if income is not None
        else CalculationsSection.missing()
    )
    tags_section = TagsSection.missing() if tags_absent else TagsSection.present(by_subject)
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present([entry]),
        calculations=calculations,
        tags=tags_section,
    )


def _only(results: list[RuleEvaluation]) -> RuleEvaluation:
    assert len(results) == 1
    return results[0]


def test_end_to_end_fires_on_unsourced_large_deposit() -> None:
    # income 8000 → spec's 50% threshold = 4000; a 5000 unsourced deposit fires.
    snap = _snapshot([("5000.00", "in", "no", "deposit")], income="8000")
    result = _only(evaluate_as1_rule(snap))
    assert result.rule_id == "AS-1"
    assert result.verdict is Verdict.FIRED
    assert result.threshold_used == Decimal(
        "4000.0"
    )  # 0.5 (from the spec) * 8000 (from the DTI calc)
    assert result.gated_pending_signoff is True  # AS-1 priya_validated=false in the spec


def test_threshold_comes_from_the_spec_and_calc_income() -> None:
    # Same 5000 deposit, but income 12000 → threshold 6000 → below → satisfied. The boundary moved
    # with the income, proving the 50% multiplier came from the spec (not a hardcoded number).
    snap = _snapshot([("5000.00", "in", "no", "deposit")], income="12000")
    result = _only(evaluate_as1_rule(snap))
    assert result.verdict is Verdict.SATISFIED
    assert result.threshold_used == Decimal("6000.0")


def test_no_direction_filter_transfer_labelled_deposit_is_evaluated() -> None:
    """A transaction whose raw transaction_type is the ambiguous 'transfer' but whose is_money_in
    TAG is 'in' is evaluated (fired) — not silently dropped. The direction bug cannot recur."""
    snap = _snapshot([("9000.00", "in", "no", "transfer")], income="8000")
    result = _only(evaluate_as1_rule(snap))
    assert result.verdict is Verdict.FIRED  # evaluated, not filtered out by a raw label


def test_money_out_transaction_is_not_applicable() -> None:
    snap = _snapshot([("40.00", "out", None, "withdrawal")], income="8000")
    result = _only(evaluate_as1_rule(snap))
    assert result.verdict is Verdict.NOT_APPLICABLE


def test_multiple_subjects_each_get_a_result() -> None:
    snap = _snapshot(
        [
            ("5000.00", "in", "no", "deposit"),  # fires
            ("5000.00", "in", "yes", "deposit"),  # sourced → satisfied
            ("40.00", "out", None, "withdrawal"),  # n/a
        ],
        income="8000",
    )
    verdicts = [r.verdict for r in evaluate_as1_rule(snap)]
    assert verdicts.count(Verdict.FIRED) == 1
    assert verdicts.count(Verdict.SATISFIED) == 1
    assert verdicts.count(Verdict.NOT_APPLICABLE) == 1


def test_tags_absent_yields_couldnt_check() -> None:
    snap = _snapshot([("5000.00", "in", "no", "deposit")], income="8000", tags_absent=True)
    result = _only(evaluate_as1_rule(snap))
    assert result.verdict is Verdict.COULDNT_CHECK


def test_income_unavailable_yields_couldnt_check() -> None:
    snap = _snapshot([("5000.00", "in", "no", "deposit")], income=None)
    result = _only(evaluate_as1_rule(snap))
    assert result.verdict is Verdict.COULDNT_CHECK
