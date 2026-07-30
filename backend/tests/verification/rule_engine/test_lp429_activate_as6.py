"""LP-429 — activate AS-6 (account ownership) on Priya's sign-off.

LP-404 turned AS-6 into the FIRST multi-tag rule delivering Priya's surface-don't-reject ruling (owner=no ->
fired, owner=unknown / co_holder=yes -> needs_review, owner=yes -> satisfied; the middle rows COUNT). Its bar has
been proposed since LP-397 (0.95). LP-429 is Priya's sign-off — validated:true clears the calibratable-now gate.
These tests pin: the flip (validated, eligible, live); the multi-tag PRECEDENT (the bar measures the two routing
tags at 11/11, NOT the reason-only holder_name_variance at 5/11 — ADR-338); the stmt_facts fold-in (the three
tags PRODUCED when AS-6 runs, no LP-384 trap); the middle rows route to needs_review (the document counts); the
5 real LF-6T3N statements stay satisfied (no false flag — AS-6 ships AUTO); and the count/invariant (33 -> 34).
The real-run verdicts are in docs/tickets/LP-429.md (a point-in-time run of the live reasoner — not re-run here).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.rule_engine.activation_bars import (
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
)
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio

_OWNER = UUID("11111111-1111-4111-8111-111111111111")


def _tag(v: str) -> Tag:
    return Tag(
        value=v,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("r",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snap(tags: dict[str, Tag]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="bs",
                    document_type="bank_statement",
                    belongs_to=(BorrowerRef(borrower_id=_OWNER, name="X"),),
                    fields={"account_holder": Field.present("X", source=FieldSource.EXTRACTED)},
                )
            ]
        ),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({"bs": tags}),
    )


def _as6(tags: dict[str, Tag]) -> RuleEvaluation:
    return evaluate_deterministic_rule(load_rule_spec("AS-6"), _snap(tags))[0]


# ======================================================================= #
# The flip — validated, eligible, live
# ======================================================================= #
def test_as6_is_validated_eligible_and_live() -> None:
    bar = load_activation_bars()["AS-6"]
    assert bar.status == "calibratable-now"
    assert bar.threshold == 0.95 and bar.measured_accuracy == 1.0
    assert bar.validated  # LP-429 — Priya signed off
    assert is_eligible(bar)
    assert "AS-6" in ACTIVE_RULE_IDS


def test_active_count_is_34_and_invariant_holds() -> None:
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT == 34
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids())
    assert "AS-6" in eligible_rule_ids()
    assert len(set(ACTIVE_RULE_IDS)) == len(ACTIVE_RULE_IDS)  # no duplicates


# ======================================================================= #
# The multi-tag PRECEDENT (ADR-338) — the bar measures the routing tags, not the reason-only variance
# ======================================================================= #
def test_bar_measures_the_two_routing_tags_not_the_reason_only_variance() -> None:
    lb = load_activation_bars()["AS-6"].load_bearing_ai_tags
    assert lb == ("stmt.owner_matches_borrower", "stmt.non_borrower_co_holder")  # 11/11 each
    assert "stmt.holder_name_variance" not in lb  # 5/11, drives reason text only — not the verdict


def test_as6_ships_auto_and_the_kind_cross_check_passes() -> None:
    bar = load_activation_bars()["AS-6"]
    assert bar.ships == "auto"  # structural presence check
    assert (
        load_rule_spec("AS-6").deterministic is not None
    )  # deterministic -> auto is legal (LP-424)


# ======================================================================= #
# The routing (Priya's ruling) — the middle rows COUNT (needs_review, not fired); no false flag on a match
# ======================================================================= #
def test_owner_no_fires_but_owner_unknown_and_co_holder_route_to_needs_review() -> None:
    # owner=no -> the exclude verdict (fired). owner=unknown and (owner=yes + co_holder=yes) -> needs_review:
    # the statement COUNTS while a human confirms. This IS Priya's surface-don't-reject ruling.
    assert (
        _as6(
            {
                "stmt.owner_matches_borrower": _tag("no"),
                "stmt.holder_name_variance": _tag("surname_differs"),
            }
        ).verdict
        is Verdict.FIRED
    )
    unknown = _as6(
        {
            "stmt.owner_matches_borrower": _tag("unknown"),
            "stmt.holder_name_variance": _tag("nickname"),
        }
    )
    assert unknown.verdict is Verdict.NEEDS_REVIEW  # counts, not excluded
    co_holder = _as6(
        {
            "stmt.owner_matches_borrower": _tag("yes"),
            "stmt.holder_name_variance": _tag("none"),
            "stmt.non_borrower_co_holder": _tag("yes"),
        }
    )
    assert co_holder.verdict is Verdict.NEEDS_REVIEW  # counts, not excluded


def test_a_certain_match_stays_satisfied_no_false_flag() -> None:
    # The FP harm AS-6 exists to avoid, and it ships AUTO: a genuine borrower's own account (owner=yes, no
    # non-borrower co-holder) must be satisfied — never a false 'not the borrower's account'.
    ok = _as6(
        {
            "stmt.owner_matches_borrower": _tag("yes"),
            "stmt.holder_name_variance": _tag("none"),
            "stmt.non_borrower_co_holder": _tag("no"),
        }
    )
    assert ok.verdict is Verdict.SATISFIED


# ======================================================================= #
# The stmt_facts fold-in — the three tags are PRODUCED when AS-6 runs (no LP-384 missing-tag trap)
# ======================================================================= #
async def test_stmt_facts_folds_in_so_the_three_tags_are_produced() -> None:
    # KEYLESS: the fold-in + a stub materialization proves the three tags are PRODUCED at the statement subjects
    # (so at rule time they exist — a couldnt_check would be an honest data reason, never a missing-tag one, the
    # LP-384 trap). The live 4/5/2 routing distribution needs the real model and is the doc's job (LP-429.md).
    from app.services.verification_run import _ai_groups_for_rules, _required_ai_groups
    from app.verification.eval.owner_match_scenarios import build_owner_match_scenario_snapshot
    from app.verification.eval.stubs import stub_materialization_reasoners
    from app.verification.tag_materialization.producer import materialize_tags

    assert _ai_groups_for_rules(("AS-6",)) == frozenset({"stmt_facts"})
    assert "stmt_facts" in _required_ai_groups()  # folds into the LIVE set now that AS-6 is active

    snap = build_owner_match_scenario_snapshot()
    snap = await materialize_tags(
        snap, ai_reasoners=stub_materialization_reasoners(), only_groups=frozenset({"stmt_facts"})
    )
    produced = {
        tid for sub in snap.tags.by_subject.values() for tid in sub if tid.startswith("stmt.")
    }
    assert {
        "stmt.owner_matches_borrower",
        "stmt.holder_name_variance",
        "stmt.non_borrower_co_holder",
    } <= produced
