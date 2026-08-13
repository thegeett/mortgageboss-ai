"""LP-433 — the pay-stub-only documentation rule (IN-16), Priya's B12 SEPARATE check.

Her ruling (LP-393-6 → LP-432): a 2-year history cannot rest on pay stubs alone — a W-2 or 1099 is required (the
sibling of IN-15's B14 terminated-employment check). DETERMINISTIC (income.history_documentation, derived
per-borrower from the DOCUMENT-TYPE PRESENCE of the borrower's attributed w2 / 1099 / pay_stub) → no AI, no
calibration (ADR-334). These tests pin every branch (fire / W-2 satisfy / 1099 satisfy / VOE-only n/a), the
reason DISCIPLINE (asks for the document, never accuses the borrower, distinct from IN-6/IN-11/IN-15), per-
borrower isolation, the borrower-subject match, and the activation (no-ai-dependency, 35 -> 36). The live-reasoner
IN-6/IN-11 boundary observation (incl. Priya's labelled B12 borrower) is in docs/tickets/LP-433.md.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    _pay_stub_only_borrower,
    build_pay_stub_only_snapshot,
)
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import (
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio


async def _verdicts() -> dict[str, tuple[Verdict, str]]:
    """IN-16's verdict + reason per borrower on the pay-stub-only scenario (keyless: the derived producer is
    deterministic; the AI stub is irrelevant — IN-16 reads only the derived tag)."""
    snap = await materialize_tags(
        build_pay_stub_only_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    results, _ = await evaluate_rules(snap, rule_ids=("IN-16",))
    by_borrower = {str(_pay_stub_only_borrower(i)): i for i in range(1, 5)}
    return {
        f"B{by_borrower[r.subject_id]}": (r.verdict, r.reasoning)
        for r in results
        if r.subject_id in by_borrower
    }


# ======================================================================= #
# The four branches (Priya's ruling: pay stubs alone are insufficient; a W-2 or 1099 clears)
# ======================================================================= #
async def test_pay_stub_only_fires() -> None:
    verdict, reason = (await _verdicts())["B1"]
    assert verdict is Verdict.FIRED
    assert "pay stubs" in reason.lower()


async def test_a_w2_satisfies() -> None:
    verdict, _ = (await _verdicts())["B2"]
    assert verdict is Verdict.SATISFIED


async def test_a_1099_satisfies_the_or_1099_leg() -> None:
    # Her ruling is "W-2 OR 1099" — a 1099 with no W-2 must satisfy. Easy to build W-2-only by accident, so
    # this leg is pinned explicitly.
    verdict, _ = (await _verdicts())["B3"]
    assert verdict is Verdict.SATISFIED


async def test_voe_only_is_not_applicable_not_a_finding() -> None:
    # D2: no pay stubs (a VOE only) → the rule cannot apply → not_applicable, NEVER a finding on an empty set.
    # Her ruling is NOT broadened to accept a VOE (a VOE-only borrower is out of scope, not satisfied).
    verdict, _ = (await _verdicts())["B4"]
    assert verdict is Verdict.NOT_APPLICABLE


# ======================================================================= #
# The reason DISCIPLINE — asks for the document, never accuses; distinct from IN-6 / IN-11 / IN-15
# ======================================================================= #
async def test_the_fired_reason_asks_for_the_document_never_accuses_the_borrower() -> None:
    _verdict, reason = (await _verdicts())["B1"]
    low = reason.lower()
    assert "a w-2 or 1099 is needed" in low  # it ASKS FOR THE DOCUMENT (a file gap, not a fact)
    for forbidden in ("cannot document", "unable to", "the borrower cannot", "insufficient income"):
        assert forbidden not in low, forbidden  # NEVER a claim about the borrower


async def test_the_reason_and_tags_are_distinct_from_the_three_live_siblings() -> None:
    # The boundary (D6): IN-16 must never surface a finding that duplicates IN-6 (employer-name coverage),
    # IN-11 (whether 2 years exist) or IN-15 (a terminated job). Distinct wording + DISJOINT load-bearing tags.
    _verdict, in16_reason = (await _verdicts())["B1"]
    low = in16_reason.lower()
    assert (
        "history" not in low or "two-year income history" in low
    )  # its own framing, not IN-11's "2-year"
    in16 = load_rule_spec("IN-16").deterministic
    assert in16 is not None
    in16_tags = set(in16.load_bearing_tags)
    for sibling in ("IN-6", "IN-11", "IN-15"):
        sib = load_rule_spec(sibling).deterministic
        assert sib is not None
        assert in16_tags.isdisjoint(sib.load_bearing_tags), sibling  # different tags, no overlap


# ======================================================================= #
# Per-borrower isolation + the subject match (anti-structural-death)
# ======================================================================= #
async def test_per_borrower_isolation_b2_w2_does_not_satisfy_b1() -> None:
    # B1 (pay stubs only) FIRES even though B2 HAS a W-2 — a borrower's documents never speak for another's
    # (belongs_to attribution). If isolation broke, B1 would read as w2_or_1099 (satisfied).
    v = await _verdicts()
    assert v["B1"][0] is Verdict.FIRED and v["B2"][0] is Verdict.SATISFIED


async def test_the_derived_tag_materializes_at_the_borrower_subject() -> None:
    # The subject match (ID-5 anti-structural-death): the per-document w2/1099/pay_stub presence promotes to a
    # per-BORROWER income.history_documentation tag, which the per-borrower rule reads.
    snap = await materialize_tags(
        build_pay_stub_only_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    for i, expected in (
        (1, "pay_stub_only"),
        (2, "w2_or_1099"),
        (3, "w2_or_1099"),
        (4, "no_pay_stubs"),
    ):
        tags = snap.tags.by_subject.get(str(_pay_stub_only_borrower(i)), {})
        assert "income.history_documentation" in tags  # produced at the borrower subject
        assert tags["income.history_documentation"].value == expected


# ======================================================================= #
# Activation — no-ai-dependency, deterministic → live (35 -> 36); IN-6/IN-11/IN-15 untouched
# ======================================================================= #
def test_in16_is_active_and_the_invariant_holds() -> None:
    bar = load_activation_bars()["IN-16"]
    assert bar.status == "no-ai-dependency" and bar.threshold is None
    assert bar.ships == "auto" and not bar.load_bearing_ai_tags  # deterministic, no AI tag
    assert is_eligible(bar) and "IN-16" in ACTIVE_RULE_IDS
    assert (
        len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT == 53
    )  # LP-447 +IH-1; LP-485 +CL-1/CR-13/PR-6
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids())


def test_the_live_siblings_are_untouched() -> None:
    assert {"IN-6", "IN-11", "IN-15"} <= set(ACTIVE_RULE_IDS)
