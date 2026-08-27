"""LP-631/632 — the coverage flag, and the liability the credit report already documents.

THE REPORTED CASE. Staging's LF-AWBB carries *"Lease agreement or documentation for the lease payment
liability"*, written at 22:34:58 from the MISMO liability ``LeasePayment / ALLY FINANCIAL / $438.00``,
still open beside a credit report completed at 22:37:47 whose tradelines list
``ALLY FINANCIAL / AUTO / 438``. Fannie Mae B3-6-01 asks for separate documentation only for a
liability "that is not shown on a credit report".

The asymmetry these tests exist to pin: of the six needs this predicate can reach on staging, four are
CORRECT — their files have no credit report, so the liabilities genuinely must be verified from the
borrower or creditor. A predicate that suppressed all six would be worse than none.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.document import DocumentStatus
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.models.stated_financials import StatedLiability
from app.services.needs_coverage import flag_covered_needs, keep_need_despite_coverage
from sqlalchemy import select
from tests.integration import factories


async def _file(db):
    company = await factories.make_company(db, slug="acme")
    return company, await factories.make_loan_file(db, company=company)


async def _need(
    db,
    loan_file,
    *,
    needs_type="lease_agreement",
    origin=NeedsItemOrigin.AI_REASONING,
    disposition=NeedsItemDisposition.PROPOSED,
    status=NeedsItemStatus.PENDING,
):
    need = await factories.make_needs_item(db, loan_file=loan_file, title=f"Need: {needs_type}")
    need.needs_type = needs_type
    need.origin = origin
    need.disposition = disposition
    need.status = status
    await db.flush()
    return need


async def _liability(db, loan_file, *, liability_type, holder, payment):
    row = StatedLiability(
        loan_file_id=loan_file.id,
        liability_type=liability_type,
        holder_name=holder,
        monthly_payment=Decimal(payment),
    )
    db.add(row)
    await db.flush()
    return row


async def _credit_report(db, loan_file, company, *, tradelines):
    document = await factories.make_document(
        db,
        loan_file=loan_file,
        company=company,
        filename="credit-report.pdf",
        document_type="credit_report",
        status=DocumentStatus.COMPLETED,
    )
    await factories.make_extraction(db, document=document, data={"tradelines": tradelines})
    return document


# --------------------------------------------------------------------------- #
# The reported case
# --------------------------------------------------------------------------- #


async def test_the_lease_need_the_credit_report_already_answers(db_session) -> None:
    """LF-AWBB, reproduced. The liability is on the credit report at the stated payment, so B3-6-01's
    trigger for separate documentation is not met and the need is flagged for the processor."""
    company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="lease_agreement")
    await _liability(
        db_session, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )
    document = await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[
            {"creditor_name": "UWM", "account_type": "MTG", "monthly_payment": 3907},
            {"creditor_name": "ALLY FINANCIAL", "account_type": "AUTO", "monthly_payment": 438},
        ],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1
    await db_session.refresh(need)
    assert need.covered_by_document_id == document.id
    assert "ALLY FINANCIAL" in (need.coverage_note or "")
    assert "B3-6-01" in (need.coverage_note or "")


async def test_the_need_is_flagged_not_closed(db_session) -> None:
    """ADR-388. The flag is the whole intervention — the need's own state is untouched, because the
    system does not get to decide a document will not be collected."""
    company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file)
    await _liability(
        db_session, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "ALLY FINANCIAL", "monthly_payment": 438}],
    )

    await flag_covered_needs(db_session, loan_file_id=loan_file.id)
    await db_session.refresh(need)
    assert need.status is NeedsItemStatus.PENDING
    assert need.disposition is NeedsItemDisposition.PROPOSED
    assert need.deleted_at is None


# --------------------------------------------------------------------------- #
# The four that must survive
# --------------------------------------------------------------------------- #


async def test_no_credit_report_means_the_need_is_correct(db_session) -> None:
    """LF-BVFU / LF-4A5V / LF-ABRS. B3-6-01 requires the documentation precisely BECAUSE there is no
    credit report — four of staging's six reachable needs are this case."""
    _company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file)
    await _liability(
        db_session, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0
    await db_session.refresh(need)
    assert need.covered_by_document_id is None


async def test_every_liability_must_match_not_just_one(db_session) -> None:
    """LP-108's discipline from the coverage side. "Statements for all four revolving accounts" is
    not answered by a report carrying one of them; under-claiming costs a click, over-claiming is the
    dangerous direction."""
    company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="BANK OF AMERICA", payment="25"
    )
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="SYNCB/ROOMS TO GO", payment="301"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "BANK OF AMERICA", "monthly_payment": 25}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0
    await db_session.refresh(need)
    assert need.covered_by_document_id is None


