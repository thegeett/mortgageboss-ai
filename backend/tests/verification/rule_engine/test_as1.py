"""AS-1 as DATA (LP-324) — the rule runs through the GENERIC deterministic evaluator from its spec.

Behaviourally identical to the former per-rule module (the LP-324 equivalence property): each case
drives ``evaluate_as1_rule`` over a one-transaction snapshot carrying the subject's tags + a DTI calc
for the qualifying-income operand. The threshold (50%) and the multiplier now live in ``AS-1.yaml``,
not in these tests — so the ``multiplier`` knob and the raw ``contradiction`` input are gone (the
contradiction path is a gate concern, covered by ``test_gate.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.verification.rule_engine.as1 import (
    TAG_AMOUNT,
    TAG_HAS_SOURCE,
    TAG_IS_MONEY_IN,
    TAG_SOURCE_STRENGTH,
)
from app.verification.rule_engine.engine import evaluate_as1_rule
from app.verification.rule_engine.enumerators import LOAN_SUBJECT
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_INCOME = Decimal("8000")  # threshold = 0.5 * 8000 = 4000
_DOC = "docstmt0000000000"
# LP-366 — the income tag AS-1 now reads (a loan-level `loan_tag` operand), replacing the DTI calc.
_INCOME_TAG = "dti.qualifying_income_monthly"


def _tag(
    tag_id: str,
    value: str,
    *,
    confidence: float | None,
    produced_by: TagProducedBy,
    stage: TagStage,
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning=f"{tag_id} reason",
        source_facts=("txndeposit0000000",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=stage,
    )


def _money_in(value: str = "in", *, confidence: float | None = 0.9) -> Tag:
    return _tag(
        TAG_IS_MONEY_IN,
        value,
        confidence=confidence,
        produced_by=TagProducedBy.AI,
        stage=TagStage.A,
    )


def _amount(value: str) -> Tag:
    return _tag(
        TAG_AMOUNT, value, confidence=None, produced_by=TagProducedBy.PARSED, stage=TagStage.A
    )


def _source(value: str = "no", *, confidence: float | None = 0.8) -> Tag:
    return _tag(
        TAG_HAS_SOURCE, value, confidence=confidence, produced_by=TagProducedBy.AI, stage=TagStage.B
    )


def _evaluate(
    tags: dict[str, Tag],
    *,
    confidence_floor: float = 0.5,
    income: Decimal | None = _INCOME,
) -> RuleEvaluation:
    """Run AS-1 (the spec, via the generic evaluator) over a one-transaction snapshot carrying
    ``tags`` + the qualifying-income LOAN tag AS-1 reads via its ``loan_tag`` operand (LP-366). ``income=
    None`` → no income tag → the operand resolves to None → couldnt_check (the fail-closed path)."""
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
            loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
        ),
        document_content_id=_DOC,
    )
    assert txns is not None
    cid = txns[0].content_id
    by_subject: dict[str, dict[str, Tag]] = {cid: dict(tags)}
    if income is not None:
        # The loan-level income tag (derived from the borrowers' MISMO stated income), read by AS-1's
        # `loan_tag` operand. No confidence — it is a deterministic derived aggregate.
        by_subject[LOAN_SUBJECT] = {
            _INCOME_TAG: _tag(
                _INCOME_TAG,
                str(income),
                confidence=None,
                produced_by=TagProducedBy.DERIVED,
                stage=TagStage.A,
            )
        }
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id=_DOC, document_type="bank_statement", transactions=txns)]
        ),
        tags=TagsSection.present(by_subject),
    )
    [result] = evaluate_as1_rule(snap, confidence_floor=confidence_floor)
    return result


# --------------------------------------------------------------------------- #
# Fires / satisfied
# --------------------------------------------------------------------------- #


def test_fires_on_unsourced_large_deposit() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(confidence=0.9),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no", confidence=0.8),
        }
    )
    assert result.verdict is Verdict.FIRED
    assert result.threshold_used == Decimal("4000.0")  # 0.5 * 8000
    assert result.verdict_confidence == 0.8  # min(is_money_in 0.9, has_source 0.8); amount ignored
    assert result.how_to_fix is not None
    # The three load-bearing tags are carried inline (provenance — never a bare number).
    ids = {t.tag_id for t in result.load_bearing_tags}
    assert ids == {TAG_IS_MONEY_IN, TAG_AMOUNT, TAG_HAS_SOURCE}
    assert result.gated_pending_signoff is True  # AS-1 threshold not Priya-validated


def test_satisfied_when_sourced() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("yes"),
        }
    )
    assert result.verdict is Verdict.SATISFIED


def test_satisfied_when_below_threshold() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("3000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert result.verdict is Verdict.SATISFIED


def test_threshold_boundary_uses_strict_greater_than() -> None:
    # Exactly at the threshold (4000) is NOT over (GT is strict) → satisfied.
    at = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("4000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert at.verdict is Verdict.SATISFIED
    # A cent above fires.
    over = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("4000.01"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert over.verdict is Verdict.FIRED


# --------------------------------------------------------------------------- #
# Fail-closed gate
# --------------------------------------------------------------------------- #


def test_has_identified_source_unknown_is_couldnt_check_not_fired() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("unknown"),
        }
    )
    assert result.verdict is Verdict.COULDNT_CHECK
    assert (
        "could not be read" in result.reasoning
    )  # LP-376-C: the deposit's source, in mortgage terms


def test_is_money_in_unknown_is_couldnt_check() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in("unknown"),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert result.verdict is Verdict.COULDNT_CHECK


def test_absent_source_tag_is_couldnt_check_distinct_reason() -> None:
    result = _evaluate(
        {TAG_IS_MONEY_IN: _money_in(), TAG_AMOUNT: _amount("5000.00")}
    )  # no has_source
    assert result.verdict is Verdict.COULDNT_CHECK
    # LP-376-C: names the deposit's source (the missing fact) + "could not be found", not the tag id.
    assert "could not be found" in result.reasoning and "source" in result.reasoning


def test_low_confidence_load_bearing_tag_is_needs_review() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(confidence=0.9),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no", confidence=0.3),
        }
    )
    assert result.verdict is Verdict.NEEDS_REVIEW  # NOT a confident satisfied/fired
    assert result.verdict_confidence == 0.3


def test_income_unavailable_is_couldnt_check_never_a_fabricated_threshold() -> None:
    """No DTI → the qualifying-income operand can't resolve → the threshold operand is None →
    couldnt_check, never a comparison against a fabricated (e.g. zero) threshold that would fire on
    any deposit. (Replaces the former injected-multiplier test — the multiplier is spec data now.)"""
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no"),
        },
        income=None,
    )
    assert result.verdict is Verdict.COULDNT_CHECK
    assert result.threshold_used is None  # no threshold was computed


# --------------------------------------------------------------------------- #
# Applicability + the no-direction-filter guarantee
# --------------------------------------------------------------------------- #


def test_money_out_is_not_applicable() -> None:
    result = _evaluate({TAG_IS_MONEY_IN: _money_in("out"), TAG_AMOUNT: _amount("5000.00")})
    assert result.verdict is Verdict.NOT_APPLICABLE


def test_deposit_is_evaluated_regardless_of_raw_label() -> None:
    """The bug cannot recur: applicability is the is_money_in TAG, not a raw label. A deposit the
    AI judged money-in is evaluated even though its raw label was 'transfer'/ambiguous."""
    # We only carry the TAG here — there is no raw 'direction' anywhere in the rule's input.
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in("in"),
            TAG_AMOUNT: _amount("9000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert result.verdict is Verdict.FIRED  # evaluated + fired, not silently dropped


def test_deterministic_same_tags_same_verdict() -> None:
    tags = {
        TAG_IS_MONEY_IN: _money_in(),
        TAG_AMOUNT: _amount("5000.00"),
        TAG_HAS_SOURCE: _source("no"),
    }
    assert _evaluate(tags).verdict == _evaluate(tags).verdict == Verdict.FIRED


# --------------------------------------------------------------------------- #
# Source STRENGTH (LP-314a) — a claim is not a proven paper trail
# --------------------------------------------------------------------------- #


def _strength(value: str) -> Tag:
    return _tag(
        TAG_SOURCE_STRENGTH,
        value,
        confidence=0.8,
        produced_by=TagProducedBy.DERIVED,
        stage=TagStage.B,
    )


def _sourced_large(strength: str | None) -> dict[str, Tag]:
    # A sourced ($5000 > $4000 threshold) deposit, optionally carrying a strength tag.
    tags = {
        TAG_IS_MONEY_IN: _money_in(),
        TAG_AMOUNT: _amount("5000.00"),
        TAG_HAS_SOURCE: _source("yes"),
    }
    if strength is not None:
        tags[TAG_SOURCE_STRENGTH] = _strength(strength)
    return tags


def test_large_self_asserted_source_is_needs_review() -> None:
    result = _evaluate(_sourced_large("self_asserted"))
    assert result.verdict is Verdict.NEEDS_REVIEW  # NOT a clean satisfied
    assert result.how_to_fix is not None and "paper trail" in result.how_to_fix
    assert "self_asserted" in result.reasoning
    # The strength tag is carried inline for provenance.
    assert any(t.tag_id == TAG_SOURCE_STRENGTH for t in result.load_bearing_tags)


def test_large_verified_source_is_satisfied() -> None:
    assert _evaluate(_sourced_large("verified")).verdict is Verdict.SATISFIED


def test_large_intrinsic_source_is_satisfied() -> None:
    assert _evaluate(_sourced_large("intrinsic")).verdict is Verdict.SATISFIED


def test_small_self_asserted_source_is_satisfied() -> None:
    # A small ($3000 < $4000) self-asserted transfer is not worth a manual chase.
    tags = {
        TAG_IS_MONEY_IN: _money_in(),
        TAG_AMOUNT: _amount("3000.00"),
        TAG_HAS_SOURCE: _source("yes"),
        TAG_SOURCE_STRENGTH: _strength("self_asserted"),
    }
    assert _evaluate(tags).verdict is Verdict.SATISFIED


def test_sourced_without_strength_tag_is_satisfied_backward_compatible() -> None:
    # An older snapshot with no source_strength tag → sourced large deposit still satisfies.
    assert _evaluate(_sourced_large(None)).verdict is Verdict.SATISFIED


def test_at_threshold_self_asserted_is_needs_review_ge_boundary() -> None:
    # "at or over" (GE) — a self-asserted deposit exactly at the threshold routes to needs_review.
    tags = {
        TAG_IS_MONEY_IN: _money_in(),
        TAG_AMOUNT: _amount("4000.00"),  # exactly the threshold
        TAG_HAS_SOURCE: _source("yes"),
        TAG_SOURCE_STRENGTH: _strength("self_asserted"),
    }
    assert _evaluate(tags).verdict is Verdict.NEEDS_REVIEW
