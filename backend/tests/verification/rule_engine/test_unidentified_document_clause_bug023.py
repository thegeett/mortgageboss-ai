"""bug-023 — ID-3 and ID-8 asked for documents the file was already holding.

The other half of bug-020. LF-XMB2 carries four documents the classifier could not identify, including
the borrower's driver's licence, and ID-3 still said "only one document in the file shows the date of
birth" — true of what could be READ, not of what the file HOLDS, because a gather skips an unclassified
document exactly as if it were absent.

The clause belongs in the MESSAGE and nowhere else: `requested_documents` is borrower-facing (Phase 4
shows it verbatim) and deliberately names no document type, so "identify the untyped files" — an
instruction to the processor — must never leak into it.
"""

# bug-023 review — ID-8'S SENTENCE IS UNCONDITIONAL SPEC TEXT, so it must be true of a file with NO
# unidentified documents too. Measured on staging: ID-8 carries 9 needs_review findings across 8 files
# and only 5 of them sit on a file holding any untyped document — so the imperative form ("check the
# file's unidentified documents first") was wrong on 4 of 9 live findings, telling a processor to go and
# look at something that is not there. A judgment rule's guidance cannot read the snapshot (its
# templates interpolate `reasoned_over` tags only), so the fix is grammatical rather than a count: a
# CONDITIONAL clause is true either way.
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.consistency import _unidentified_note, evaluate_consistency_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import unclassified_documents

pytestmark = pytest.mark.anyio

_B = uuid4()


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _doc(content_id: str, document_type: str | None) -> DocumentEntry:
    return DocumentEntry(
        content_id=content_id,
        document_type=document_type,
        belongs_to=(BorrowerRef(borrower_id=_B, name="fixture"),),
    )


def _snap(entries: list[DocumentEntry], tags: dict[str, dict[str, Tag]] | None = None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(tags or {}),
    )


# --------------------------------------------------------------------------- #
# The shared predicate — one definition, because it was becoming several
# --------------------------------------------------------------------------- #
def test_both_unclassified_shapes_count() -> None:
    """`classification.py` writes the "unknown" slug when the model is unsure AND when the call never
    completed; a document can also carry no type at all. Both are unidentified."""
    snap = _snap([_doc("slug", "unknown"), _doc("none", None), _doc("typed", "pay_stub")])

    assert unclassified_documents(snap) == ("slug", "none")


def test_an_absent_documents_section_names_nothing() -> None:
    """A build that could not look has not found untyped files — the honest answer is none, not a claim
    about a file it never read."""
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.failed("degraded"),
        tags=TagsSection.present({}),
    )

    assert unclassified_documents(snap) == ()


def test_the_note_is_empty_when_every_document_is_identified() -> None:
    assert _unidentified_note(_snap([_doc("p1", "pay_stub")])) == ""


def test_the_note_counts_the_unidentified_documents() -> None:
    note = _unidentified_note(
        _snap([_doc("a", None), _doc("b", "unknown"), _doc("p1", "pay_stub")])
    )

    assert "2 document(s)" in note and "identify those first" in note


# --------------------------------------------------------------------------- #
# ID-3 — through the real rule
# --------------------------------------------------------------------------- #
async def _id3(entries: list[DocumentEntry], tags: dict[str, dict[str, Tag]]):
    results = await evaluate_consistency_rule(load_rule_spec("ID-3"), _snap(entries, tags))
    assert results, "ID-3 produced no evaluation — the fixture does not reach the rule"
    return results[0]


async def test_id3_says_the_second_source_may_be_sitting_untyped() -> None:
    """THE LF-XMB2 SHAPE: one readable source, and the licence that would have been the second sitting
    in the file unidentified."""
    result = await _id3(
        [_doc("dl", "unknown"), _doc("ps", "pay_stub")],
        {"ps": {"id.dob": _tag("1990-04-02")}},
    )

    assert result.verdict is Verdict.COULDNT_CHECK
    assert "not identified yet" in result.reasoning
    assert "1 document(s)" in result.reasoning


async def test_id3_says_nothing_extra_when_the_file_is_fully_identified() -> None:
    result = await _id3(
        [_doc("ps", "pay_stub"), _doc("w2", "w2")],
        {"ps": {"id.dob": _tag("1990-04-02")}},
    )

    assert result.verdict is Verdict.COULDNT_CHECK
    assert "not identified yet" not in result.reasoning


async def test_the_borrower_facing_ask_never_carries_the_clause() -> None:
    """⚠️ THE LINE THIS TICKET MUST NOT CROSS. `requested_documents` is shown to the BORROWER verbatim
    and names no document type on purpose. "Identify the untyped files" is our filing, not theirs —
    it belongs in the processor's message only."""
    result = await _id3(
        [_doc("dl", "unknown"), _doc("ps", "pay_stub")],
        {"ps": {"id.dob": _tag("1990-04-02")}},
    )

    assert result.requested_documents
    for ask in result.requested_documents:
        assert "identified" not in ask and "identify" not in ask.lower()