async def test_all_of_them_matching_does_flag(db_session) -> None:
    """The other half of the same rule — and the note names every account, so the processor can check
    the claim rather than take it."""
    company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="BANK OF AMERICA", payment="25"
    )
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="SYNCB/ROOMS TO GO", payment="301"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[
            {"creditor_name": "BANK OF AMERICA", "monthly_payment": 25},
            {"creditor_name": "SYNCB/ROOMS TO GO", "monthly_payment": 301},
        ],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1
    await db_session.refresh(need)
    assert "BANK OF AMERICA" in (need.coverage_note or "")
    assert "SYNCB/ROOMS TO GO" in (need.coverage_note or "")


async def test_the_payment_must_agree_not_only_the_name(db_session) -> None:
    """LF-AWBB carries two CAPITAL ONE rows and two SYNCB/TJXDC rows. The name alone is not
    identifying; requiring the payment to agree is what makes the pair mean something."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="CAPITAL ONE", payment="120"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "CAPITAL ONE", "monthly_payment": 45}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_a_zero_payment_tradeline_is_not_evidence(db_session) -> None:
    """Most of LF-AWBB's 24 tradelines report $0. A closed or never-used account does not document a
    $438 obligation."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file)
    await _liability(
        db_session, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "ALLY FINANCIAL", "monthly_payment": 0}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_no_liability_of_the_type_is_no_basis_for_a_flag(db_session) -> None:
    """An absent premise does not make a claim true. A lease need on a file stating no lease is
    strange, but nothing in the credit report answers it."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="lease_agreement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="BANK OF AMERICA", payment="25"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "BANK OF AMERICA", "monthly_payment": 25}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_a_truncated_creditor_name_still_matches(db_session) -> None:
    """Credit reports truncate. Prefix matching in either direction covers that; it does NOT cover
    internal abbreviation (``UNITED WHSLE MORT`` for ``UNITED WHOLESALE MORTGAGE``), which simply
    fails to match — the safe direction, since a non-match keeps the need."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="BANK OF AMERICA", payment="25"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "BANK OF AMER", "monthly_payment": 25}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1


# --------------------------------------------------------------------------- #
# The eligibility boundary + disposal
# --------------------------------------------------------------------------- #


async def _flaggable_file(db):
    company, loan_file = await _file(db)
    await _liability(
        db, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )
    await _credit_report(
        db,
        loan_file,
        company,
        tradelines=[{"creditor_name": "ALLY FINANCIAL", "monthly_payment": 438}],
    )
    return company, loan_file


async def test_a_need_the_processor_confirmed_is_never_flagged(db_session) -> None:
    """LP-625's boundary, reused verbatim: a confirmed need carries their judgement, and a predicate
    concluding otherwise does not get to say so on their row."""
    _company, loan_file = await _flaggable_file(db_session)
    need = await _need(db_session, loan_file, disposition=NeedsItemDisposition.CONFIRMED)

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0
    await db_session.refresh(need)
    assert need.covered_by_document_id is None


