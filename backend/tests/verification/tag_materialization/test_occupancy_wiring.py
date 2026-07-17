"""OC-2's occupancy tags — wired (LP-371).

OC-2 (LIVE, judgment) reads two load-bearing tags — `occupancy.stated` and
`occupancy.consistent_with_signals` — that were in the vocabulary WITH producers but never declared in
`tag_production.yaml` (the orphan class, LP-366-A/367). Absent → the judgment gate fails-closed → OC-2
couldnt_checked on every file, structurally. This wires both: `occupancy.stated` as a DERIVED MISMO→enum
mapping (a raw parsed passthrough would emit MISMO's out-of-enum 'primary_residence'), and
`occupancy.consistent_with_signals` as the first loan-subject AI group.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import DocumentsSection, MismoSection, Snapshot, TagsSection
from app.verification.tag_materialization.declarations import (
    ProductionMode,
    load_ai_groups,
    load_declarations,
)
from app.verification.tag_materialization.derived import _UNKNOWN, _occupancy_stated


def _field(value: str) -> Field:
    return Field.present(value, source=FieldSource.PARSED)


def _snapshot(mismo: Mapping[str, Field] | None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(dict(mismo)) if mismo is not None else MismoSection.missing(),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# occupancy.stated — the MISMO → enum mapping (derived, not parsed)
# --------------------------------------------------------------------------- #
def test_occupancy_stated_maps_the_mismo_value_to_the_enum() -> None:
    # The mapped keys mirror the OccupancyType StrEnum (primary_residence / second_home / investment),
    # which is the only value space property.occupancy can carry.
    for mismo_value, expected in (
        ("primary_residence", "primary"),
        ("second_home", "second"),
        ("investment", "investment"),
        ("PRIMARY_RESIDENCE", "primary"),  # casefolded
    ):
        value, _ = _occupancy_stated(
            _snapshot({"property.occupancy": _field(mismo_value)}), "loan", None
        )
        assert value == expected, f"{mismo_value} → {value!r}, expected {expected!r}"
        # the mapped value is in the tag's declared enum (never an out-of-enum MISMO value)
        assert value in (load_declarations()["occupancy.stated"].allowed_values or ())


def test_occupancy_stated_abstains_when_occupancy_absent() -> None:
    value, reason = _occupancy_stated(_snapshot({}), "loan", None)
    assert value == _UNKNOWN and "absent" in reason  # never a guessed occupancy


def test_occupancy_stated_abstains_when_mismo_absent() -> None:
    value, _ = _occupancy_stated(_snapshot(None), "loan", None)
    assert value == _UNKNOWN


def test_occupancy_stated_abstains_on_an_unmapped_mismo_value() -> None:
    # A MISMO value not in the map → unknown (never coerced into the enum).
    value, reason = _occupancy_stated(
        _snapshot({"property.occupancy": _field("time_share")}), "loan", None
    )
    assert value == _UNKNOWN and "time_share" in reason


# --------------------------------------------------------------------------- #
# The wiring — OC-2's load-bearing tags now HAVE producers (the orphan is closed)
# --------------------------------------------------------------------------- #
def test_oc2_load_bearing_tags_are_declared() -> None:
    decls = load_declarations()
    spec = load_rule_spec("OC-2")
    assert spec.judgment is not None
    for tag_id in spec.judgment.load_bearing_tags:
        assert tag_id in decls, f"OC-2 load-bearing tag {tag_id} still has no producer declaration"
    assert decls["occupancy.stated"].mode is ProductionMode.DERIVED
    assert decls["occupancy.consistent_with_signals"].mode is ProductionMode.AI


def test_occupancy_is_a_loan_subject_ai_group() -> None:
    group = load_ai_groups()["occupancy"]
    assert (
        group.subject == "loan"
    )  # the first loan-subject AI group (its context = the MISMO facts)
    assert group.tag_ids == ("occupancy.consistent_with_signals",)


def test_oc2_is_live() -> None:
    assert (
        "OC-2" in ACTIVE_RULE_IDS
    )  # the whole point — a live rule that could never verdict, now can


def test_consistent_with_signals_is_calibration_registered() -> None:
    # An abstaining AI tag feeding a LIVE rule must be in _ABSTAINING_DIMENSIONS, else over_abstaining is
    # silently inert and a prompt that couldnt_checks OC-2 on every file (the orphan-class failure) hides.
    from app.verification.eval.calibration import _ABSTAINING_DIMENSIONS

    assert "occupancy.consistent_with_signals" in _ABSTAINING_DIMENSIONS


# --------------------------------------------------------------------------- #
# Fail-closed PRESERVED — absent occupancy → OC-2 couldnt_checks (the gate, no AI call)
# --------------------------------------------------------------------------- #
async def test_oc2_still_couldnt_checks_when_occupancy_absent() -> None:
    # MISMO occupancy absent → occupancy.stated is unknown → the judgment gate fails-closed BEFORE any
    # AI call → couldnt_check with a reason. The fix must not fabricate a verdict where the fact is absent.
    from app.verification.rule_engine.registry import evaluate_rules
    from app.verification.tag_materialization.producer import materialize_tags

    snap = _snapshot({})  # no property.occupancy
    materialized = await materialize_tags(snap, only_groups=frozenset())  # derived only, no AI
    results, _ = await evaluate_rules(materialized, rule_ids=("OC-2",))
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    # the gate names an absent/unknown load-bearing OCCUPANCY tag (not a fabricated verdict)
    assert "occupancy." in (results[0].reasoning or "")
