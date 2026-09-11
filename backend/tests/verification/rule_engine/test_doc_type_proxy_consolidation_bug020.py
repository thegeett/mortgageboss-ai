"""bug-020 — four untyped documents became five findings.

LF-XMB2 carries four documents the classifier could not identify. They produced the consolidated
UNIDENTIFIED-DOCUMENTS finding naming all four — and then four more LO-2 rows, one per document, each
asking whether that same file is a letter of explanation.

LO-2 cannot scope itself on `document.document_type`: the applicability DSL has only eq/ne and its scope
is eight document types. It reads `loe.is_explanation_letter`, which a recipe computes from the type
alone — "unknown" for an unclassified document, fail-closed so an untyped file is surfaced rather than
declared "not a letter". `undetermined_by_document_type` then asked whether the abstention's cause was
`document.document_type` itself, and a proxy is not that tag, so every untyped document kept its own row.

What must NOT change: a proxy abstaining on a document whose type IS known stays its own finding — it
failed for some other reason, and folding it into "identify these documents" would send a processor
after the wrong thing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.rule_engine.applicability import undetermined_by_document_type
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import DOC_TYPE_PROXY_TAGS, DOC_TYPE_TAG, TagCondition
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_LOE_PREDICATE = TagCondition(tag="loe.is_explanation_letter", op="eq", value="yes")


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


# --------------------------------------------------------------------------- #
# The predicate — a proxy for the document type IS the document type
# --------------------------------------------------------------------------- #
def test_the_loe_proxy_is_declared_as_a_document_type_proxy() -> None:
    """The set is the contract. LO-2's predicate must be in it, or the consolidation below is an
    accident of the tag id rather than a declared property."""
    assert "loe.is_explanation_letter" in DOC_TYPE_PROXY_TAGS


def test_a_proxy_abstention_on_an_untyped_document_consolidates() -> None:
    """THE LF-XMB2 SHAPE: the document has no classified type, so the proxy cannot resolve and the
    remedy is the one the consolidated finding already states."""
    subject_tags = {
        DOC_TYPE_TAG: _tag("unknown"),
        "loe.is_explanation_letter": _tag("unknown"),
    }

    assert undetermined_by_document_type([_LOE_PREDICATE], subject_tags) is True


def test_a_proxy_abstention_on_a_TYPED_document_does_not_consolidate() -> None:
    """The half that keeps it honest. The type is known, so whatever stopped the proxy is a different
    problem — "identify these documents" would be the wrong instruction."""
    subject_tags = {
        DOC_TYPE_TAG: _tag("bank_statement"),
        "loe.is_explanation_letter": _tag("unknown"),
    }

    assert undetermined_by_document_type([_LOE_PREDICATE], subject_tags) is False


def test_an_absent_document_type_counts_as_unidentified() -> None:
    """A document whose type tag never materialized is as unidentified as one typed "unknown"."""
    assert (
        undetermined_by_document_type(
            [_LOE_PREDICATE], {"loe.is_explanation_letter": _tag("unknown")}
        )
        is True
    )


def test_a_tag_that_is_not_a_proxy_never_consolidates() -> None:
    """AS-1's direction is not a document-type question: its remedy is to read the statement, not to
    identify a file. Only declared proxies fold in."""
    predicate = TagCondition(tag="txn.is_money_in", op="eq", value="in")
    subject_tags = {DOC_TYPE_TAG: _tag("unknown"), "txn.is_money_in": _tag("unknown")}

    assert undetermined_by_document_type([predicate], subject_tags) is False


def test_scope_false_still_wins_outright_over_a_proxy() -> None:
    """LP-640's precedence is untouched: a definitely-out-of-scope predicate means there is no
    abstention to consolidate, wherever it sits in the conjunction."""
    out_of_scope = TagCondition(tag="program.type", op="eq", value="fha")
    subject_tags = {
        DOC_TYPE_TAG: _tag("unknown"),
        "loe.is_explanation_letter": _tag("unknown"),
        "program.type": _tag("conventional"),  # definitely not FHA
    }

    assert undetermined_by_document_type([_LOE_PREDICATE, out_of_scope], subject_tags) is False


# --------------------------------------------------------------------------- #
# LO-2 end to end — four untyped documents, one queue item
# --------------------------------------------------------------------------- #
def test_lo2_over_four_untyped_documents_consolidates() -> None:
    """Through the real spec and the real evaluator: every LO-2 row must be attributed to the
    unidentified documents, which is what lets the persistence layer collapse them into one."""
    from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
    from app.verification.rules.specs import load_rule_spec

    cids = ("dl", "ead", "pa3", "chime")
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id=cid, document_type="unknown") for cid in cids]
        ),
        tags=TagsSection.present(
            {cid: {"loe.is_explanation_letter": _tag("unknown")} for cid in cids}
        ),
    )

    results = evaluate_deterministic_rule(load_rule_spec("LO-2"), snapshot)

    assert len(results) == len(cids)
    assert all(r.verdict is Verdict.COULDNT_CHECK for r in results), "still blocked, never cleared"
    assert all(r.unidentified_document for r in results), (
        "each row must be attributed to the unidentified document, so the persistence layer folds "
        "them into the one consolidated finding instead of four separate queue items"
    )


def test_lo2_on_a_typed_non_letter_is_not_attributed_to_an_unidentified_document() -> None:
    """A pay stub is confidently not a letter — not_applicable, and nothing to consolidate."""
    from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
    from app.verification.rules.specs import load_rule_spec

    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id="p1", document_type="pay_stub")]
        ),
        tags=TagsSection.present({"p1": {"loe.is_explanation_letter": _tag("no")}}),
    )

    results = evaluate_deterministic_rule(load_rule_spec("LO-2"), snapshot)

    assert all(not r.unidentified_document for r in results)
