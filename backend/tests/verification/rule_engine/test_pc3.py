"""PC-3 — property address matches (LP-407-4): the last blocker-free rule. A DETERMINISTIC rule that branches
on the derived property.address_normalized_match enum (a contract-vs-MISMO subject-address compare using the
consistency normalizers). No AI, no threshold → it activates (29 → 30). A mismatch routes to needs_review
(ADR-325 — the deterministic normalizers cannot expand abbreviations, so a possible variant is surfaced for a
human, never auto-fired as a "different property").

These pin: the branches (match → satisfied; mismatch / abbreviation-variant → needs_review; absent → couldnt_check);
THE MAILING-ADDRESS TRAP (only a mailing address → couldnt_check, never a comparison against it); the multi-contract
abstain (→ unknown); both addresses in the tag provenance; the subject match; the scenarios are standalone (95…,
NOT LF-6T3N); and PC-3 is LIVE + eligible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_address_abbrev_snapshot,
    build_address_mailing_only_snapshot,
    build_address_match_snapshot,
    build_address_mismatch_snapshot,
    build_address_unit_variant_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentsSection, MismoSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"
_TAG = "property.address_normalized_match"
_SPEC = load_rule_spec("PC-3")


def _tag(value: str, produced_by: TagProducedBy = TagProducedBy.DERIVED) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=(_LOAN,),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def _snapshot(match: str | None, purpose: str | None = "purchase") -> Snapshot:
    # LP-509-A5: PC-3 is scoped purchase-only, so a case that expects it to RUN states a purchase.
    tags: dict[str, dict[str, Tag]] = {}
    if purpose is not None:
        tags[_LOAN] = {"loan.purpose": _tag(purpose, TagProducedBy.PARSED)}
    if match is not None:
        tags.setdefault(_LOAN, {})[_TAG] = _tag(match)
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present(tags),
    )


def _evaluate(match: str | None) -> list[RuleEvaluation]:
    return evaluate_deterministic_rule(_SPEC, _snapshot(match))


# --------------------------------------------------------------------------- #
# The branches — "no" → needs_review (NOT fired), the ADR-325 routing
# --------------------------------------------------------------------------- #
def test_match_satisfies() -> None:
    assert [r.verdict for r in _evaluate("yes")] == [Verdict.SATISFIED]


def test_mismatch_routes_to_needs_review_not_fired() -> None:
    results = _evaluate("no")
    assert [r.verdict for r in results] == [Verdict.NEEDS_REVIEW]
    assert (
        results[0].verdict is not Verdict.FIRED
    )  # ADR-325: never auto-fired on the abbreviation residue
    assert results[0].how_to_fix


def test_unknown_is_couldnt_check() -> None:
    assert [r.verdict for r in _evaluate("unknown")] == [Verdict.COULDNT_CHECK]


def test_absent_tag_is_couldnt_check() -> None:
    assert [r.verdict for r in _evaluate(None)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# The subject match (anti-structural-death)
# --------------------------------------------------------------------------- #
def test_tag_is_produced_at_the_subject_pc3_reads() -> None:
    assert _SPEC.subject_enumeration == _LOAN
    assert load_declarations()[_TAG].subject == _LOAN


# --------------------------------------------------------------------------- #
# On the REAL address scenarios (LP-407-4's fixtures — NOT LF-6T3N)
# --------------------------------------------------------------------------- #
async def _materialize(snap: Snapshot) -> Snapshot:
    return await materialize_tags(snap, only_groups=frozenset())  # parsed + derived, no AI


async def test_match_scenario_satisfies_and_names_both_addresses() -> None:
    mat = await _materialize(build_address_match_snapshot())
    tag = mat.tags.by_subject[_LOAN][_TAG]
    assert str(tag.value) == "yes"
    # both addresses in the tag provenance (an enum branch cannot interpolate an operand — the AS-8 pattern)
    assert "789 Birchwood Ln, Springfield IL 62711" in tag.reasoning
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.SATISFIED]


async def test_mismatch_scenario_needs_review() -> None:
    mat = await _materialize(build_address_mismatch_snapshot())
    tag = mat.tags.by_subject[_LOAN][_TAG]
    assert str(tag.value) == "no"
    assert "789 Birchwood" in tag.reasoning and "456 Oak Street" in tag.reasoning
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.NEEDS_REVIEW]


async def test_abbreviation_variant_now_resolves_to_satisfied() -> None:
    # LP-407-4 review: the former FP case (same property; "Lane"/"Illinois"/ZIP+4 on the contract vs
    # "Ln"/"IL"/ZIP5 in the file) is now RESOLVED by the deterministic address canonicalizer (_norm_address:
    # street suffixes + state names + ZIP+4→ZIP5) → PC-3 SATISFIES, instead of the needs_review noise it used to
    # emit on this common same-property rendering.
    mat = await _materialize(build_address_abbrev_snapshot())
    assert str(mat.tags.by_subject[_LOAN][_TAG].value) == "yes"
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.SATISFIED]


async def test_unit_designator_residue_still_needs_review_never_fired() -> None:
    # THE RESIDUE the canonicalizer deliberately leaves (ADR-325 survives): same property, "Apt 2" vs "Unit 2".
    # Unit designators are NOT canonicalized (too varied to unify safely), so it still reads as a mismatch →
    # NEEDS_REVIEW (a human clears it), NEVER a false "different property" FIRING.
    mat = await _materialize(build_address_unit_variant_snapshot())
    assert str(mat.tags.by_subject[_LOAN][_TAG].value) == "no"
    results = evaluate_deterministic_rule(_SPEC, mat)
    assert [r.verdict for r in results] == [Verdict.NEEDS_REVIEW]
    assert results[0].verdict is not Verdict.FIRED


async def test_mailing_only_couldnt_checks_never_compares_the_mailing_address() -> None:
    # THE MAILING-ADDRESS TRAP (D1): the file has a borrower mailing address but NO subject-property address.
    # PC-3 must COULDNT_CHECK — never compare the contract against the mailing address as a substitute.
    mat = await _materialize(build_address_mailing_only_snapshot())
    tag = mat.tags.by_subject[_LOAN][_TAG]
    assert str(tag.value) == "unknown"
    assert "mailing" in tag.reasoning  # the recipe names why (no complete subject-property address)
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.COULDNT_CHECK]


async def test_lf6t3n_couldnt_checks_no_mismo_subject_address() -> None:
    # LF-6T3N has no MISMO subject-property address (LP-414 added only property.purchase_price) → PC-3
    # couldnt_checks. An honest absence; the branches are proven on the address scenarios above.
    mat = await _materialize(build_lf6t3n_snapshot())
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# _norm_address — the deterministic canonicalizer (LP-407-4 review). It must unify true synonyms of ONE token
# while NEVER merging two genuinely different addresses (a false SATISFIED is the dangerous direction).
# --------------------------------------------------------------------------- #
def test_norm_address_canonicalizes_synonyms_to_equal() -> None:
    from app.verification.tag_materialization.derived import _norm_address

    # street suffix + full state name + ZIP+4 all fold to the file's terse rendering
    assert _norm_address("789 Birchwood Lane, Springfield Illinois 62711-0142") == _norm_address(
        "789 Birchwood Ln Springfield IL 62711"
    )
    # a multi-word state (phrase-replaced before tokenizing, so "north" is not mis-read as a directional)
    assert _norm_address("5 Elm St, Raleigh North Carolina 27601") == _norm_address(
        "5 Elm St Raleigh NC 27601"
    )


def test_norm_address_never_merges_distinct_addresses() -> None:
    from app.verification.tag_materialization.derived import _norm_address

    # different house number / street / suffix / city / state must stay DISTINCT after canonicalization
    base = _norm_address("789 Birchwood Ln Springfield IL 62711")
    assert _norm_address("788 Birchwood Ln Springfield IL 62711") != base  # house number
    assert _norm_address("789 Oak Ln Springfield IL 62711") != base  # street name
    assert _norm_address("789 Birchwood Ave Springfield IL 62711") != base  # suffix stays distinct
    assert _norm_address("789 Birchwood Ln Riverton IL 62711") != base  # city
    assert _norm_address("789 Birchwood Ln Springfield IA 62711") != base  # state
    # ZIP5 truncation does not collapse two different ZIP+4s of DIFFERENT base ZIPs
    assert _norm_address("789 Birchwood Ln Springfield IL 62711-0142") != _norm_address(
        "789 Birchwood Ln Springfield IL 62799-0142"
    )


# --------------------------------------------------------------------------- #
# Live + eligible — no AI dependency, no threshold
# --------------------------------------------------------------------------- #
def test_pc3_is_live_and_eligible_no_ai_dependency() -> None:
    assert "PC-3" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["PC-3"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == () and bar.threshold is None
    assert bar.input_resolves is True and is_eligible(bar) is True
