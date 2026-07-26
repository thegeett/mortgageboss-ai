"""LP-382 — the employment-date → gap → IN-4 chain (a REGRESSION pin, not a new feature).

LP-382's premise was that IN-4's employment dates aren't extracted. The gate of record REFUTED it: the VOE
extractor already emits start_date/end_date, the tags income.employment_start/end already read them (LP-369
wired the names), and the loan-level producer income.max_employment_gap_days already computes a real gap — so
IN-4 reaches a real verdict. IN-4 is `unknown` on LF-6T3N only because that file has NO VOE (a DATA gap, like
LP-381's derived-4), not because a field is missing.

These pin the working chain so a future VOE-extractor rename can't silently break IN-4's input (the LP-333/369
silent-death class): the tag `data` names ARE the VOE fields; the loan-level producer computes the gap across
documents and ABSTAINS (unknown-with-reason, never a guessed gap) below two dated records; and IN-4 fires /
satisfies / couldnt_checks on the gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.extraction.voe import VOEExtraction
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
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
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _voe(cid: str, *, start: str | None = None, end: str | None = None) -> DocumentEntry:
    fields = {}
    if start is not None:
        fields["start_date"] = _f(start)
    if end is not None:
        fields["end_date"] = _f(end)
    return DocumentEntry(content_id=cid, document_type="voe", fields=fields)


def _snap(docs: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


def _gap_tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("r",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


# --------------------------------------------------------------------------- #
# THE NAME-MATCH — the tag `data` IS the VOE field (the LP-333/369 trap stays closed)
# --------------------------------------------------------------------------- #
def test_employment_date_tags_read_the_voe_extractor_fields() -> None:
    decls = load_declarations()
    voe_fields = set(VOEExtraction().model_dump())
    assert decls["income.employment_start"].data == "start_date" and "start_date" in voe_fields
    assert decls["income.employment_end"].data == "end_date" and "end_date" in voe_fields


# --------------------------------------------------------------------------- #
# THE CHAIN COMPUTES — VOE dates → the loan-level gap (already works, pinned)
# --------------------------------------------------------------------------- #
async def test_gap_computes_across_documents_from_voe_dates() -> None:
    # prior job ended 2024-06-30, current job started 2024-09-15 → a 77-day gap.
    docs = [_voe("voe1", start="2022-01-10", end="2024-06-30"), _voe("voe2", start="2024-09-15")]
    out = await materialize_tags(_snap(docs), only_groups=frozenset())  # parsed + derived, no AI
    gap = out.tags.by_subject["loan"][
        "income.max_employment_gap_days"
    ]  # LOAN-level, matching IN-4's spec
    assert gap.value == "77"


async def test_gap_abstains_below_two_dated_records_never_guesses() -> None:
    # a single dated employment record cannot have a gap → unknown WITH a reason (never a fabricated 0).
    out = await materialize_tags(_snap([_voe("voe1", start="2024-09-15")]), only_groups=frozenset())
    gap = out.tags.by_subject.get("loan", {}).get("income.max_employment_gap_days")
    assert gap is not None and gap.value == "unknown" and "fewer than two" in (gap.reasoning or "")


# --------------------------------------------------------------------------- #
# IN-4 REACHES A REAL VERDICT — given the gap tag (activatable the moment a file carries the dates)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("gap", "expected"),
    [("77", Verdict.FIRED), ("20", Verdict.SATISFIED), ("unknown", Verdict.COULDNT_CHECK)],
)
def test_in4_resolves_on_the_gap(gap: str, expected: Verdict) -> None:
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({"loan": {"income.max_employment_gap_days": _gap_tag(gap)}}),
    )
    assert evaluate_deterministic_rule(load_rule_spec("IN-4"), snap)[0].verdict is expected
