"""Shared read helpers over a built snapshot (LP-313/314).

Tiny, pure accessors the tag-production stages share so the traversal is defined once, not
copy-pasted per stage. No mutation, no DB, no AI.
"""

from __future__ import annotations

from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import (
    DocumentEntry,
    ListRow,
    Snapshot,
    SnapshotField,
    TransactionRecord,
)
from app.verification.snapshot.pii import PiiField


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


def _comparable(field: SnapshotField) -> object:
    """One row field reduced to something two documents can be compared on (bug-025).

    ⚠️ A ROW FIELD MAY BE A ``PiiField``, WHICH HAS NO ``value`` AT ALL. It carries a masked
    ``display`` plus a ``match_hash`` and deliberately discards the raw value, so ``field_value`` —
    typed for ``Field`` and reaching for ``.value`` / ``.is_present`` — is wrong for one both to mypy
    and at runtime. This is not hypothetical for the case that motivated the de-duplication: a
    tradeline's ``account_number_masked`` is a declared-sensitive row field, so every credit report
    hits this branch.

    The masked display plus the match hash is the right comparison anyway: two copies of one document
    mask to the same display and hash to the same value, and two different accounts do not.
    """
    if isinstance(field, PiiField):
        return ("pii", field.display, field.match_hash, field.absent)
    return field_value(field)


def _list_contribution(entry: DocumentEntry, list_name: str) -> tuple[object, ...]:
    """What this document contributes to ``list_name`` — its identity for de-duplication (bug-025).

    ``document_type`` + the resolved borrowers + every row's ``(field name, value)`` pairs. Two
    documents agreeing on all three are offering the SAME rows, whatever else differs about them.

    ⚠️ ``row_id`` IS DELIBERATELY EXCLUDED, and including it would defeat the whole thing. A row's id
    is derived from its content *scoped by the parent document's content id* (`finalize_lists` takes
    ``document_content_id``), so two byte-identical documents produce rows whose ids differ by
    construction. Comparing ids would find no duplicates ever.

    ``belongs_to`` IS included, and that is what keeps the legitimate case safe: a joint file may carry
    one credit report per borrower, and those are two documents about two people, not one filed twice.
    Sorted by borrower id, because the link query orders by confidence and equal-confidence borrowers
    have no stable relative order (the same reason `_document_base` sorts them).
    """
    rows = entry.lists.get(list_name, ())
    return (
        entry.document_type,
        tuple(sorted((str(ref.borrower_id), ref.name) for ref in (entry.belongs_to or ()))),
        tuple(
            tuple(sorted((name, str(_comparable(field))) for name, field in row.fields.items()))
            for row in rows
        ),
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

    ⚠️ A DOCUMENT FILED TWICE CONTRIBUTES ITS ROWS ONCE (bug-025). This flattens rows across every
    matching document, and on staging one loan file carries the same credit report twice — same
    filename, same 134,660 bytes, each extraction listing the same 24 tradelines. So every row-level
    consumer saw 48 rows where 24 exist: `credit.tradeline_count` doubled, the sum in
    `credit.tradeline_monthly_payment_total` doubled, and `liability_rows` minted two subjects for one
    debt (the limitation `enumerators.py` records as "no dedup WITHIN a source"). Deduplicating HERE
    fixes all four at once, because all four gather through this function.

    IT IS A SUM PROBLEM, not a presentation one, which is why the guard is here and not at emission.
    These rows feed TAG MATERIALISATION — upstream of findings entirely — so no collapse of duplicate
    findings could have reached it. LP-1000 stops new duplicates being created; this is what protects
    the files that already carry them.

    THE SURVIVOR IS THE LOWEST ``content_id``, never the first in document order. `liability_rows`
    uses a row's ``row_id`` as a finding's subject key, and a row_id is scoped by its parent document —
    so if the surviving copy changed between runs, the reconciler would meet an unseen subject, mint a
    fresh finding and retire the old one with its history. Documents load ordered by
    ``(document_type, created_at, id)``, so classifying an untyped document reorders them; a content id
    is stable per document by construction (LP-312). Same correction bug-024's review applied to the
    transaction and per-account collapses.
    """
    if snapshot.documents.absent:
        return []
    in_scope = [
        entry
        for entry in snapshot.documents.entries
        if document_type is None or entry.document_type == document_type
    ]
    # Group by what each document CONTRIBUTES, then keep one document per group — the one whose
    # content id sorts lowest, so the choice cannot move when the documents are reordered.
    survivors: dict[tuple[object, ...], str] = {}
    for entry in in_scope:
        if not entry.lists.get(list_name):
            continue  # contributes nothing either way; never a "duplicate" of another empty document
        signature = _list_contribution(entry, list_name)
        current = survivors.get(signature)
        if current is None or entry.content_id < current:
            survivors[signature] = entry.content_id
    keep = set(survivors.values())
    return [
        row
        for entry in in_scope
        if entry.content_id in keep
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
