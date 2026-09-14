"""bug-025 — a document filed twice must not contribute its rows twice.

`all_list_rows` flattens rows across every matching document. On staging one loan file carries the
same credit report twice — same filename, same 134,660 bytes, each extraction listing the same 24
tradelines — so every row-level consumer saw 48 rows where 24 exist:

  * `credit.tradeline_count` counted 48;
  * `credit.tradeline_monthly_payment_total` summed 48 monthly payments;
  * `liability_rows` minted two subjects for one debt (the "no dedup WITHIN a source" limitation
    `enumerators.py` already records);
  * and `credit.collection_aggregate_balance`, which gates LIVE CR-10 against Fannie's payoff
    thresholds, sums over the same rows.

All four gather through this one function, which is why the guard lives there.

WHY NOT AT EMISSION: these rows feed TAG MATERIALISATION, upstream of findings entirely, so no
collapse of duplicate findings could reach the doubled number. LP-1000 stops new duplicates being
created; this protects the files that already carry them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    ListRow,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.pii import PiiField, PiiKind
from app.verification.snapshot.traversal import all_list_rows, field_value

_LOAN_FILE_ID = uuid4()

_TRADELINES = "tradelines"


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _row(creditor: str, payment: str, row_id: str) -> ListRow:
    # `row_id` differs between two copies BY CONSTRUCTION — it is derived from the row's content
    # scoped by the parent document's content id — so the de-duplication must ignore it. Passing
    # deliberately different ids here is what makes that assertion real.
    return ListRow(
        fields={"creditor_name": _f(creditor), "monthly_payment": _f(payment)},
        row_id=row_id,
    )


def _report(
    content_id: str, rows: tuple[ListRow, ...], *, refs: tuple[BorrowerRef, ...] = ()
) -> DocumentEntry:
    return DocumentEntry(
        content_id=content_id,
        document_type="credit_report",
        belongs_to=refs or None,
        lists={_TRADELINES: rows},
    )


def _snap(entries: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# The defect
# --------------------------------------------------------------------------- #
def test_the_same_report_filed_twice_contributes_its_rows_once() -> None:
    """THE STAGING SHAPE: 24 tradelines present, 48 gathered."""
    rows_a = tuple(_row(f"CREDITOR {n}", str(100 + n), f"lst_a{n}") for n in range(24))
    rows_b = tuple(_row(f"CREDITOR {n}", str(100 + n), f"lst_b{n}") for n in range(24))
    snap = _snap([_report("doc_a", rows_a), _report("doc_b", rows_b)])

    gathered = all_list_rows(snap, _TRADELINES, document_type="credit_report")

    assert len(gathered) == 24, "the duplicate report's rows were counted again"


def test_a_sum_over_the_rows_is_no_longer_doubled() -> None:
    """The arithmetic this exists for — `tradeline_monthly_payment_total`'s shape."""
    rows_a = (_row("UWM", "3907", "lst_a1"), _row("ALLY FINANCIAL", "438", "lst_a2"))
    rows_b = (_row("UWM", "3907", "lst_b1"), _row("ALLY FINANCIAL", "438", "lst_b2"))
    snap = _snap([_report("doc_a", rows_a), _report("doc_b", rows_b)])

    # `fields` is `dict[str, SnapshotField]` — a `Field | PiiField` union, and a `PiiField` carries no
    # value at all, which is why production compares through `_comparable` rather than `field_value`.
    # The narrowing here is the test paying the same tax: this fixture builds plain `Field`s, and
    # saying so is honest where reaching straight for `.value` would assert against a shape the type
    # does not guarantee.
    payments: list[int] = []
    for row in all_list_rows(snap, _TRADELINES, document_type="credit_report"):
        payment = row.fields["monthly_payment"]
        assert isinstance(payment, Field), "this fixture builds plain Fields, not PiiFields"
        payments.append(int(str(field_value(payment))))
    total = sum(payments)

    assert total == 4345, "the payment total still double-counts the duplicate report"


def test_the_row_ids_of_the_surviving_copy_are_the_ones_returned() -> None:
    """Not just the count — a caller keying findings on `row_id` must get ONE copy's ids, not a
    mixture, or two subjects would still describe one debt."""
    snap = _snap(
        [
            _report("doc_b", (_row("UWM", "3907", "lst_b1"),)),
            _report("doc_a", (_row("UWM", "3907", "lst_a1"),)),
        ]
    )

    (row,) = all_list_rows(snap, _TRADELINES, document_type="credit_report")

    assert row.row_id == "lst_a1", "the survivor must be the lowest content_id's copy"


