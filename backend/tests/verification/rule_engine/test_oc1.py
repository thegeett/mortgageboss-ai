"""OC-1 occupancy consistency — the FIRST Bucket 2 rule (LP-406-4), a DETERMINISTIC structural rule
that branches on an already-produced AI enum (occupancy.consistent_with_signals — the same tag LIVE
OC-2 rides), with ZERO new producer and ZERO per-rule Python.

These pin: the satisfy + fire paths; the three D5 states (absent tag / absent MISMO / present-but-
unclear) each couldnt_check; a shaky signal → needs_review; the SUBJECT MATCH (both tags materialize at
the loan subject OC-1 reads — the anti-structural-death check); plain-language reasons (no dotted tag
ids reach a processor); and (LP-495a) that OC-1 is ACTIVE on a self-consistency rate while its AI tag remains UNSCORED —
ratification, not a measurement, is what makes that safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"
_SPEC = load_rule_spec("OC-1")


def _tag(
    value: str, *, confidence: float | None, produced_by: TagProducedBy = TagProducedBy.AI
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=(_LOAN,),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def _occupancy_tags(
    *,
    stated: str | None = "primary",
    consistent: str | None = "yes",
    consistent_conf: float | None = 0.9,
) -> dict[str, Tag]:
    tags: dict[str, Tag] = {}
    if stated is not None:  # derived structural fact — a parsed-style passthrough (confidence None)
        tags["occupancy.stated"] = _tag(stated, confidence=None, produced_by=TagProducedBy.PARSED)
    if consistent is not None:
        tags["occupancy.consistent_with_signals"] = _tag(consistent, confidence=consistent_conf)
    return tags


def _snapshot(tags: dict[str, Tag] | None, *, tags_absent: bool = False) -> Snapshot:
    by_subject = {} if tags is None else {_LOAN: tags}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        tags=TagsSection.missing() if tags_absent else TagsSection.present(by_subject),
    )


def _verdicts(tags: dict[str, Tag] | None, *, tags_absent: bool = False) -> list[Verdict]:
    return [
        r.verdict
        for r in evaluate_deterministic_rule(_SPEC, _snapshot(tags, tags_absent=tags_absent))
    ]


# --------------------------------------------------------------------------- #
# The two verdict paths (D1 / D2)
# --------------------------------------------------------------------------- #


def test_satisfied_when_declarations_agree() -> None:
    # consistent_with_signals == "yes" → the stated occupancy agrees with the other 1003 declarations.
    assert _verdicts(_occupancy_tags(consistent="yes")) == [Verdict.SATISFIED]


def test_fired_when_declarations_conflict() -> None:
    # consistent_with_signals == "no" → a real inconsistency → the rule fires.
    results = evaluate_deterministic_rule(_SPEC, _snapshot(_occupancy_tags(consistent="no")))
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert results[0].how_to_fix  # a fired finding tells the processor how to fix it


# --------------------------------------------------------------------------- #
# D5 — absent ≠ empty ≠ unknown, each a distinct couldnt_check (via the fail-closed gate)
# --------------------------------------------------------------------------- #


def test_unknown_signal_is_couldnt_check() -> None:
    # The AI could not tell (present but "unknown") → couldnt_check, never a guessed pass.
    assert _verdicts(_occupancy_tags(consistent="unknown")) == [Verdict.COULDNT_CHECK]


def test_stated_occupancy_unknown_is_couldnt_check() -> None:
    # MISMO present but no occupancy stated → occupancy.stated == "unknown" → couldnt_check (nothing to
    # be consistent WITH). This is the LF-6T3N state (its MISMO declares no occupancy).
    assert _verdicts(_occupancy_tags(stated="unknown")) == [Verdict.COULDNT_CHECK]


def test_absent_signal_tag_is_couldnt_check() -> None:
    # The AI consistency tag was never produced (absent, not "unknown") → couldnt_check for a distinct
    # reason. This is what a no-AI run yields (the tag is AI-produced).
    assert _verdicts(_occupancy_tags(consistent=None)) == [Verdict.COULDNT_CHECK]


def test_absent_mismo_tags_is_couldnt_check() -> None:
    # No tags layer at all (no 1003/MISMO) → couldnt_check, never a silent pass.
    assert _verdicts(None, tags_absent=True) == [Verdict.COULDNT_CHECK]


def test_low_confidence_signal_is_needs_review() -> None:
    # A shaky AI signal (below the 0.5 floor) → needs_review (a human looks), never an auto verdict.
    assert _verdicts(_occupancy_tags(consistent="no", consistent_conf=0.2)) == [
        Verdict.NEEDS_REVIEW
    ]


# --------------------------------------------------------------------------- #
# The SUBJECT MATCH — the anti-structural-death check (the ID-5 class, bitten 8+ times)
# --------------------------------------------------------------------------- #


def test_read_tags_are_declared_at_the_subject_oc1_enumerates() -> None:
    # OC-1 enumerates the loan subject; BOTH tags it reads must be PRODUCED at that same subject, else the
    # rule couldnt_checks on every file forever (structural death).
    declarations = load_declarations()
    assert _SPEC.subject_enumeration == _LOAN
    for tag_id in _SPEC.deterministic.load_bearing_tags:  # type: ignore[union-attr]
        assert declarations[tag_id].subject == _LOAN, (
            f"{tag_id} is not produced at the loan subject"
        )


async def test_stated_occupancy_materializes_at_loan_on_the_real_fixture() -> None:
    # On the REAL LF-6T3N fixture, occupancy.stated materializes UNDER the loan subject (where OC-1 reads)
    # — proving the producer/consumer subject match end-to-end, not just in the declaration. Its value is
    # "unknown" because that fixture's MISMO states no occupancy (a DATA gap), which is a separate thing
    # from a subject mismatch.
    mat = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())  # parsed+derived
    loan_tags = {} if mat.tags.absent else mat.tags.by_subject.get(_LOAN, {})
    assert "occupancy.stated" in loan_tags  # materialized at the subject OC-1 enumerates


async def test_oc1_couldnt_checks_honestly_on_the_base_fixture() -> None:
    # The base fixture states no occupancy AND does not run the occupancy AI group offline → OC-1
    # couldnt_checks. This is HONEST (a data/fixture gap, like live IN-1's no-stated-income abstain) —
    # NOT a bug and NOT structural death (the tags' subject matches; see the tests above). A fixture that
    # adds property.occupancy + the produced consistency signal would exercise satisfy/fire (a fixture
    # ticket, not this one).
    mat = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# Plain-language reasons (LP-376-C) — no dotted tag ids reach a processor
# --------------------------------------------------------------------------- #


def test_reasons_are_plain_language_no_dotted_tag_ids() -> None:
    for tags in (_occupancy_tags(consistent="yes"), _occupancy_tags(consistent="no")):
        for r in evaluate_deterministic_rule(_SPEC, _snapshot(tags)):
            for tag_id in ("occupancy.stated", "occupancy.consistent_with_signals"):
                assert tag_id not in r.reasoning
            assert "occupancy" in r.reasoning  # still names the concern in words


# --------------------------------------------------------------------------- #
# Written but HELD — not activated (its AI tag is unscored; no Priya bar)
# --------------------------------------------------------------------------- #


def test_oc1_is_activated_on_a_rate_not_a_measurement() -> None:
    # ⚠️ LP-495a — OC-1 WAS held (not-calibratable-yet) and is now ACTIVE on `ratify-pending` (ADR-378).
    # The premise of the old assertion is UNCHANGED and is what this now pins directly: the tag is STILL
    # UNSCORED. A self-consistency rate is NOT a measurement — it says two independent derivations agreed,
    # not that either was right — so `measured_accuracy` stays None and RATIFICATION is the safety
    # substitute. The full activation record is in test_oc1_occupancy_consistency_lp495a.py.
    bar = load_activation_bars()["OC-1"]
    assert bar.status == "ratify-pending"
    assert bar.load_bearing_ai_tags == ("occupancy.consistent_with_signals",)
    assert bar.measured_accuracy is None, "the tag is still unscored — a rate is not a measurement"
    assert bar.self_consistency_rate is not None
    assert is_eligible(bar) is True
    assert "OC-1" in ACTIVE_RULE_IDS
