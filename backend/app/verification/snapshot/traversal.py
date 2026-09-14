"""Shared read helpers over a built snapshot (LP-313/314).

Tiny, pure accessors the tag-production stages share so the traversal is defined once, not
copy-pasted per stage. No mutation, no DB, no AI.
"""

from __future__ import annotations

from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import ListRow, Snapshot, TransactionRecord


def field_value(field: Field) -> object:
    """A snapshot Field's present value, or ``None`` when the field is absent.

    The single "what a consumer/AI sees for this cell" rule: an absent field reads as ``None``,
    a present field (even present-but-null) reads as its value.
    """
    return field.value if field.is_present else None


def all_transactions(snapshot: Snapshot) -> list[TransactionRecord]:
    """Every surfaced transaction across the snapshot's documents, in deterministic order.

    Empty when the documents section is absent/failed or carries no transactions.
    """
    if snapshot.documents.absent:
        return []
    return [txn for entry in snapshot.documents.entries for txn in (entry.transactions or ())]


#: The classifier's UNCLASSIFIED sentinel. A slug, not None — `classification.py` writes it both when
#: the model is unsure and when the call never completed, so a document can be unclassified either way.
_UNKNOWN_DOC_TYPE = "unknown"


def unclassified_documents(snapshot: Snapshot) -> tuple[str, ...]:
    """Content ids of the documents nobody has identified yet (bug-023).

    ONE definition, because it was becoming several. A rule that looks for a document type skips an
    unclassified file exactly as if it were absent, so its finding says the file does not have it — on
    LF-XMB2, ID-5 asked for a government ID while the borrower's licence sat in the file, untyped, and
    ID-3 said only one document states the date of birth when the licence would have been the second.
    Both need the same clause, and bug-020 wrote the predicate inline for the first of them.

    Returns ids rather than a count so a caller can name them; empty when the documents section itself
    is absent, which is the honest answer — a build that could not look has not found untyped files.
    """
    if snapshot.documents.absent:
        return ()
    return tuple(
        entry.content_id
        for entry in snapshot.documents.entries
        if entry.document_type is None or entry.document_type == _UNKNOWN_DOC_TYPE
    )


def all_list_rows(
    snapshot: Snapshot, list_name: str, *, document_type: str | None = None
) -> list[ListRow]:
    """Every row of the named GENERIC list across the snapshot's documents (LP-437), in order.

    The generic counterpart to :func:`all_transactions` — a derived recipe or a per-row enumerator
    reads ``entry.lists.get(list_name, ())`` cleanly through this one helper, never reaching into the
    dict per consumer. Empty when the documents section is absent or no document carries the list.

    ``document_type`` scopes the gather to one document type (LP-453 review) — a list-name is NOT a
    unique key (66+ lists exist; a future extractor could reuse ``tradelines``/``transactions``), so a
    consumer that means "the credit report's tradelines" passes ``document_type="credit_report"`` rather
    than trusting global name uniqueness. ``None`` gathers across every document type (the prior behavior).
    """
    if snapshot.documents.absent:
        return []
    return [
        row
        for entry in snapshot.documents.entries
        if document_type is None or entry.document_type == document_type
        for row in entry.lists.get(list_name, ())
    ]


def source_document_by_subject(snapshot: Snapshot) -> dict[str, str]:
    """Map every subject a rule can be keyed on to the DOCUMENT it came from (LP-619).

    A finding is keyed by SUBJECT, and only some subjects are documents. A deposit's subject is a
    transaction's content_id and a tradeline's is a list row's — and both are stored NESTED INSIDE the
    document they came from, then flattened by :func:`all_transactions` / :func:`all_list_rows`, which
    keep the child and drop the parent. On LF-3CVT that was most of the file: AS-1 alone has eleven
    findings, each about a deposit, none able to say WHICH bank statement it is on.

    So this is not a derivation — it is the parent link that already exists in the structure, kept:

    * a document maps to ITSELF (a `per_document` rule's subject IS its source);
    * a transaction maps to the statement carrying it;
    * a stable list row maps to the document declaring the list (a tradeline to the credit report).

    NOT EVERY SUBJECT IS IN HERE, and that is the point. A borrower, a loan, an account key, a MISMO
    stated liability (which came from the 1003 import, not from any document on the file) and an
    id-less tradeline (synthesized a subject id because its row carried none) are all ABSENT — a
    caller gets nothing for them and must say nothing, rather than attributing a finding to a document
    it did not come from.
    """
    if snapshot.documents.absent:
        return {}
    parents: dict[str, str] = {}
    for entry in snapshot.documents.entries:
        parents[entry.content_id] = entry.content_id
        for txn in entry.transactions or ():
            parents[txn.content_id] = entry.content_id
        for rows in entry.lists.values():
            for row in rows:
                if row.row_id is not None:
                    parents[row.row_id] = entry.content_id
    return parents
