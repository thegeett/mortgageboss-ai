"""Subject enumerators (LP-324) — resolve a spec's executable ``subject_enumeration`` key.

A rule's spec declares WHERE its subjects come from as a KEY (not prose); the generic evaluators
resolve the key to an enumerator that yields ``(subject_id, subject_tags)`` pairs from a tagged
snapshot. Adding a rule over an existing subject shape needs no new Python — it reuses a key.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.verification.rules.specs import DOC_TYPE_TAG
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_transactions

# The loan-level subject key: loan-level tags (occupancy.*, id.*, …) live under this single subject
# in the tags layer (distinct from the per-transaction content_id subjects). Introduced by LP-319.
LOAN_SUBJECT = "loan"
_UNKNOWN = "unknown"

Subject = tuple[str, Mapping[str, Tag]]
Enumerator = Callable[[Snapshot], list[Subject]]


def _per_deposit(snapshot: Snapshot) -> list[Subject]:
    """One subject per bank-statement transaction (its stable content_id + its tag map)."""
    if snapshot.tags.absent:
        return [(txn.content_id, {}) for txn in all_transactions(snapshot)]
    return [
        (txn.content_id, snapshot.tags.by_subject.get(txn.content_id, {}))
        for txn in all_transactions(snapshot)
    ]


def _loan(snapshot: Snapshot) -> list[Subject]:
    """The single loan-level subject (loan-level tags live under ``LOAN_SUBJECT``)."""
    tags = {} if snapshot.tags.absent else snapshot.tags.by_subject.get(LOAN_SUBJECT, {})
    return [(LOAN_SUBJECT, tags)]


def _per_borrower(snapshot: Snapshot) -> list[Subject]:
    """One subject per borrower on the loan — serving BOTH meanings of ``per_borrower`` (LP-325/331).

    Borrowers are the distinct ``belongs_to`` refs across the documents (the reliable
    borrower↔document resolution, LP-202), in first-seen order.

    The subject's tag map is ASSEMBLED (LP-331, GAP-D) by DECLARED keying, so the SAME enumerator
    serves its two legitimate meanings without duplicating a fact:

    * a CONSISTENCY rule uses ``per_borrower`` as a GROUPING KEY and IGNORES this map — it GATHERS its
      document-keyed fact across the borrower's documents itself (LP-325). So what this map contains is
      irrelevant to consistency (verified: ``consistency.py`` discards ``_subject_tags``), and ID-1/2/3/4
      are unchanged. LP-326's document keying is untouched.
    * a per-borrower JUDGMENT rule (e.g. ID-8 citizenship eligibility) READS this map. It gets the
      borrower's OWN facts (materialized under ``by_subject[borrower_id]`` — a borrower-level fact like
      ``id.citizenship`` from the 1003/MISMO) plus the LOAN-LEVEL shared facts (e.g. ``program.type``)
      merged in as context — each fact from its ONE declared keying (no duplication, no divergence). A
      borrower's own facts override a same-id loan fact.

    Borrower isolation: each map holds ONLY that borrower's own tags + the shared loan tags — one
    borrower's facts never leak into another's. An absent/empty map → the judgment gates to couldnt_check
    for that borrower (fail-closed), never a fabricated verdict.

    NOTE (deferred, LP-331): a PRODUCER that materializes ``id.citizenship`` under ``borrower_id`` from
    MISMO (which keys per-borrower facts by INDEX, ``borrower.N.*``) needs a ``borrower_id ↔ MISMO-index``
    resolution — a separate materialization gap. This enumerator is complete regardless of how the
    borrower's facts got under ``by_subject[borrower_id]``.
    """
    if snapshot.documents.absent:
        return []
    by_subject = {} if snapshot.tags.absent else snapshot.tags.by_subject
    loan_tags = by_subject.get(
        LOAN_SUBJECT, {}
    )  # loan-level facts, shared into every borrower's context
    seen: dict[str, None] = {}  # borrower_id -> None, preserving first-seen (deterministic) order
    for entry in snapshot.documents.entries:
        if entry.belongs_to is None:
            continue
        for ref in entry.belongs_to:
            seen.setdefault(str(ref.borrower_id), None)
    # {**loan, **own}: the borrower's OWN facts take precedence over a same-id loan fact.
    return [(bid, {**loan_tags, **by_subject.get(bid, {})}) for bid in seen]


def _per_document(snapshot: Snapshot) -> list[Subject]:
    """One subject per document (LP-327) — its stable ``content_id`` + the tags ABOUT that document.

    Unlike ``per_borrower``, the tag map is POPULATED (a document's tags are keyed under its own
    content_id), so a per-DOCUMENT rule (ID-9 POA acceptability, ID-7 title vesting, altered-document
    detection, appraisal condition) can reason over that document's declared tags.

    The document's INTRINSIC type (``DocumentEntry.document_type`` — the classifier's known vocabulary:
    ``title_commitment`` / ``power_of_attorney`` / …) is injected as a structural subject tag
    ``document.document_type`` (LP-329), so a rule can DECLARE its document-type applicability as a
    plain tag predicate (``document.document_type == "power_of_attorney"``) — no document types in
    code, no entry-passing. An unclassified document → value ``"unknown"`` (the applicability then
    couldnt_checks — honest — rather than wrongly ruling the rule out).
    """
    if snapshot.documents.absent:
        return []
    tags = {} if snapshot.tags.absent else snapshot.tags.by_subject
    subjects: list[Subject] = []
    for entry in snapshot.documents.entries:
        subject_tags = {**tags.get(entry.content_id, {}), DOC_TYPE_TAG: _doc_type_tag(entry)}
        subjects.append((entry.content_id, subject_tags))
    return subjects


# DOC_TYPE_TAG (the reserved structural tag id for a document's intrinsic type) is the ONE contract
# source in ``specs`` — imported above — so a spec's applicability predicate and this injection can
# never drift, and RuleSpec validates a document-type-scoped rule is actually per_document.


def _doc_type_tag(entry: DocumentEntry) -> Tag:
    return Tag(
        value=entry.document_type or _UNKNOWN,
        confidence=None,
        reasoning="the document's classified type (structural)",
        source_facts=(entry.content_id,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


_ENUMERATORS: dict[str, Enumerator] = {
    "per_deposit": _per_deposit,
    "loan": _loan,
    "per_borrower": _per_borrower,
    "per_document": _per_document,
}


def enumerate_subjects(key: str, snapshot: Snapshot) -> list[Subject]:
    """Resolve the spec's ``subject_enumeration`` key to its subjects (raises on an unknown key)."""
    enumerator = _ENUMERATORS.get(key)
    if enumerator is None:
        raise KeyError(f"unknown subject_enumeration key {key!r} (known: {sorted(_ENUMERATORS)})")
    return enumerator(snapshot)


def is_known_enumerator(key: str) -> bool:
    return key in _ENUMERATORS


__all__ = ["LOAN_SUBJECT", "enumerate_subjects", "is_known_enumerator"]
