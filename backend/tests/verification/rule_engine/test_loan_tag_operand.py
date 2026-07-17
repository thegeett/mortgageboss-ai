"""The `loan_tag` operand (LP-366-A) — a declared operand that reads a LOAN-subject tag from ANY rule,
whatever its own subject.

The gap it closes: a `tag` operand is SUBJECT-scoped (`_resolve_operand` reads `subject_tags`), and the
`per_deposit` enumerator hands each transaction ONLY its own tag map — never the loan's. So a per-deposit
rule (AS-1) literally cannot read a loan-level fact through a `tag` operand; the only door to loan-level
was `calc`, which drags in a calculator's gate (AS-1's false DTI dependency, LP-366). `loan_tag` is that
missing door: it reaches `by_subject[LOAN_SUBJECT]` directly, fail-closed, carrying the tag's confidence
(the property `calc` lacks — LP-318 Caveat A). No rule-id branch; a rule opts in with a SPEC line only.

Equivalence: every live rule is untouched (AS-1 still reads `calc`; that swap is LP-366), and the `calc`
operand is untouched (AS-4's reserves→PITI→insurance dependency is legitimate).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import (
    _resolve_operand,
    evaluate_deterministic_rule,
)
from app.verification.rule_engine.enumerators import LOAN_SUBJECT
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import Operand, RuleSpec, load_rule_spec
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from pydantic import JsonValue

_DOC = "docstmt0000000000"


def _tag(value: JsonValue, *, confidence: float | None = None) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=("loan",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _deposit_snapshot(
    *, loan_tags: dict[str, Tag] | None, txn_tags: dict[str, Tag], amount: str = "9000.00"
) -> tuple[Snapshot, str]:
    """A one-bank-statement-transaction snapshot: `txn_tags` land under the txn's own content_id,
    `loan_tags` (if any) under LOAN_SUBJECT. Mirrors the shape AS-1 evaluates."""
    txns = build_transactions(
        transaction_field_sets(
            {
                "transactions": [
                    {
                        "date": "2026-05-05",
                        "amount": amount,
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
    by_subject: dict[str, dict[str, Tag]] = {cid: dict(txn_tags)}
    if loan_tags is not None:
        by_subject[LOAN_SUBJECT] = dict(loan_tags)
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id=_DOC, document_type="bank_statement", transactions=txns)]
        ),
        tags=TagsSection.present(by_subject),
    )
    return snap, cid


# --------------------------------------------------------------------------- #
# The mechanism — _resolve_operand reaches the LOAN subject, ignoring subject_tags
# --------------------------------------------------------------------------- #
def test_loan_tag_reads_the_loan_subject_from_a_non_loan_subject() -> None:
    # The core property: resolved against a DEPOSIT's subject_tags (which do NOT contain the loan tag),
    # a `loan_tag` operand still resolves the LOAN-level value. This is exactly what a `tag` operand
    # cannot do — and what AS-1 needs.
    snap, cid = _deposit_snapshot(
        loan_tags={"dti.qualifying_income_monthly": _tag("28168.80")},
        txn_tags={"txn.amount": _tag("9000.00")},
    )
    deposit_tags = snap.tags.by_subject[cid]
    spec = load_rule_spec("AS-1")  # spec is unused by the loan_tag branch; any real spec serves
    resolved = _resolve_operand(
        Operand(loan_tag="dti.qualifying_income_monthly"), spec, snap, deposit_tags
    )
    assert resolved == Decimal("28168.80")
    # Contrast: a plain `tag` operand, from the same deposit subject, canNOT see the loan tag.
    assert (
        _resolve_operand(Operand(tag="dti.qualifying_income_monthly"), spec, snap, deposit_tags)
        is None
    )


def test_loan_tag_absent_resolves_to_none_fail_closed() -> None:
    # Absent loan tag → None → couldnt_check. NEVER a fabricated 0 (the whole point: a missing income
    # must block the check, not size a threshold from zero).
    snap, cid = _deposit_snapshot(loan_tags={}, txn_tags={"txn.amount": _tag("9000.00")})
    spec = load_rule_spec("AS-1")
    assert (
        _resolve_operand(
            Operand(loan_tag="dti.qualifying_income_monthly"), spec, snap, snap.tags.by_subject[cid]
        )
        is None
    )


def test_loan_tag_when_loan_subject_missing_entirely_resolves_to_none() -> None:
    snap, cid = _deposit_snapshot(loan_tags=None, txn_tags={"txn.amount": _tag("9000.00")})
    spec = load_rule_spec("AS-1")
    assert (
        _resolve_operand(
            Operand(loan_tag="dti.qualifying_income_monthly"), spec, snap, snap.tags.by_subject[cid]
        )
        is None
    )


def test_loan_tag_unparseable_value_resolves_to_none_never_coerced() -> None:
    # A present-but-unparseable value → None (never a silent 0). Same discipline as a `tag` operand.
    snap, cid = _deposit_snapshot(
        loan_tags={"dti.qualifying_income_monthly": _tag("unknown")},
        txn_tags={"txn.amount": _tag("9000.00")},
    )
    spec = load_rule_spec("AS-1")
    assert (
        _resolve_operand(
            Operand(loan_tag="dti.qualifying_income_monthly"), spec, snap, snap.tags.by_subject[cid]
        )
        is None
    )


# --------------------------------------------------------------------------- #
# The Operand validator — loan_tag is a first-class source; non-decimal type allowed on it
# --------------------------------------------------------------------------- #
def test_loan_tag_is_one_of_the_exactly_one_sources() -> None:
    assert Operand(loan_tag="x").loan_tag == "x"


def test_loan_tag_with_a_second_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="EXACTLY one"):
        Operand(loan_tag="x", tag="y")


def test_non_decimal_type_allowed_on_loan_tag() -> None:
    assert Operand(loan_tag="x", type="date").type == "date"


def test_non_decimal_type_still_rejected_on_reference() -> None:
    with pytest.raises(ValueError, match="only valid on a `tag`/`loan_tag`"):
        Operand(reference="k", type="date")


# --------------------------------------------------------------------------- #
# End to end — a per_deposit rule reads a loan tag FROM A SPEC ONLY (no engine edit per rule)
# --------------------------------------------------------------------------- #
_SYNTH_PER_DEPOSIT_SPEC = {
    "rule_id": "AS-1",  # any calculative row; model_validate does not cross-check the CSV (load does)
    "name": "synthetic loan_tag deposit rule",
    "category": "Assets",
    "kind": "calculative",
    "numeric_check": True,
    "criteria": "a deposit exceeding the loan's stated income fires",
    "applicability": {"scope": "bank statements", "trigger": "per deposit"},
    "required_inputs": [{"name": "amt", "snapshot_path": "x", "description": "d"}],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "per_deposit",
    "subject_key_fields": ["account", "date", "amount"],
    "evidence_required": "the deposit amount and the loan income",
    "guideline_reference": "n/a — synthetic",
    "spec_version": 1,
    "deterministic": {
        "load_bearing_tags": ["txn.is_money_in", "txn.amount"],
        "gated_tags": ["txn.is_money_in", "txn.amount"],
        "applicability": {"tag": "txn.is_money_in", "op": "eq", "value": "in"},
        "operands": {
            "observed": {"tag": "txn.amount"},
            "income": {"loan_tag": "dti.qualifying_income_monthly"},
        },
        "outcomes": [
            {
                "verdict": "fired",
                "when_compare": {"op": ">", "left": "observed", "right": "income"},
                "reasoning": "deposit {observed} exceeds loan income {income}",
            },
            {"verdict": "satisfied", "default": True, "reasoning": "within income"},
        ],
    },
}


def _run_synth(*, loan_tags: dict[str, Tag] | None, amount: str) -> Verdict:
    spec = RuleSpec.model_validate(_SYNTH_PER_DEPOSIT_SPEC)
    snap, _ = _deposit_snapshot(
        loan_tags=loan_tags,
        txn_tags={"txn.is_money_in": _tag("in", confidence=0.9), "txn.amount": _tag(amount)},
        amount=amount,
    )
    [result] = evaluate_deterministic_rule(spec, snap)
    return result.verdict


def test_per_deposit_rule_fires_reading_the_loan_income_tag() -> None:
    # Deposit 9000 > loan income 1000 → fired, driven entirely from the spec's loan_tag operand.
    assert (
        _run_synth(loan_tags={"dti.qualifying_income_monthly": _tag("1000")}, amount="9000.00")
        is Verdict.FIRED
    )


def test_per_deposit_rule_satisfied_below_the_loan_income() -> None:
    assert (
        _run_synth(loan_tags={"dti.qualifying_income_monthly": _tag("50000")}, amount="9000.00")
        is Verdict.SATISFIED
    )


def test_per_deposit_rule_couldnt_check_when_income_tag_absent() -> None:
    # No loan income tag → operand None → couldnt_check (fail-closed), NOT a fire against 0.
    assert _run_synth(loan_tags={}, amount="9000.00") is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# Equivalence — LP-366-A changes NO live rule; AS-1 still reads calc; the fleet is unchanged
# --------------------------------------------------------------------------- #
def test_as1_still_reads_the_dti_calc_untouched() -> None:
    # LP-366-A adds the operand KIND; the AS-1→loan_tag swap is LP-366. AS-1's threshold is still a
    # product ending in the DTI calc, verbatim.
    det = load_rule_spec("AS-1").deterministic
    assert det is not None
    threshold = det.operands["threshold"]
    assert threshold.product is not None
    assert threshold.product[-1].calc == ("dti", "gross_monthly_income")
    assert all(op.loan_tag is None for op in det.operands.values())


def test_active_rule_ids_unchanged() -> None:
    assert (
        "AS-1" in ACTIVE_RULE_IDS
    )  # the fleet still ships the same rules; no rule added/removed here