async def test_a_floor_need_is_never_flagged(db_session) -> None:
    """The floor is deterministic and near-certain; this pass exists for the PROVISIONAL rows."""
    _company, loan_file = await _flaggable_file(db_session)
    await _need(db_session, loan_file, origin=NeedsItemOrigin.FLOOR)

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_a_need_with_a_document_attached_is_never_flagged(db_session) -> None:
    """RECEIVED means the borrower already sent something. Flagging it "already covered" would tell
    the processor to drop a requirement mid-review."""
    _company, loan_file = await _flaggable_file(db_session)
    await _need(db_session, loan_file, status=NeedsItemStatus.RECEIVED)

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_the_pass_is_idempotent(db_session) -> None:
    """It runs on every document arrival and every verification. A second run over an unchanged file
    must be silent, not a second flag."""
    _company, loan_file = await _flaggable_file(db_session)
    await _need(db_session, loan_file)

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1
    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_keeping_a_flagged_need_stops_it_coming_back(db_session) -> None:
    """Without ``coverage_reviewed`` the flag returns on the next document to arrive and the
    processor is asked the same question forever."""
    _company, loan_file = await _flaggable_file(db_session)
    need = await _need(db_session, loan_file)
    await flag_covered_needs(db_session, loan_file_id=loan_file.id)

    await keep_need_despite_coverage(db_session, need=need)
    assert need.covered_by_document_id is None
    assert need.coverage_note is None
    assert need.coverage_reviewed is True

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0
    await db_session.refresh(need)
    assert need.covered_by_document_id is None
    assert need.status is NeedsItemStatus.PENDING


async def test_the_pass_can_be_turned_off(db_session, monkeypatch) -> None:
    """A predicate is an optimisation. If one ever misfires on a real file it has to be stoppable
    without a redeploy."""
    from app.core.config import settings

    _company, loan_file = await _flaggable_file(db_session)
    await _need(db_session, loan_file)
    monkeypatch.setattr(settings, "needs_coverage_flagging_enabled", False)

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


# --------------------------------------------------------------------------- #
# Review regressions — each of these shipped broken and is pinned here
# --------------------------------------------------------------------------- #


async def test_a_short_creditor_name_still_matches_exactly(db_session) -> None:
    """The length floor guarded the EQUALITY branch too, so identical short names never matched.
    ALLY, AMEX, CHASE and USAA all normalise below six characters — and because one non-match breaks
    the all-must-match loop, a single short-named liability suppressed the flag for the whole need."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(db_session, loan_file, liability_type="Revolving", holder="AMEX", payment="50")
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "AMEX", "monthly_payment": 50}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1


async def test_a_short_name_still_needs_more_than_a_shared_first_letter(db_session) -> None:
    """The floor still does its job on the PREFIX branch: short names match only when equal."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(db_session, loan_file, liability_type="Revolving", holder="AMEX", payment="50")
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "AMER", "monthly_payment": 50}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_one_tradeline_cannot_answer_two_liabilities(db_session) -> None:
    """THE FALSE-GREEN. Two stated CAPITAL ONE cards at $25/mo against the single $25 row the report
    carries: re-scanning the full list matched both against the one row, the loop completed, and the
    second card was documented by nothing while the need read fully covered."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="CAPITAL ONE", payment="25"
    )
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="CAPITAL ONE", payment="25"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "CAPITAL ONE", "monthly_payment": 25}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0


async def test_two_tradelines_do_answer_two_liabilities(db_session) -> None:
    """The other half — consuming a row must not make a genuinely covered pair look uncovered."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="CAPITAL ONE", payment="25"
    )
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="CAPITAL ONE", payment="25"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[
            {"creditor_name": "CAPITAL ONE", "monthly_payment": 25},
            {"creditor_name": "CAPITAL ONE", "monthly_payment": 25},
        ],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1


