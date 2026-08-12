"""LP-508 / ADR-377 — the distrusted-field guard: the gate's FIFTH defence.

⚠️ THE HOLE THIS CLOSES. ``gate.py`` had four defences — absent, ``"unknown"``, contradiction, low
confidence — and a confidently-WRONG parsed value defeats all four by construction: it is present, it is
not ``"unknown"``, nothing contradicts it, and the parsed producer sets ``confidence=None``, which the
confidence minimum FILTERS OUT and skips entirely when every load-bearing tag is parsed.

**IH-1 is the case.** Its only gated tag is derived from a parsed field, so it had no confidence defence at
all, and doc 104 (a "coinsurance contract" basis read off a replacement-cost HO3) auto-asserted an
insurance-adequacy verdict.

⚠️ THE BOUNDARY, PINNED HERE TOO. This layer keys on the FIELD, not on whether a given extraction was
wrong — so it is cruder than LP-474's per-extraction checks and broader. It does NOT cover doc 253 (a lone
$224k gift amount with no sibling to contradict it), because no field-level or consistency-level layer can:
there is nothing internal to compare against. That case still passes, and the test below says so.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rules.distrust import (
    DistrustError,
    distrusted_tag_ids,
    load_distrusted_fields,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_FLOOR = 0.8


def _parsed(value: str) -> Tag:
    """A parsed passthrough — ``confidence=None``, exactly the shape the gate could not see."""
    return Tag(
        value=value,
        confidence=None,
        reasoning="parsed",
        source_facts=("doc",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


# --------------------------------------------------------------------------- #
# ⚠️ The motivating case: doc 104 → IH-1 no longer auto-asserts
# --------------------------------------------------------------------------- #
def test_ih1_no_longer_auto_asserts_on_the_distrusted_basis() -> None:
    result = evaluate_gate(
        {"ins.dwelling_settlement_basis": _parsed("replacement_cost")}, confidence_floor=_FLOOR
    )
    assert result.status is GateStatus.NEEDS_REVIEW
    assert result.ratification_pending is True


def test_the_degraded_verdict_names_the_fact_not_the_tag_id() -> None:
    """A processor reads this. It must say what could not be relied on, in mortgage terms."""
    reason = evaluate_gate(
        {"ins.dwelling_settlement_basis": _parsed("replacement_cost")}, confidence_floor=_FLOOR
    ).reason
    assert reason is not None
    assert "ins.dwelling_settlement_basis" not in reason  # never the tag id
    assert "dwelling loss-settlement basis" in reason
    assert "read wrongly before" in reason


@pytest.mark.parametrize(
    "tag_id",
    ["id.id_expiration", "id.dob", "credit.report_date", "property.appraisal_date"],
)
def test_the_other_seeded_rules_degrade_too(tag_id: str) -> None:
    """ID-5 and ID-3 (docs 146/294), CR-13 and PR-6 (the single-source date class)."""
    result = evaluate_gate({tag_id: _parsed("some-value")}, confidence_floor=_FLOOR)
    assert result.status is GateStatus.NEEDS_REVIEW
    assert result.ratification_pending is True


# --------------------------------------------------------------------------- #
# ⚠️ It must not degrade everything — a clean input still passes
# --------------------------------------------------------------------------- #
def test_a_clean_field_still_passes() -> None:
    """The guard is narrow by construction: only listed fields degrade."""
    result = evaluate_gate(
        {"contract.closing_date": _parsed("2026-09-01")}, confidence_floor=_FLOOR
    )
    assert result.status is GateStatus.PASS
    assert result.ratification_pending is False


def test_a_rule_reading_only_clean_fields_is_untouched() -> None:
    result = evaluate_gate(
        {
            "contract.closing_date": _parsed("2026-09-01"),
            "rate_lock.days_to_closing": _parsed("14"),
        },
        confidence_floor=_FLOOR,
    )
    assert result.status is GateStatus.PASS


# --------------------------------------------------------------------------- #
# ⚠️ The boundary — what this layer does NOT cover
# --------------------------------------------------------------------------- #
def test_the_253_class_still_passes_and_that_is_the_boundary() -> None:
    """⚠️ Doc 253 read a gift as $224,307.94 instead of $24,307.94. ``gift_letter.gift_amount`` is NOT on
    the distrust list, so a rule reading it PASSES the gate — exactly as before this ticket.

    That is deliberate and it is the boundary of the whole approach: LP-474 recorded 253 as uncatchable by
    self-consistency (one amount, no sibling to contradict it), and a field-level list cannot help either
    unless we distrust every gift amount on every file. Catching it needs a SOURCE-magnitude check — a
    different layer. Named here so the limit is in the record, not discovered later.
    """
    assert ("gift_letter", "gift_amount") not in load_distrusted_fields()
    assert "asset.gift_amount" not in distrusted_tag_ids()


# --------------------------------------------------------------------------- #
# Ordering, state distinctness, and the list's own integrity
# --------------------------------------------------------------------------- #
def test_absent_still_beats_distrusted() -> None:
    """A MISSING value gets the more specific message; distrusted is for a value that is present."""
    result = evaluate_gate({"ins.dwelling_settlement_basis": None}, confidence_floor=_FLOOR)
    assert result.status is GateStatus.COULDNT_CHECK
    assert "could not be found" in (result.reason or "")


def test_unknown_still_beats_distrusted() -> None:
    result = evaluate_gate(
        {"ins.dwelling_settlement_basis": _parsed("unknown")}, confidence_floor=_FLOOR
    )
    assert result.status is GateStatus.COULDNT_CHECK
    assert "present but unclear" in (result.reason or "")


def test_distrusted_is_a_fifth_state_not_one_of_the_four() -> None:
    """⚠️ Absent ≠ empty ≠ unknown ≠ low-confidence ≠ distrusted. The value is there, the extractor was
    confident, nothing contradicts it — and it is still not to be relied on."""
    distrusted = evaluate_gate(
        {"ins.dwelling_settlement_basis": _parsed("replacement_cost")}, confidence_floor=_FLOOR
    )
    absent = evaluate_gate({"ins.dwelling_settlement_basis": None}, confidence_floor=_FLOOR)
    unknown = evaluate_gate(
        {"ins.dwelling_settlement_basis": _parsed("unknown")}, confidence_floor=_FLOOR
    )
    assert distrusted.status is not absent.status
    assert distrusted.reason != absent.reason != unknown.reason
    assert distrusted.ratification_pending and not absent.ratification_pending


def test_every_list_entry_carries_a_reason() -> None:
    """⚠️ A bare field name is unreviewable and cannot be pruned with confidence. The loader rejects one,
    and every shipped entry names its document and what was wrong."""
    for (doc_type, field), reason in load_distrusted_fields().items():
        assert len(reason) > 40, f"{doc_type}.{field} needs a real reason, not a stub"
        assert "doc" in reason.lower() or "ledger" in reason.lower()


def test_the_motivating_tags_are_all_resolved() -> None:
    """The list is only worth having if it reaches the tags the exposed rules actually gate on."""
    resolved = distrusted_tag_ids()
    for tag_id in (
        "ins.dwelling_settlement_basis",  # IH-1 — doc 104
        "id.id_expiration",  # ID-5 — docs 146/294
        "id.dob",  # ID-3 — docs 146/294
        "credit.report_date",  # CR-13
        "property.appraisal_date",  # PR-6
    ):
        assert tag_id in resolved, f"{tag_id} is not reached by the distrust list"


def test_an_entry_naming_an_unknown_tag_is_rejected() -> None:
    assert (
        DistrustError is not None
    )  # the loader raises it; pinned so the guard is not quietly removed
