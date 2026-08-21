"""LP-619 — a deposit's finding can name the bank statement it is on.

LP-617 gave findings their source documents, but only where the rule already knew them: consistency
rules (which gather per source) and `per_document` rules (whose subject IS the document). That left
the bulk uncovered — on LF-3CVT, AS-1's eleven deposit findings, AS-12's ten, FR-5's six and CR-6's
four could name no document at all, and between them that is most of the file.

The parent link was never missing from the data. A transaction is stored NESTED INSIDE the statement
it came from, and `all_transactions` flattens that, keeping the child and dropping the parent. Same
for `all_list_rows` and a credit report's tradelines. This keeps the parent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    ListRow,
    Snapshot,
    TransactionRecord,
)
from app.verification.snapshot.traversal import source_document_by_subject


def _txn(content_id: str) -> TransactionRecord:
    return TransactionRecord(
        content_id=content_id,
        date=Field.present("2025-03-04", source=FieldSource.EXTRACTED),
        amount=Field.present("2000.00", source=FieldSource.EXTRACTED),
        direction=Field.present("credit", source=FieldSource.DERIVED),
        description=Field.present("PAYROLL", source=FieldSource.EXTRACTED),
    )


def _snapshot(entries: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
    )


def test_a_deposit_resolves_to_the_statement_it_is_on() -> None:
    snap = _snapshot(
        [
            DocumentEntry(
                content_id="stmt_jan",
                document_type="bank_statement",
                transactions=(_txn("txn1"), _txn("txn2")),
            ),
            DocumentEntry(
                content_id="stmt_feb", document_type="bank_statement", transactions=(_txn("txn3"),)
            ),
        ]
    )
    parents = source_document_by_subject(snap)

    assert parents["txn1"] == "stmt_jan"
    assert parents["txn2"] == "stmt_jan"
    assert parents["txn3"] == "stmt_feb"  # the SECOND statement, not just any


def test_a_tradeline_resolves_to_the_credit_report() -> None:
    snap = _snapshot(
        [
            DocumentEntry(
                content_id="report",
                document_type="credit_report",
                lists={"tradelines": (ListRow(fields={}, row_id="line1"),)},
            )
        ]
    )
    assert source_document_by_subject(snap)["line1"] == "report"


def test_a_document_is_its_own_source() -> None:
    """A `per_document` rule's subject IS the document — the same lookup serves it."""
    snap = _snapshot([DocumentEntry(content_id="binder", document_type="homeowners_insurance")])
    assert source_document_by_subject(snap)["binder"] == "binder"


def test_a_row_with_no_stable_id_is_absent_rather_than_guessed() -> None:
    """An id-less tradeline is given a SYNTHESIZED subject id by the enumerator, which is not this
    row's id — so mapping it here would attach a finding to a document by coincidence."""
    snap = _snapshot(
        [
            DocumentEntry(
                content_id="report",
                document_type="credit_report",
                lists={"tradelines": (ListRow(fields={}, row_id=None),)},
            )
        ]
    )
    assert source_document_by_subject(snap) == {"report": "report"}


def test_a_borrower_or_loan_subject_has_no_document() -> None:
    """The subjects that legitimately have none. `.get()` returns None and the caller says nothing —
    a MISMO-stated liability came from the 1003 import, not from any document on the file, and
    pointing it at the credit report would be a confident lie."""
    snap = _snapshot([DocumentEntry(content_id="stmt", document_type="bank_statement")])
    parents = source_document_by_subject(snap)

    assert parents.get("loan") is None
    assert parents.get(str(uuid4())) is None  # a borrower id
    assert parents.get("lia_abc123") is None  # a MISMO stated liability


def test_an_absent_documents_section_yields_nothing() -> None:
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        documents=DocumentsSection.failed("build degraded"),
    )
    assert source_document_by_subject(snap) == {}


# --------------------------------------------------------------------------- #
# The attach step — how the run applies the map
# --------------------------------------------------------------------------- #
def _evaluation(subject_id: str, *, carried: tuple[str, ...] = ()):
    from app.verification.rule_engine.result import RuleEvaluation, Verdict

    return RuleEvaluation(
        rule_id="AS-1",
        subject_id=subject_id,
        verdict=Verdict.SATISFIED,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning="x",
        how_to_fix=None,
        source_content_ids=carried,
    )


def test_the_run_attaches_the_parent_document_to_a_deposit_finding() -> None:
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot(
        [
            DocumentEntry(
                content_id="stmt_jan",
                document_type="bank_statement",
                transactions=(_txn("txn1"),),
            )
        ]
    )
    (attached,) = _attach_document_provenance([_evaluation("txn1")], snap)
    assert attached.source_content_ids == ("stmt_jan",)


def test_what_the_rule_carried_is_never_overwritten() -> None:
    """A consistency rule knows which sources it compared AND which it excluded; the subject's own
    document cannot reconstruct that, so it must not replace it."""
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot(
        [
            DocumentEntry(
                content_id="stmt_jan",
                document_type="bank_statement",
                transactions=(_txn("txn1"),),
            )
        ]
    )
    (attached,) = _attach_document_provenance(
        [_evaluation("txn1", carried=("w2_2024", "paystub"))], snap
    )
    assert attached.source_content_ids == ("w2_2024", "paystub")


def test_a_subject_with_no_document_is_left_alone() -> None:
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot([DocumentEntry(content_id="stmt", document_type="bank_statement")])
    (attached,) = _attach_document_provenance([_evaluation("loan")], snap)
    assert attached.source_content_ids == ()
