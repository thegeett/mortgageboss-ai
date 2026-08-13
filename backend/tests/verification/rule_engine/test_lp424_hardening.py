"""LP-424 — the hardening batch. Two items implemented (the loader guard; the loan.purpose tag), two reported as
structural findings (the rule_tags drift; the base-rule bars / OC-2-on-an-unscored-tag).

These pin: (item 3) a bar declaring ships:auto on a JUDGMENTAL rule is a load error, and every current bar still
loads; (item 4) loan.purpose materializes as a parsed loan tag (purchase/refinance) with no consumer yet — the
predicate to PC-2/PC-7 is deferred; (item 2) the FINDING — OC-2 is a live BASE rule that rides the UNSCORED
occupancy.consistent_with_signals but ships RATIFY (safe: a human signs each verdict), so it cannot get an
eligible bar and stays a base rule (Geet's call); (item 1) nothing in the eval path reads rule_tags.csv.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.activation_bars import (
    ActivationBarError,
    load_activation_bars,
    parse_bar,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS
from app.verification.rules.kinds import RuleKindName, kind_for
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio


# ======================================================================= #
# ITEM 3 — the loader cross-check: ships:auto on a judgmental rule is a load error
# ======================================================================= #
def test_every_current_bar_still_loads() -> None:
    # The guard must not break startup — every committed bar loads (no current judgmental rule declares auto).
    bars = load_activation_bars()
    assert len(bars) >= 1
    for rid, bar in bars.items():
        kind = kind_for(rid)
        if kind is not None and kind.kind is RuleKindName.JUDGMENTAL:
            assert bar.ships == "ratify"  # every judgmental rule's bar correctly ratifies


def test_ships_auto_on_a_judgmental_rule_is_rejected() -> None:
    # IN-7 is judgmental (ai_judgment) — a bar declaring ships:auto for it is a LIE (the runtime ratifies).
    assert kind_for("IN-7") is not None and kind_for("IN-7").kind is RuleKindName.JUDGMENTAL
    with pytest.raises(ActivationBarError, match="judgmental kind"):
        parse_bar(
            "IN-7",
            {
                "status": "calibratable-now",
                "ships": "auto",
                "threshold": 0.9,
                "validated": False,
                "rationale": "x",
            },
        )


def test_ships_auto_on_a_non_judgmental_rule_is_accepted() -> None:
    # AS-1 is calculative — ships:auto is legitimate (the guard is judgmental-only).
    assert kind_for("AS-1").kind is not RuleKindName.JUDGMENTAL
    bar = parse_bar(
        "AS-1",
        {
            "status": "no-ai-dependency",
            "ships": "auto",
            "threshold": None,
            "validated": False,
            "rationale": "x",
        },
    )
    assert bar.ships == "auto"


# ======================================================================= #
# ITEM 4 — the loan.purpose parsed tag (the predicate is deferred)
# ======================================================================= #
def _loan_snapshot(purpose: str | None) -> Snapshot:
    mismo = {"loan.purpose": Field.present(purpose, source=FieldSource.PARSED)} if purpose else {}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )


def test_loan_purpose_is_a_parsed_loan_tag() -> None:
    decl = load_declarations()["loan.purpose"]
    assert decl.mode is ProductionMode.PARSED and decl.subject == "loan"
    assert decl.allowed_values == ("purchase", "refinance")


async def test_loan_purpose_materializes_from_the_mismo_fact() -> None:
    for purpose in ("purchase", "refinance"):
        mat = await materialize_tags(_loan_snapshot(purpose), only_groups=frozenset())
        assert mat.tags.by_subject["loan"]["loan.purpose"].value == purpose


async def test_loan_purpose_absent_when_no_purpose_stated() -> None:
    # fail-closed: no MISMO loan.purpose → the tag does not materialize (never a fabricated value).
    mat = await materialize_tags(_loan_snapshot(None), only_groups=frozenset())
    assert "loan.purpose" not in mat.tags.by_subject.get("loan", {})


def test_loan_purpose_is_now_consumed_by_pr2() -> None:
    """⚠️ UPDATED AT LP-492, and the cause is the deferral ending — not a weakened assertion.

    LP-424 built `loan.purpose` but deliberately did NOT wire the PC-2/PC-7 predicate: LF-6T3N carries no
    purpose, so those rules would have regressed to couldnt_check, and no refinance fixture existed. It
    was an intentional orphan, and this test pinned that.

    PR-2 (LP-492) is its FIRST consumer, as an applicability predicate — a purchase concept that must not
    run on a refinance. The deferral's own condition is satisfied this time: PR-2 is NEW, so nothing
    regresses, and all three directions are proven (purchase, refinance, and absent → couldnt_check,
    never a silent skip).

    ⚠️ The orphan check is not dropped, it is INVERTED: the tag must now be read by exactly the rule that
    claims it. If PR-2 stops reading it, this fails."""
    from tests.verification.tag_materialization.test_vocabulary_orphans import _live_hard_reads

    assert "loan.purpose" in _live_hard_reads()
    applicability = load_rule_spec("PR-2").deterministic.applicability
    assert applicability is not None
    assert (applicability.tag, applicability.value) == ("loan.purpose", "purchase")


# ======================================================================= #
# ITEM 2 (reported) — OC-2 rides an UNSCORED tag but ships RATIFY (the finding, pinned)
# ======================================================================= #
def test_oc2_is_a_base_rule_riding_an_unscored_tag_but_ratifies() -> None:
    # The finding: OC-2 is LIVE via _BASE_ACTIVE (predates the gate), reads occupancy.consistent_with_signals
    # (AI, UNSCORED — the OC-1 tag), and is JUDGMENTAL so it RATIFIES every verdict (a human signs each) — safe,
    # but it cannot get an eligible bar, which is why item 2 (backfill base-rule bars via the gate) STOPPED:
    # giving OC-2 a bar would make it not-calibratable-yet -> ineligible -> deactivated. Geet's call.
    assert "OC-2" in _BASE_ACTIVE
    assert kind_for("OC-2").kind is RuleKindName.JUDGMENTAL  # -> ratify, never auto (LP-376-B)
    # OC-1's bar (a candidate) reads the SAME tag and records it is unscored (not-calibratable-yet).
    assert load_activation_bars()["OC-1"].status == "not-calibratable-yet"


# ======================================================================= #
# ITEM 1 (reported) — nothing in the eval path reads rule_tags.csv
# ======================================================================= #
def test_eval_path_does_not_read_rule_tags_csv() -> None:
    # The drift in rule_tags.csv is planning-only: the evaluator reads each spec's load_bearing_tags, never the
    # CSV. (Verified structurally in LP-406-2b; pinned here so a future reader cannot re-introduce a CSV read.)
    import inspect

    from app.verification.rule_engine import deterministic, judgment, registry

    for module in (deterministic, judgment, registry):
        src = inspect.getsource(module)
        assert "rule_tags" not in src, module.__name__


# ======================================================================= #
# Equivalence — no rule added/activated
# ======================================================================= #
def test_no_rule_activation_changed() -> None:
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT  # 31 — the batch adds no rule
