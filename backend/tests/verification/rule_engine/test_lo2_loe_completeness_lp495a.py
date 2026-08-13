"""LP-495a — LO-2 (letter-of-explanation completeness).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ THREE STATES THAT MUST NOT COLLAPSE, and the ticket names two of them explicitly:
      "no letter exists"                    -> NOT_APPLICABLE, no finding
      "a letter exists but cannot be read"  -> COULDNT_CHECK
      "a letter exists and is incomplete"   -> NEEDS_REVIEW
All three are proven below, and a test asserts the first two are DIFFERENT verdicts rather than trusting
that they are.

⚠️ THE RULE IS NARROWER THAN THE APPROVED DIRECTIVE ASKED, ON EVIDENCE. The directive said
`explanation_summary` + `referenced_date` + `borrower_signature_present` "across all six LOX types";
those three fields exist on exactly ONE of the eight LOE-family types. Phase A's measured "9/34 · 6/34 ·
7/34" have the whole family as their denominator while their numerator can only come from the 9 base
letters — they are really 9/9, 6/9 and 7/9. A rule built literally on them would have reported 25 of 34
letters incomplete. See LO-2.yaml's header for the per-type field inventory.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_lo2_complete_snapshot,
    build_lo2_incomplete_snapshot,
    build_lo2_no_letter_snapshot,
    build_lo2_odd_signature_snapshot,
    build_lo2_unreadable_snapshot,
    build_lo2_unsigned_snapshot,
)
from app.verification.rule_engine.activation_bars import (
    is_eligible,
    load_activation_bars,
    ratifies_every_finding,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.derived import _LOE_DOC_TYPES
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _one(builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("LO-2",))
    assert len(evaluations) == 1, f"LO-2 is per-document over one document, got {evaluations}"
    return evaluations[0].verdict


async def test_a_complete_letter_is_satisfied() -> None:
    assert await _one(build_lo2_complete_snapshot) is Verdict.SATISFIED


async def test_a_letter_missing_date_and_signature_needs_review() -> None:
    """⚠️ needs_review, NEVER fired. On the one type with the fields, `referenced_date` fills 6/9 and
    `borrower_signature_present` 7/9, so an empty extracted field cannot be distinguished from a field the
    extraction missed — a `fired` verdict would assert a defect on a letter that may state its date on the
    page."""
    assert await _one(build_lo2_incomplete_snapshot) is Verdict.NEEDS_REVIEW


async def test_an_affirmatively_unsigned_letter_needs_review() -> None:
    assert await _one(build_lo2_unsigned_snapshot) is Verdict.NEEDS_REVIEW


async def test_an_unrecognised_signature_answer_couldnt_checks() -> None:
    """⚠️ ADR-376's discipline: an unrecognised value ABSTAINS rather than reading as "unsigned". A
    finding must never rest on a value nobody defined."""
    assert await _one(build_lo2_odd_signature_snapshot) is Verdict.COULDNT_CHECK


async def test_a_letter_that_cannot_be_read_couldnt_checks() -> None:
    """⚠️ "PRESENT BUT UNREADABLE". `credit_explanation_letter` is a real classifier type with NO
    EXTRACTOR AT ALL — the bench records status `no_extractor` for all 4 in the corpus. The letter is in
    the file and its completeness cannot be read from what was extracted."""
    assert await _one(build_lo2_unreadable_snapshot) is Verdict.COULDNT_CHECK


async def test_a_file_with_no_letter_is_not_applicable() -> None:
    """⚠️ "NO LETTER EXISTS" — never a gap. Knowing a letter is OWED needs the list of conditions that
    require one, which is lender- and AUS-driven and enumerated nowhere in the file. That is LO-1's held
    blocker, and `applicability_expected: false` is where it shows through."""
    assert await _one(build_lo2_no_letter_snapshot) is Verdict.NOT_APPLICABLE


async def test_no_letter_and_unreadable_letter_are_different_verdicts() -> None:
    """⚠️ THE TICKET'S EXPLICIT REQUIREMENT, ASSERTED RATHER THAN ASSUMED. These two must not collapse:
    one means nothing is owed, the other means something is present that nobody can check."""
    missing = await _one(build_lo2_no_letter_snapshot)
    unreadable = await _one(build_lo2_unreadable_snapshot)
    assert missing is not unreadable
    assert (missing, unreadable) == (Verdict.NOT_APPLICABLE, Verdict.COULDNT_CHECK)


async def test_a_missing_letter_is_never_satisfied() -> None:
    """⚠️ NEVER SATISFIED ON A MISSING DOCUMENT, BY CODE PATH."""
    snapshot = await materialize_tags(build_lo2_no_letter_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("LO-2",))
    assert all(e.verdict is not Verdict.SATISFIED for e in evaluations)
    assert load_rule_spec("LO-2").deterministic.applicability_expected is False


def test_lo2_can_never_fire() -> None:
    """A spec property: an incomplete letter is surfaced for confirmation, never asserted as a defect."""
    spec = load_rule_spec("LO-2")
    assert spec.deterministic is not None
    verdicts = {outcome.verdict for outcome in spec.deterministic.outcomes}
    assert "fired" not in verdicts
    assert verdicts == {"satisfied", "needs_review", "couldnt_check"}


def test_the_amount_leg_is_absent() -> None:
    """⚠️ DELIBERATE, NOT FORGOTTEN. `referenced_amount` fills 0/34 across the family and 0/9 on the one
    type that declares it — the TI-3/4/5 block. A leg that never resolves cannot be load-bearing, and
    asserting on it would make every letter incomplete."""
    import inspect

    from app.verification.tag_materialization import derived

    source = inspect.getsource(derived._loe_completeness)
    assert "referenced_amount" not in source
    assert "explanation_summary" in source
    assert "referenced_date" in source
    assert "borrower_signature_present" in source


def test_every_loe_document_type_is_in_scope() -> None:
    """⚠️ NONE OF THE EIGHT TYPES IS SILENTLY SKIPPED. The seven without the completeness fields abstain
    (couldnt_check), which is a different answer from being out of scope. If a new LOE type is added to
    the catalog without being added here, it would silently fall outside LO-2 — this is the check."""
    from app.documents.catalog import CATALOG

    catalog_loe = {
        dtype
        for dtype in CATALOG
        if "letter_of_explanation" in dtype
        or dtype in ("credit_explanation_letter", "application_loe")
    }
    assert catalog_loe == set(_LOE_DOC_TYPES), (
        "the LOE document-type set has drifted from the classifier catalog — a letter type outside "
        f"_LOE_DOC_TYPES is invisible to LO-2. catalog-only={catalog_loe - set(_LOE_DOC_TYPES)}, "
        f"scope-only={set(_LOE_DOC_TYPES) - catalog_loe}"
    )


def test_lo2_is_active_eligible_and_does_not_ratify() -> None:
    assert "LO-2" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["LO-2"]
    assert bar.status == "no-ai-dependency", "deterministic — no rate, no ratification"
    assert bar.input_resolves is True
    assert bar.load_bearing_ai_tags == ()
    assert is_eligible(bar)
    assert not ratifies_every_finding("LO-2")


def test_the_signature_field_is_typed_and_the_catalog_kind_is_stale() -> None:
    """⚠️ REPORTED, NOT RE-KINDED. `borrower_signature_present` is a TYPED extractor field, so the
    catalog's "signature (AI for scans)" rationale is stale — LP-487's question answering yes a sixth
    time. Re-kinding needs its own Phase A; rule_kinds.csv stays at 135 rows. This test pins BOTH halves:
    the field really is typed, and the stale row really is still there."""
    from app.ai.extraction.letter_of_explanation import LetterOfExplanationExtraction
    from app.verification.rules.kinds import load_rule_kinds

    assert "borrower_signature_present" in LetterOfExplanationExtraction.model_fields
    kind = load_rule_kinds()["LO-2"]
    assert "AI for scans" in kind.rationale, (
        "the stale catalog rationale was edited — that is a re-kind, and it needs its own Phase A"
    )
