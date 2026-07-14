"""The tag object model + the two-layer snapshot shape (LP-312).

Covers the §3D tag contract (value incl. "unknown"; nullable confidence; source_facts as
content_ids; the enums; frozen), and the additive tags layer: a Snapshot carries a
present-empty `tags` section and a `from_tag` on calc breakdown lines, all round-tripping
losslessly at snapshot_version 3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.verification.snapshot.model import (
    SNAPSHOT_VERSION,
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from pydantic import ValidationError

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _tag(**kw: Any) -> Tag:
    base: dict[str, Any] = {
        "value": "no",
        "confidence": 0.62,
        "reasoning": "no matching payroll within window",
        "source_facts": ("txn0000000000abcd",),
        "produced_by": TagProducedBy.AI,
        "tag_role": TagRole.STRUCTURAL_FACT,
        "tag_version": 1,
        "stage": TagStage.B,
    }
    base.update(kw)
    return Tag(**base)


def test_tag_constructs_with_the_full_contract() -> None:
    tag = _tag()
    assert tag.value == "no"
    assert tag.confidence == 0.62
    assert tag.source_facts == ("txn0000000000abcd",)
    assert tag.produced_by is TagProducedBy.AI
    assert tag.tag_role is TagRole.STRUCTURAL_FACT
    assert tag.stage is TagStage.B
    assert tag.tag_version == 1


def test_tag_value_domain_includes_unknown_and_confidence_may_be_null() -> None:
    # "unknown" is always a legal value; a parsed tag carries no invented confidence.
    parsed = _tag(value="unknown", confidence=None, produced_by=TagProducedBy.PARSED)
    assert parsed.value == "unknown"
    assert parsed.confidence is None
    # value is any JSON value (number, bool, null all fine).
    assert _tag(value=42).value == 42
    assert _tag(value=None).value is None


def test_tag_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        _tag(confidence=1.5)
    with pytest.raises(ValidationError):
        _tag(confidence=-0.1)


def test_tag_rejects_empty_source_fact_id() -> None:
    with pytest.raises(ValidationError):
        _tag(source_facts=("txn_ok", ""))


def test_tag_is_frozen() -> None:
    tag = _tag()
    with pytest.raises(ValidationError):
        tag.value = "yes"


def test_tag_round_trips_losslessly() -> None:
    tag = _tag(source_facts=("txn0000000000abcd", "doc0000000000abcd"))
    assert Tag.model_validate_json(tag.model_dump_json()) == tag


# --------------------------------------------------------------------------- #
# The tags layer
# --------------------------------------------------------------------------- #


def test_tags_section_defaults_present_empty() -> None:
    section = TagsSection()
    assert section.is_present and section.by_subject == {}
    assert not section.absent


def test_tags_section_absent_carries_no_tags() -> None:
    assert TagsSection.missing().absent is True
    assert TagsSection.failed("production timed out").reason == "production timed out"
    with pytest.raises(ValidationError):
        TagsSection(absent=True, by_subject={"txn1": {"txn.is_money_in": _tag()}})


def test_snapshot_has_empty_tags_layer_by_default() -> None:
    snap = Snapshot(loan_file_id=uuid4(), run_id=uuid4(), created_at=_WHEN)
    assert snap.snapshot_version == SNAPSHOT_VERSION == 3
    assert snap.tags.is_present and snap.tags.by_subject == {}


def test_two_layer_snapshot_round_trips_including_empty_tags_and_from_tag() -> None:
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        calculations=CalculationsSection.present(
            dti=CalculationEntry(
                value={"back_end_dti": "43.10"},
                breakdown=[
                    CalcBreakdownLine(
                        key="income.1",
                        label="Base",
                        amount="6000",
                        source="stated",
                        from_tag=None,  # populated by LP-318; null now
                    )
                ],
            )
        ),
    )
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back == snap
    assert back.snapshot_version == 3
    assert back.tags.is_present and back.tags.by_subject == {}  # present-empty survives
    line = back.calculations.dti.breakdown[0]  # type: ignore[union-attr]
    assert line.from_tag is None  # from_tag round-trips


def test_from_tag_value_round_trips_when_set() -> None:
    line = CalcBreakdownLine(
        key="ltv.value",
        label="Value",
        amount="500000",
        source="extracted",
        from_tag="txnabc123def456",
    )
    assert (
        CalcBreakdownLine.model_validate_json(line.model_dump_json()).from_tag == "txnabc123def456"
    )


def test_populated_tags_layer_round_trips() -> None:
    """Even though production is out of scope, the shape must carry tags losslessly."""
    section = TagsSection.present(
        {"txn0000000000abcd": {"txn.is_money_in": _tag(value="yes", stage=TagStage.A)}}
    )
    snap = Snapshot(loan_file_id=uuid4(), run_id=uuid4(), created_at=_WHEN, tags=section)
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back == snap
    assert back.tags.by_subject["txn0000000000abcd"]["txn.is_money_in"].value == "yes"
