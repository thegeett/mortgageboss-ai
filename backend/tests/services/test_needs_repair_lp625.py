"""LP-625 — repairing what LP-623 could only prevent.

Preventing a defect does not undo it. LP-623 stopped the floor minting a second ID need under a new
name, and stopped a recovered need keeping the sentence describing how it failed. Neither pass creates
or removes a row, so on LF-ABRS the damage stayed exactly where it was: two needs titled "Government ID
— Vidulasrri Muruganandam", one VERIFIED against the borrower's green card and one REJECTED against
their unreadable licence, and a RECEIVED W-2 need still reading "could not be processed".
"""

from __future__ import annotations

from app.models.needs_item import (
    NeedsItemStatus,
)
from app.services.needs_engine import repair_needs_for_file, transition_need
from tests.integration import factories


async def _file(db):
    company = await factories.make_company(db, slug="acme")
    return company, await factories.make_loan_file(db, company=company)


async def _need(db, loan_file, *, needs_type, status=NeedsItemStatus.PENDING, borrower_id=None):
    need = await factories.make_needs_item(db, loan_file=loan_file)
    need.needs_type = needs_type
    need.status = status
    need.borrower_id = borrower_id
    await db.flush()
    return need


async def test_the_duplicate_government_id_is_merged(db_session) -> None:
    """THE REPORTED PAIR. Two rows, one title, contradictory states — and no amount of re-running
    fixed it, because the preventive change only stops a THIRD being made."""
    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    legacy = await _need(
        db_session,
        loan_file,
        needs_type="drivers_license",
        status=NeedsItemStatus.VERIFIED,
        borrower_id=borrower.id,
    )
    minted = await _need(
        db_session,
        loan_file,
        needs_type="government_id",
        status=NeedsItemStatus.REJECTED,
        borrower_id=borrower.id,
    )

    touched = await repair_needs_for_file(db_session, loan_file.id)

    assert touched >= 1
    # The VERIFIED row survives: a need a document actually satisfied beats one still complaining.
    assert legacy.status is NeedsItemStatus.VERIFIED
    assert minted.status is NeedsItemStatus.WAIVED
    assert "Merged into the other" in (minted.reason or "")


async def test_the_furthest_along_row_wins_whichever_order_they_were_made(db_session) -> None:
    """The keeper is chosen by PROGRESS, not by age, so the outcome does not depend on which pass
    happened to run first."""
    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    older_pending = await _need(
        db_session, loan_file, needs_type="drivers_license", borrower_id=borrower.id
    )
    newer_verified = await _need(
        db_session,
        loan_file,
        needs_type="government_id",
        status=NeedsItemStatus.VERIFIED,
        borrower_id=borrower.id,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert newer_verified.status is NeedsItemStatus.VERIFIED
    assert older_pending.status is NeedsItemStatus.WAIVED


async def test_two_borrowers_ids_are_not_merged_into_one(db_session) -> None:
    """Equivalence is per BORROWER. Collapsing two borrowers' ID needs would silently drop a
    requirement — the exact failure the per-borrower key exists to prevent, arriving from the repair
    side instead."""
    _company, loan_file = await _file(db_session)
    first = await factories.make_borrower(db_session, loan_file=loan_file)
    second = await factories.make_borrower(db_session, loan_file=loan_file)
    second.borrower_position = 2
    await db_session.flush()
    a = await _need(db_session, loan_file, needs_type="government_id", borrower_id=first.id)
    b = await _need(db_session, loan_file, needs_type="government_id", borrower_id=second.id)

    await repair_needs_for_file(db_session, loan_file.id)

    assert a.status is NeedsItemStatus.PENDING
    assert b.status is NeedsItemStatus.PENDING


async def test_a_recovered_need_drops_the_failure_text_it_kept(db_session) -> None:
    """`reason` describes the STATE. A need that recovered BEFORE the clearing shipped keeps the
    sentence describing how it failed, and only re-transitions if a new document happens to arrive."""
    _company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="w2", status=NeedsItemStatus.RECEIVED)
    need.reason = "A w2 is in the file but could not be processed (needs_review)."
    await db_session.flush()

    await repair_needs_for_file(db_session, loan_file.id)

    assert need.reason is None


async def test_a_genuinely_rejected_need_keeps_its_reason(db_session) -> None:
    """The clearing must not erase a reason that still holds — a REJECTED need is exactly where the
    sentence belongs."""
    _company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="w2", status=NeedsItemStatus.REJECTED)
    need.reason = "A w2 is in the file but could not be processed (needs_review)."
    await db_session.flush()

    await repair_needs_for_file(db_session, loan_file.id)

    assert need.reason is not None


async def test_a_waived_need_keeps_its_reason(db_session) -> None:
    """A processor's waiver reason is theirs, and it is the record of why the need went away."""
    _company, loan_file = await _file(db_session)
    need = await _need(db_session, loan_file, needs_type="w2")
    await transition_need(
        db_session, need=need, to_state=NeedsItemStatus.WAIVED, reason="verified in person"
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert need.reason == "verified in person"


async def test_repairing_a_clean_file_changes_nothing(db_session) -> None:
    """Idempotent, so it is safe on every verification of a file that has nothing wrong with it."""
    _company, loan_file = await _file(db_session)
    await _need(db_session, loan_file, needs_type="appraisal")
    await _need(db_session, loan_file, needs_type="credit_report")

    assert await repair_needs_for_file(db_session, loan_file.id) == 0


async def test_an_untyped_need_is_never_merged(db_session) -> None:
    """Two needs with no type are not evidence of one duplicated need — they are two free-formed asks
    that happen to share an absence."""
    _company, loan_file = await _file(db_session)
    a = await _need(db_session, loan_file, needs_type=None)
    b = await _need(db_session, loan_file, needs_type=None)

    await repair_needs_for_file(db_session, loan_file.id)

    assert a.status is NeedsItemStatus.PENDING
    assert b.status is NeedsItemStatus.PENDING


def test_an_unmatchable_ai_need_says_a_document_cannot_close_it() -> None:
    """LF-ABRS carried two needs with `needs_type` null — "the 'Other' liability", "the unspecified
    asset". Matching keys on `needs_type`, so no upload could ever advance them, and nothing on the row
    said so. The ask is real and is kept; the row stops pretending a document will close it."""
    from app.services.needs_ai import _unmatchable_note

    note = _unmatchable_note("The borrower lists an asset with no type.")

    assert "No document type matches this request" in note
    assert "close it by hand" in note


def test_a_matchable_ai_need_gets_no_such_note() -> None:
    from app.services.needs_ai import _unmatchable_note

    assert _unmatchable_note("x", matchable=True) == "x"
