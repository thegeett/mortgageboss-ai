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
from app.verification.rules import distrust
from app.verification.rules.distrust import (
    DistrustError,
    distrusted_tag_ids,
    load_distrusted_fields,
)
from app.verification.rules.specs import load_rule_spec
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


def _gated_tags(rule_id: str) -> set[str]:
    """Every tag id a rule actually hands to the gate — the only thing the distrust check can match."""
    spec = load_rule_spec(rule_id)
    tags: set[str] = set()
    for block in (spec.deterministic, spec.judgment):
        if block is not None:
            tags |= set(getattr(block, "gated_tags", ()) or ())
            tags |= set(getattr(block, "load_bearing_tags", ()) or ())
    if spec.consistency is not None:
        tags.add(spec.consistency.gather_tag)
    return tags


@pytest.mark.parametrize("rule_id", ["IH-1", "ID-5", "ID-3", "CR-13", "PR-6"])
def test_each_protected_rule_actually_gates_on_a_distrusted_tag(rule_id: str) -> None:
    """⚠️ THE ASSERTION THAT WAS MISSING, and why the gap shipped green.

    The previous version called ``evaluate_gate`` with a HAND-BUILT map keyed by the parsed tag ids —
    but no rule ever passes those to the gate. ID-5 gates on ``id.borrower_id_expiration``, CR-13 on
    ``credit.report_age_months_at_closing``, PR-6 on ``property.appraisal_age_months_at_closing``: all
    DERIVED from the distrusted field, none of them the parsed tag. So the test asserted the mechanism
    in isolation and passed while the wiring reached only 1 of the 5 rules it claimed to protect.

    This intersects each rule's REAL gated tags with the distrust list, which is the only thing that
    proves protection.
    """
    reached = _gated_tags(rule_id) & set(distrusted_tag_ids())
    assert reached, (
        f"{rule_id} is documented as distrust-protected but none of its gated tags "
        f"{sorted(_gated_tags(rule_id))} is on the distrust list — name the DERIVED tag it gates on in "
        "distrusted_fields.yaml's `tags:` section"
    )


def test_every_distrusted_field_reaches_a_rule() -> None:
    """No entry may be inert. A distrusted tag that no active rule gates on protects nothing, and the
    file's own comments promise the opposite — so an unreachable entry is a silent lie, not dead weight."""
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

    gated = {t for rule_id in ACTIVE_RULE_IDS for t in _gated_tags(rule_id)}
    unreachable = sorted(set(distrusted_tag_ids()) - gated)
    # The PARSED upstream tags are legitimately unreached — their DERIVED consumers carry the protection.
    upstream = {"id.id_expiration", "credit.report_date", "property.appraisal_date"}
    assert not (set(unreachable) - upstream), (
        f"distrusted tags no active rule gates on: {sorted(set(unreachable) - upstream)}"
    )


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


def test_an_entry_naming_an_unknown_tag_is_rejected(tmp_path, monkeypatch) -> None:
    """⚠️ The previous version asserted ``DistrustError is not None`` — true of any imported name, so
    deleting the guard it claims to pin left the suite green. This exercises the guard."""
    bogus = tmp_path / "distrusted_fields.yaml"
    bogus.write_text("tags:\n  not.a.real.tag: because reasons\n", encoding="utf-8")
    monkeypatch.setattr(distrust, "_PATH", bogus)
    for fn in (distrust._document, distrust.load_distrusted_fields, distrust.distrusted_tag_ids):
        fn.cache_clear()
    try:
        with pytest.raises(DistrustError, match="no such declared tag"):
            distrust.distrusted_tag_ids()
    finally:
        monkeypatch.undo()
        for fn in (
            distrust._document,
            distrust.load_distrusted_fields,
            distrust.distrusted_tag_ids,
        ):
            fn.cache_clear()


def test_a_field_entry_naming_an_unknown_field_is_rejected(tmp_path, monkeypatch) -> None:
    """The symmetric guard (reported finding): ``fields:`` used to DROP an unmatched entry silently while
    ``tags:`` raised, so a typo or an extractor rename disabled protection with nothing failing."""
    bogus = tmp_path / "distrusted_fields.yaml"
    bogus.write_text(
        "fields:\n  homeowners_insurance:\n    no_such_field_at_all: because reasons\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(distrust, "_PATH", bogus)
    for fn in (distrust._document, distrust.load_distrusted_fields, distrust.distrusted_tag_ids):
        fn.cache_clear()
    try:
        with pytest.raises(DistrustError, match="no schema spec declares that field"):
            distrust.load_distrusted_fields()
    finally:
        monkeypatch.undo()
        for fn in (
            distrust._document,
            distrust.load_distrusted_fields,
            distrust.distrusted_tag_ids,
        ):
            fn.cache_clear()


def test_a_non_mapping_root_raises_distrust_error(tmp_path, monkeypatch) -> None:
    """Reported finding: the second read did not guard the root, so a list root raised AttributeError
    from inside evaluate_gate rather than a DistrustError."""
    bogus = tmp_path / "distrusted_fields.yaml"
    bogus.write_text("- not\n- a mapping\n", encoding="utf-8")
    monkeypatch.setattr(distrust, "_PATH", bogus)
    for fn in (distrust._document, distrust.load_distrusted_fields, distrust.distrusted_tag_ids):
        fn.cache_clear()
    try:
        with pytest.raises(DistrustError, match="top level must be a mapping"):
            distrust.distrusted_tag_ids()
    finally:
        monkeypatch.undo()
        for fn in (
            distrust._document,
            distrust.load_distrusted_fields,
            distrust.distrusted_tag_ids,
        ):
            fn.cache_clear()
