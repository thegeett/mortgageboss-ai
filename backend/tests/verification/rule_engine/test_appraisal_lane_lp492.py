"""LP-492 — PR-3 · PR-4 · PR-5 · PR-7, and the ratification proof owed from LP-491.

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ n=2 — two appraisals is the whole corpus, and BOTH are ordinary (C4/C3, "as is", condominium). The
finding paths of PR-3, PR-4 and PR-5 have NEVER been observed on real data; they are built against the
guideline. These fixtures prove wiring and direction, not accuracy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.derived import _CONDITION_RATINGS
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_ADDR = {
    "property.address_line": "34 Birch Rd",
    "property.city": "Rivertown",
    "property.state": "IL",
    "property.postal_code": "60000",
}


def _snapshot(**appraisal_fields: str) -> Snapshot:
    fields = {
        "appraised_value": "410000.00",
        "appraisal_effective_date": "2026-06-01",
        **appraisal_fields,
    }
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="ap-1",
                    document_type="appraisal",
                    belongs_to=None,
                    fields={
                        k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in fields.items()
                    },
                )
            ]
        ),
        mismo=MismoSection.present(
            {k: Field.present(v, source=FieldSource.PARSED) for k, v in _ADDR.items()}
        ),
        tags=TagsSection.present({}),
    )


async def _tag(snapshot: Snapshot, tag_id: str) -> str | None:
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    tag = materialized.tags.by_subject.get("ap-1", {}).get(tag_id)
    return None if tag is None else str(tag.value)


# --------------------------------------------------------------------------- #
# ⚠️ PR-5 — the C5 trap. C1-C5 are ELIGIBLE AS IS; only C6 is a finding.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rating", ["C1", "C2", "C3", "C4", "C5"])
async def test_c1_through_c5_normalise_and_are_eligible_as_is(rating: str) -> None:
    """⚠️ C5 IS ELIGIBLE. An earlier draft of the ticket said "C5 and C6 generally require repairs" —
    that is wrong, and encoding a C5 threshold would fire on a common, perfectly eligible property.

    Fannie B4-1.3-06 (page dated 06/04/2025, VERIFIED against the live page this session): "Properties
    with condition ratings C1, C2, C3, C4, and C5 as previously defined are eligible in 'as is'
    condition."
    """
    assert await _tag(_snapshot(condition_rating=rating), "property.condition_rating") == rating
    assert rating.casefold() in _CONDITION_RATINGS
    assert rating != load_rule_spec("PR-5").reference_values.values["ineligible_rating"]


async def test_only_c6_is_the_ineligible_rating() -> None:
    """ "Loans secured by properties with a condition rating of C6 are not eligible for sale to Fannie
    Mae" — and the remedy is a resulting minimum of C5, NOT C4 (Freddie's stricter standard is tier S and
    unbranchable: the agency axis is not a fact on any file, LP-501)."""
    values = load_rule_spec("PR-5").reference_values.values
    assert values["ineligible_rating"] == "C6"
    assert values["minimum_rating_after_repair"] == "C5"
    assert set(values["eligible_as_is_ratings"].split("|")) == {"C1", "C2", "C3", "C4", "C5"}


@pytest.mark.parametrize("raw", ["Condition: excellent", "5", "", "C7"])
async def test_an_unrecognised_rating_abstains(raw: str) -> None:
    """⚠️ ADR-376. Both real appraisals are UAD 2.6-era ("9/2011"); the 3.6 cutover in Nov 2026 may spell
    the rating differently, and an equality against one layout is the `is_disputed` mistake."""
    assert await _tag(_snapshot(condition_rating=raw), "property.condition_rating") == "unknown"


async def test_the_ratings_normalise_case_and_whitespace() -> None:
    assert await _tag(_snapshot(condition_rating=" c4 "), "property.condition_rating") == "C4"


# --------------------------------------------------------------------------- #
# PR-7 — the address compare, and the mailing-address trap
# --------------------------------------------------------------------------- #
async def test_a_matching_address_is_satisfied() -> None:
    snapshot = _snapshot(subject_property_address="34 Birch Road, Rivertown, Illinois 60000-1234")
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(materialized, rule_ids=("PR-7",))
    assert [e.verdict for e in evaluations] == [Verdict.SATISFIED], (
        "the shared canonicalisers must resolve Road/Rd, Illinois/IL and ZIP+4"
    )


async def test_a_different_property_needs_review() -> None:
    """⚠️ WAS `fired`, CHANGED AT THE LP-492 REVIEW. The original argument — "an address is not ambiguous
    the way a name is, so a residual mismatch means a DIFFERENT property" — does not survive the
    canonicaliser it depends on: `_norm_address` deliberately does not canonicalise UNIT DESIGNATORS
    (ADR-325), and BOTH real appraisals in the corpus are condominiums. So "34 Birch Rd Unit 4B" against
    MISMO's "34 Birch Rd" + "#4B" normalises to "... unit 4b" vs "... 4b" and reported two different
    properties for one condo unit. PC-3 shares the canonicaliser and routes its mismatch to needs_review
    for exactly that residue; PR-7 was escalating the identical failure to a hard defect on the most
    common document shape available."""
    snapshot = _snapshot(subject_property_address="9 Elm Street, Othertown, IL 60001")
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(materialized, rule_ids=("PR-7",))
    assert [e.verdict for e in evaluations] == [Verdict.NEEDS_REVIEW]


async def test_a_condo_unit_is_not_reported_as_a_different_property() -> None:
    """⚠️ THE CASE THAT FORCED THE CHANGE. A unit designator rendered two ordinary ways must not read as
    two properties — and with both corpus appraisals being condos, this is the common shape, not a
    corner."""
    snapshot = _snapshot(subject_property_address="34 Birch Rd Unit 4B, Rivertown, IL 60000")
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(materialized, rule_ids=("PR-7",))
    assert [e.verdict for e in evaluations] != [Verdict.FIRED], (
        "a condo unit differing only in its designator must never be a hard defect"
    )


async def test_an_incomplete_file_address_abstains_never_half_matches() -> None:
    """⚠️ THE MAILING-ADDRESS TRAP (LP-407-4 D1). A partial subject address must not be compared — and a
    borrower's current_address is never read, because the parser can fill it with a MAILING address."""
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        documents=_snapshot(subject_property_address="34 Birch Rd, Rivertown IL 60000").documents,
        mismo=MismoSection.present(
            {"property.postal_code": Field.present("60000", source=FieldSource.PARSED)}
        ),
        tags=TagsSection.present({}),
    )
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(materialized, rule_ids=("PR-7",))
    assert [e.verdict for e in evaluations] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# ⚠️ THE RATIFICATION PROOF — for this cohort AND the two owed from LP-491
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("rule_id", "value"),
    [
        ("PR-3", "eligible"),
        ("PR-3", "needs_review"),
        ("PR-4", "complete"),
        ("PR-4", "subject_to"),
        ("PR-5", "eligible_as_is"),
        ("PR-5", "requires_repair"),
    ],
)
async def test_ratify_pending_findings_carry_ratification(rule_id: str, value: str) -> None:
    """⚠️ RATIFICATION IS THE ENTIRE SAFETY SUBSTITUTE for the missing measurement (ADR-378), so it is
    proven through the REAL evaluator — never by calling the mechanism. Both the benign and the adverse
    value are covered, because a rule that ratified only its findings would still auto-assert its passes.
    """
    from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

    async def judge(_context_json: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(
            judgment=RuleJudgment(value=value, confidence=0.9, reasoning="scripted"),
            input_tokens=1,
            output_tokens=1,
            model="stub-pr",
            truncated=False,
        )

    snapshot = await materialize_tags(
        _snapshot(
            condition_rating="C4",
            appraisal_completion_condition="As is",
            property_type="Condominium",
            subject_property_address="34 Birch Rd, Rivertown IL 60000",
        ),
        only_groups=frozenset(),
    )
    evaluations, _tags = await evaluate_rules(
        snapshot, rule_ids=(rule_id,), judgment_reasoners={rule_id: judge}
    )
    asserted = [e for e in evaluations if e.verdict is Verdict.NEEDS_REVIEW]
    assert asserted, f"{rule_id} produced no asserting finding for {value!r}"
    assert all(e.ratification_pending for e in asserted), (
        f"{rule_id} shipped an unmeasured AI judgment with no human in the loop"
    )


def test_every_ratify_pending_rule_in_this_cohort_is_wired() -> None:
    bars = load_activation_bars()
    for rule_id in ("PR-3", "PR-4", "PR-5"):
        bar = bars[rule_id]
        assert bar.status == "ratify-pending"
        assert bar.measured_accuracy is None, "a self-consistency rate is not a measurement"
        assert bar.self_consistency_rate == 1.0 and bar.self_consistency_cases == 2
        assert is_eligible(bar) and rule_id in ACTIVE_RULE_IDS


def test_pr7_carries_no_model_and_needed_no_catalog_edit() -> None:
    """⚠️ PC-3's precedent: a catalog `ai_fuzzy_match` row whose body is a DETERMINISTIC compare, live on
    a no-ai-dependency bar. PR-7 is its twin, so no catalog edit was needed and none was made — the row
    count stays 135."""
    from app.verification.rules.kinds import load_rule_kinds

    assert len(load_rule_kinds()) == 136  # LP-509-D1 +IH-9 (hazard policy expired)
    bar = load_activation_bars()["PR-7"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == () and bar.self_consistency_rate is None
    assert is_eligible(bar) and "PR-7" in ACTIVE_RULE_IDS