async def test_the_catalogued_installment_type_is_reached(db_session) -> None:
    """`installment_loan_statement` is the CATALOG type, so it is what `canonical_need_type` stores —
    and the map named only the uncatalogued `installment_statement`, reaching just the rows whose type
    failed canonicalisation and was stored raw."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="installment_loan_statement")
    await _liability(
        db_session, loan_file, liability_type="Installment", holder="ALLY FINANCIAL", payment="300"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "ALLY FINANCIAL", "monthly_payment": 300}],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1


async def test_a_value_wrapped_tradeline_row_is_read_not_crashed(db_session) -> None:
    """Rows ship bare, but the snapshot's own reader unwraps `{"value": ...}` defensively because a
    hand-written extractor could store either. Here a wrapped row handed `_normalize_creditor` a dict,
    raised AttributeError, and was swallowed into a silently disabled predicate for that file."""
    company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="lease_agreement")
    await _liability(
        db_session, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[
            {
                "creditor_name": {"value": "ALLY FINANCIAL"},
                "monthly_payment": {"value": "438.00"},
            }
        ],
    )

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 1


async def test_a_failing_predicate_leaves_the_session_usable(db_session, monkeypatch) -> None:
    """A bare `except` around a DB read is best-effort only for NON-DB errors. A SQLAlchemy error
    poisons the session, so the warning was logged and then the CALLER's commit raised
    PendingRollbackError — discarding the LP-68 match and the LP-69 needs written before it. An
    optimisation would have destroyed the work it runs after."""
    from app.services import needs_coverage
    from sqlalchemy import text

    _company, loan_file = await _flaggable_file(db_session)
    need = await _need(db_session, loan_file)

    async def _explode(db, _loan_file_id, _needs):
        await db.execute(text("SELECT * FROM a_table_that_does_not_exist"))
        return []

    monkeypatch.setattr(needs_coverage, "_PREDICATES", (_explode,))

    assert await flag_covered_needs(db_session, loan_file_id=loan_file.id) == 0
    # The session survives: the caller can still read and write, which is the whole point.
    assert await db_session.scalar(select(NeedsItem.id).where(NeedsItem.id == need.id)) == need.id


async def test_the_kill_switch_covers_the_retraction_path(db_session, monkeypatch) -> None:
    """One switch that turns off only half the flags is a switch that does not do what it says: the
    deterministic source goes quiet while the model keeps writing the same columns on every run."""
    from app.core.config import settings
    from app.services.needs_coverage import apply_retraction

    _company, loan_file = await _flaggable_file(db_session)
    need = await _need(db_session, loan_file)
    monkeypatch.setattr(settings, "needs_coverage_flagging_enabled", False)

    assert (
        await apply_retraction(db_session, need=need, why="Covered by the credit report.") is False
    )
    assert need.coverage_note is None


# --------------------------------------------------------------------------- #
# The note a processor actually reads — pinned verbatim, from the first real run
# --------------------------------------------------------------------------- #


async def test_the_note_names_the_liability_in_english(db_session) -> None:
    """LF-AWBB's first real flag read "matching the stated leasepayment liability on the
    application" — the raw MISMO token dropped into a sentence a processor is meant to check. The
    whole argument for this flag is that someone READS it; prose that reads like a formatting
    accident undermines that."""
    company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="lease_agreement")
    await _liability(
        db_session, loan_file, liability_type="LeasePayment", holder="ALLY FINANCIAL", payment="438"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[{"creditor_name": "ALLY FINANCIAL", "monthly_payment": 438}],
    )

    await flag_covered_needs(db_session, loan_file_id=loan_file.id)
    await db_session.refresh(need)
    assert need.coverage_note == (
        "The credit report lists ALLY FINANCIAL at $438/mo, matching the stated lease payment "
        "liability on the application. Fannie Mae B3-6-01 asks for separate documentation only "
        "for a liability that is NOT shown on a credit report."
    )


async def test_the_plural_note_is_grammatical(db_session) -> None:
    """The same run produced "matching every stated revolving liabilities" — `every` takes a
    singular noun."""
    company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="credit_card_statement")
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="BANK OF AMERICA", payment="25"
    )
    await _liability(
        db_session, loan_file, liability_type="Revolving", holder="SYNCB/ROOMS TO GO", payment="301"
    )
    await _credit_report(
        db_session,
        loan_file,
        company,
        tradelines=[
            {"creditor_name": "BANK OF AMERICA", "monthly_payment": 25},
            {"creditor_name": "SYNCB/ROOMS TO GO", "monthly_payment": 301},
        ],
    )

    await flag_covered_needs(db_session, loan_file_id=loan_file.id)
    await db_session.refresh(need)
    assert need.coverage_note == (
        "The credit report lists BANK OF AMERICA at $25/mo and SYNCB/ROOMS TO GO at $301/mo, "
        "matching all 2 stated revolving liabilities on the application. Fannie Mae B3-6-01 asks "
        "for separate documentation only for a liability that is NOT shown on a credit report."
    )
