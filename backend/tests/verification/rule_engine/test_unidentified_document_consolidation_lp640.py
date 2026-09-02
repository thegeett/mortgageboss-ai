"""LP-640 — one unidentified document must cost ONE queue item, not 22.

On staging LF-ZE9N, three documents the classifier could not identify produced **66 of the 148 items**
in the processor's queue: 22 rules x 3 documents, every row asking the same question and carrying the
same remedy. This pins both halves of the fix:

* the ENGINE attributes the abstention (``unidentified_document``) only when the DOCUMENT-TYPE
  predicate is what it could not determine — never when some other fact is missing; and
* the PERSISTENCE layer collapses those into a single loan-level evaluation, while every one of them
  stays ``COULDNT_CHECK`` so no blocked rule can read as clean (the LP-391 silence trap).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.rule_findings import consolidate_unidentified_documents
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage


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


def _snapshot(docs: list[tuple[str, str | None, dict[str, Tag]]]) -> Snapshot:
    entries = [DocumentEntry(content_id=cid, document_type=dtype) for cid, dtype, _ in docs]
    by_subject = {cid: tags for cid, _, tags in docs if tags}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )


def _evaluation(
    rule_id: str, subject_id: str, *, unidentified: bool, verdict: Verdict = Verdict.COULDNT_CHECK
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning="fixture reason",
        how_to_fix=None,
        unidentified_document=unidentified,
    )


# --------------------------------------------------------------------------- #
# The engine's attribution — only a DOCUMENT-TYPE abstention is consolidatable
# --------------------------------------------------------------------------- #
def test_unknown_document_type_marks_the_abstention_as_unidentified() -> None:
    # ID-7 scopes to a title commitment. A document whose type is "unknown" cannot be ruled in OR out,
    # so the rule abstains — and the abstention is attributable to the document type.
    results = evaluate_deterministic_rule(
        load_rule_spec("ID-7"), _snapshot([("doc-unknown", "unknown", {})])
    )
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    assert results[0].unidentified_document is True


def test_a_confidently_typed_document_is_never_marked() -> None:
    # A paystub is DEFINITELY not a title commitment → not_applicable (scope-false), which must never
    # be swept into the consolidated finding: nothing about it asks a processor to identify anything.
    results = evaluate_deterministic_rule(
        load_rule_spec("ID-7"), _snapshot([("pay", "paystub", {})])
    )
    assert all(r.unidentified_document is False for r in results)


def test_an_absent_document_couldnt_check_is_not_marked() -> None:
    # LP-330's MISSING-document abstention is a different task with a different remedy ("request one
    # from the borrower"), so it keeps its own finding rather than folding into "identify these files".
    results = evaluate_deterministic_rule(
        load_rule_spec("ID-7"), _snapshot([("pay", "paystub", {}), ("w2", "w2", {})])
    )
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    assert results[0].subject_id == "missing:title_commitment"
    assert results[0].unidentified_document is False


# --------------------------------------------------------------------------- #
# The consolidation
# --------------------------------------------------------------------------- #
def test_twenty_two_rules_over_three_documents_become_one_finding() -> None:
    # The LF-ZE9N shape, exactly: 22 rules x 3 unidentified documents.
    blocked = [
        _evaluation(f"R-{n}", f"doc{d}", unidentified=True) for d in range(3) for n in range(22)
    ]
    out = consolidate_unidentified_documents(blocked)

    assert len(out) == 1
    consolidated = out[0]
    assert consolidated.subject_id == "loan"
    assert consolidated.verdict is Verdict.COULDNT_CHECK  # still blocks — never silence
    assert "3 documents" in consolidated.reasoning
    assert "66 checks" in consolidated.reasoning  # names the cost it just absorbed
    # LP-617 — links the actual documents, so a loan-level row is still actionable.
    assert consolidated.source_content_ids == ("doc0", "doc1", "doc2")


def test_a_single_unidentified_document_reads_in_the_singular() -> None:
    out = consolidate_unidentified_documents([_evaluation("R-1", "doc0", unidentified=True)])
    assert len(out) == 1
    assert "1 document in this file could not be identified" in out[0].reasoning
    assert "it" in out[0].how_to_fix  # not "each one"


def test_unrelated_findings_pass_through_untouched() -> None:
    keep_open = _evaluation("AS-1", "txn1", unidentified=False, verdict=Verdict.FIRED)
    keep_abstain = _evaluation("IN-3", "loan", unidentified=False)
    blocked = _evaluation("ID-7", "doc0", unidentified=True)

    out = consolidate_unidentified_documents([keep_open, blocked, keep_abstain])

    assert keep_open in out and keep_abstain in out
    assert blocked not in out
    assert len(out) == 3  # the two survivors + one consolidated


def test_no_unidentified_documents_returns_the_input_unchanged() -> None:
    # The run that must RETIRE a prior consolidated finding produces none of them, so this path has to
    # be a clean no-op — and identity is asserted, not just equality, to pin that nothing is rebuilt.
    results = [_evaluation("AS-1", "txn1", unidentified=False)]
    assert consolidate_unidentified_documents(results) is results


def test_the_consolidated_finding_never_claims_a_validated_threshold() -> None:
    # It is the row a processor is most likely to read; a Priya-validated badge on a synthetic finding
    # with no threshold would be a false claim of domain sign-off.
    out = consolidate_unidentified_documents([_evaluation("ID-7", "doc0", unidentified=True)])
    assert out[0].priya_validated is False
    assert out[0].threshold_used is None
    assert out[0].load_bearing_tags == ()
