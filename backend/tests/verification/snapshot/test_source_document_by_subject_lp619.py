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


# --------------------------------------------------------------------------- #
# bug-013 — a carried TRANSACTION id is translated to its statement
# --------------------------------------------------------------------------- #
def test_a_carried_transaction_resolves_to_its_statement() -> None:
    """THE LF-XMB2 SHAPE. The deterministic evaluator carries the ids its tags named, and a
    per-transaction tag names its own transaction — so AS-1 arrived carrying `("txn1",)`, skipped the
    subject path as "the rule knew better", and the transaction id was later dropped as not-a-document.
    """
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
    (attached,) = _attach_document_provenance([_evaluation("txn1", carried=("txn1",))], snap)
    assert attached.source_content_ids == ("stmt_jan",)


def test_a_matched_debit_on_another_statement_names_both_statements() -> None:
    """A FORWARD GUARD — not a shape anything produces today, and the docstring said otherwise.

    Every load-bearing tag on the four `per_deposit` rules is AI or parsed, and both producers set
    `source_facts=(subject_id,)` (`tag_materialization/ai.py`, `parsed.py`); `_per_deposit` merges no
    loan-level tags into a transaction's map, and the only two recipes that name their own sources are
    loan-subject. So a carried id today is the subject's own transaction and nothing else.

    A producer that named a matched withdrawal — the obvious next one for AS-2 — would land here, and
    then both statements are what the verdict rests on. See the ordering test below for which of them
    becomes the finding's primary link.
    """
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot(
        [
            DocumentEntry(
                content_id="stmt_jan",
                document_type="bank_statement",
                transactions=(_txn("txn1"),),
            ),
            DocumentEntry(
                content_id="stmt_savings",
                document_type="bank_statement",
                transactions=(_txn("txn9"),),
            ),
        ]
    )
    (attached,) = _attach_document_provenance([_evaluation("txn1", carried=("txn1", "txn9"))], snap)
    assert attached.source_content_ids == ("stmt_jan", "stmt_savings")


def test_the_carried_order_decides_the_primary_link() -> None:
    """WHICH STATEMENT LEADS IS THE SPEC'S TAG ORDER, not the subject — the invariant a future producer
    has to respect, pinned here because the reviewed commit asserted the opposite ("the deposit's own
    statement stays first") as though the code guaranteed it.

    Translation preserves carried order, and `rule_findings._update_finding` writes `source_ids[0]` to
    `source_document_id` — the single document the UI opens. So the FIRST load-bearing tag in the spec
    decides it. Today every `per_deposit` spec lists a tag on the subject first (AS-1 opens with
    `txn.is_money_in`), which is the whole reason the deposit's own statement leads; a spec that led
    with a tag naming another document would silently send a processor there instead.
    """
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot(
        [
            DocumentEntry(
                content_id="stmt_jan",
                document_type="bank_statement",
                transactions=(_txn("txn1"),),
            ),
            DocumentEntry(
                content_id="stmt_savings",
                document_type="bank_statement",
                transactions=(_txn("txn9"),),
            ),
        ]
    )
    # The subject is still txn1; only the CARRIED order is reversed.
    (attached,) = _attach_document_provenance([_evaluation("txn1", carried=("txn9", "txn1"))], snap)
    assert attached.source_content_ids == ("stmt_savings", "stmt_jan")


def test_two_transactions_on_one_statement_name_it_once() -> None:
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot(
        [
            DocumentEntry(
                content_id="stmt_jan",
                document_type="bank_statement",
                transactions=(_txn("txn1"), _txn("txn2")),
            )
        ]
    )
    (attached,) = _attach_document_provenance([_evaluation("txn1", carried=("txn1", "txn2"))], snap)
    assert attached.source_content_ids == ("stmt_jan",)


def test_an_as1_finding_from_the_real_evaluator_names_its_statement() -> None:
    """End to end over the path that broke: the generic deterministic evaluator runs AS-1's spec, its
    tags name their own transaction (as AI and parsed tags do), and the attach step must turn that into
    the statement — not leave a transaction id for the persistence step to drop."""
    from datetime import UTC, datetime
    from uuid import UUID

    from app.services.verification_run import _attach_document_provenance
    from app.verification.rule_engine.as1 import TAG_AMOUNT, TAG_HAS_SOURCE, TAG_IS_MONEY_IN
    from app.verification.rule_engine.engine import evaluate_as1_rule
    from app.verification.rule_engine.enumerators import LOAN_SUBJECT
    from app.verification.snapshot.documents_section import (
        build_transactions,
        transaction_field_sets,
    )
    from app.verification.snapshot.model import TagsSection
    from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

    txns = build_transactions(
        transaction_field_sets(
            {
                "transactions": [
                    {
                        "date": "2026-02-25",
                        "amount": "19039.08",
                        "description": "D",
                        "transaction_type": "deposit",
                    }
                ]
            },
            "bank_statement",
            loan_file_id=UUID("00000000-0000-0000-0000-00000000b013"),
        ),
        document_content_id="stmt_pnc",
    )
    assert txns is not None
    cid = txns[0].content_id

    def tag(value: str, produced_by: TagProducedBy, subject: str) -> Tag:
        return Tag(
            value=value,
            confidence=0.9 if produced_by is TagProducedBy.AI else None,
            reasoning="fixture",
            source_facts=(subject,),
            produced_by=produced_by,
            tag_role=TagRole.STRUCTURAL_FACT,
            stage=TagStage.A,
        )

    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id="stmt_pnc", document_type="bank_statement", transactions=txns
                )
            ]
        ),
        tags=TagsSection.present(
            {
                cid: {
                    TAG_IS_MONEY_IN: tag("in", TagProducedBy.AI, cid),
                    TAG_AMOUNT: tag("19039.08", TagProducedBy.PARSED, cid),
                    TAG_HAS_SOURCE: tag("no", TagProducedBy.AI, cid),
                },
                LOAN_SUBJECT: {
                    "dti.qualifying_income_monthly": tag(
                        "11193.99", TagProducedBy.DERIVED, LOAN_SUBJECT
                    )
                },
            }
        ),
    )
    [result] = evaluate_as1_rule(snap, confidence_floor=0.5)
    assert result.source_content_ids == (cid,)  # the precondition: the rule carried a TRANSACTION

    (attached,) = _attach_document_provenance([result], snap)
    assert attached.source_content_ids == ("stmt_pnc",)


def test_a_carried_document_id_is_not_rewritten() -> None:
    """AS-8 names its two statements directly. A document maps to itself, so the translation is a no-op
    for it — the same object comes back, not merely an equal one."""
    from app.services.verification_run import _attach_document_provenance

    snap = _snapshot(
        [
            DocumentEntry(content_id="stmt_jan", document_type="bank_statement"),
            DocumentEntry(content_id="stmt_feb", document_type="bank_statement"),
        ]
    )
    evaluation = _evaluation("loan", carried=("stmt_jan", "stmt_feb"))
    (attached,) = _attach_document_provenance([evaluation], snap)
    assert attached is evaluation