def test_the_survivor_does_not_depend_on_document_order() -> None:
    """⚠️ THE RECONCILER'S EXPOSURE, closed the way bug-024's review closed it.

    A row's `row_id` is a finding's subject key. Documents load ordered by
    `(document_type, created_at, id)`, so classifying a previously untyped document reorders them —
    and if the surviving copy moved, the reconciler would meet a subject it has never seen, mint a
    fresh finding and retire the old one with its history. A content id is stable per document by
    construction (LP-312), so it decides, not position.
    """
    rows_a = (_row("UWM", "3907", "lst_a1"),)
    rows_b = (_row("UWM", "3907", "lst_b1"),)
    for order in ([("doc_a", rows_a), ("doc_b", rows_b)], [("doc_b", rows_b), ("doc_a", rows_a)]):
        snap = _snap([_report(cid, rows) for cid, rows in order])

        (row,) = all_list_rows(snap, _TRADELINES, document_type="credit_report")

        assert row.row_id == "lst_a1", f"arriving as {[c for c, _ in order]} changed the survivor"


# --------------------------------------------------------------------------- #
# What must STILL be gathered — each a way this could have been too aggressive
# --------------------------------------------------------------------------- #
def test_two_reports_for_DIFFERENT_borrowers_both_count() -> None:
    """⚠️ THE LEGITIMATE CASE, and the reason `belongs_to` is in the signature. A joint file may
    carry one credit report per borrower — two documents about two people, not one filed twice.
    `enumerators.py` names this case in the same breath as the duplicate."""
    one, two = (
        BorrowerRef(borrower_id=uuid4(), name="Ila Patel"),
        BorrowerRef(borrower_id=uuid4(), name="Divyeshkumar Patel"),
    )
    rows = (_row("UWM", "3907", "lst_1"),)
    snap = _snap(
        [
            _report("doc_a", rows, refs=(one,)),
            _report("doc_b", (_row("UWM", "3907", "lst_2"),), refs=(two,)),
        ]
    )

    assert len(all_list_rows(snap, _TRADELINES, document_type="credit_report")) == 2


def test_two_genuinely_different_reports_both_count() -> None:
    snap = _snap(
        [
            _report("doc_a", (_row("UWM", "3907", "lst_a1"),)),
            _report("doc_b", (_row("DISCOVER", "367", "lst_b1"),)),
        ]
    )

    assert len(all_list_rows(snap, _TRADELINES, document_type="credit_report")) == 2


def test_a_masked_row_field_compares_without_reaching_for_a_value() -> None:
    """⚠️ `PiiField` HAS NO `.value`. A tradeline's `account_number_masked` is declared sensitive, so
    every real credit report takes this branch — comparing on the masked display plus the match hash,
    which two copies of one document share and two different accounts do not."""
    masked = PiiField.from_raw(
        "4111111111111111",
        kind=PiiKind.ACCOUNT,
        loan_file_id=_LOAN_FILE_ID,
        source=FieldSource.EXTRACTED,
    )
    row_a = ListRow(fields={"account_number_masked": masked}, row_id="lst_a1")
    row_b = ListRow(fields={"account_number_masked": masked}, row_id="lst_b1")
    snap = _snap([_report("doc_a", (row_a,)), _report("doc_b", (row_b,))])

    gathered = all_list_rows(snap, _TRADELINES, document_type="credit_report")

    assert len(gathered) == 1 and gathered[0].row_id == "lst_a1"


def test_a_document_carrying_no_rows_is_not_a_duplicate_of_another_empty_one() -> None:
    """Two reports that contribute nothing are not "the same document" — they contribute nothing
    either way, and treating them as duplicates would be a claim about them that nothing supports."""
    snap = _snap(
        [
            _report("doc_a", ()),
            _report("doc_b", ()),
            _report("doc_c", (_row("UWM", "3907", "lst_c1"),)),
        ]
    )

    assert len(all_list_rows(snap, _TRADELINES, document_type="credit_report")) == 1


def test_an_absent_documents_section_still_gathers_nothing() -> None:
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        documents=DocumentsSection.failed("degraded"),
        tags=TagsSection.present({}),
    )

    assert all_list_rows(snap, _TRADELINES, document_type="credit_report") == []


def test_a_different_document_type_is_untouched_by_the_scope() -> None:
    """The `document_type` filter still decides what is in scope at all; de-duplication happens
    within that scope, never across it."""
    snap = _snap(
        [
            _report("doc_a", (_row("UWM", "3907", "lst_a1"),)),
            DocumentEntry(
                content_id="doc_other",
                document_type="bank_statement",
                lists={_TRADELINES: (_row("UWM", "3907", "lst_o1"),)},
            ),
        ]
    )

    gathered = all_list_rows(snap, _TRADELINES, document_type="credit_report")

    assert [r.row_id for r in gathered] == ["lst_a1"]
