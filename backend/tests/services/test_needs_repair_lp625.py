"""LP-625 — repairing what LP-623 could only prevent.

Preventing a defect does not undo it. LP-623 stopped the floor minting a second ID need under a new
name, and stopped a recovered need keeping the sentence describing how it failed. Neither pass creates
or removes a row, so on LF-ABRS the damage stayed exactly where it was: two needs titled "Government ID
— Vidulasrri Muruganandam", one VERIFIED against the borrower's green card and one REJECTED against
their unreadable licence, and a RECEIVED W-2 need still reading "could not be processed".
"""

from __future__ import annotations

import structlog
from app.models.needs_item import (
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.services.needs_engine import (
    canonical_need_type,
    repair_needs_for_file,
    transition_need,
)
from tests.integration import factories


async def _file(db):
    company = await factories.make_company(db, slug="acme")
    return company, await factories.make_loan_file(db, company=company)


async def _need(
    db,
    loan_file,
    *,
    needs_type,
    status=NeedsItemStatus.PENDING,
    borrower_id=None,
    # FLOOR by default: every merge case here models a pair the FLOOR minted, which is the only
    # origin the repair may waive. The factory's own default is MANUAL, and a manual need is
    # deliberately out of scope — see `test_a_processors_own_need_is_never_merged_away`.
    origin=NeedsItemOrigin.FLOOR,
    disposition=NeedsItemDisposition.CONFIRMED,
):
    need = await factories.make_needs_item(db, loan_file=loan_file)
    need.needs_type = needs_type
    need.status = status
    need.borrower_id = borrower_id
    need.origin = origin
    need.disposition = disposition
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


async def test_a_processors_own_need_is_never_merged_away(db_session) -> None:
    """THE SAFETY BOUNDARY. Merging on (type, borrower) alone put a processor's own need in scope.

    The floor's `bank_statement` need is RECEIVED with a Chase statement attached; the processor adds
    "Bank statement — Wells Fargo, November" for the same borrower and the same type. RECEIVED
    outranks PENDING, so the manual row was the loser: waived, and its disposition flipped CONFIRMED
    -> WAIVED. A real requirement silently left the open list and the second statement was never
    collected. The same shape covers every legitimately multi-instance type.
    """
    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    floor_need = await _need(
        db_session,
        loan_file,
        needs_type="bank_statement",
        status=NeedsItemStatus.RECEIVED,
        borrower_id=borrower.id,
    )
    manual = await _need(
        db_session,
        loan_file,
        needs_type="bank_statement",
        status=NeedsItemStatus.PENDING,
        borrower_id=borrower.id,
        origin=NeedsItemOrigin.MANUAL,
        disposition=NeedsItemDisposition.CONFIRMED,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert manual.status is NeedsItemStatus.PENDING, (
        "a processor's need is not the floor's duplicate"
    )
    assert manual.disposition is NeedsItemDisposition.CONFIRMED
    assert floor_need.status is NeedsItemStatus.RECEIVED, "and nothing else moved either"


async def test_an_ai_proposal_is_never_merged_away(db_session) -> None:
    """Same boundary, the other non-floor origin. An AI proposal the processor confirmed is a
    decision; only the floor's own duplicate is provably redundant."""
    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    await _need(
        db_session,
        loan_file,
        needs_type="w2",
        status=NeedsItemStatus.VERIFIED,
        borrower_id=borrower.id,
    )
    proposal = await _need(
        db_session,
        loan_file,
        needs_type="w2",
        status=NeedsItemStatus.PENDING,
        borrower_id=borrower.id,
        origin=NeedsItemOrigin.AI_REASONING,
        disposition=NeedsItemDisposition.PROPOSED,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert proposal.status is NeedsItemStatus.PENDING


async def test_a_floor_duplicate_still_merges_into_a_manual_keeper(db_session) -> None:
    """The restriction is on the LOSER, not the pair. A floor row is still redundant when the row it
    duplicates happens to be the processor's — otherwise the repair would stop working the moment a
    processor touched the file."""
    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    manual = await _need(
        db_session,
        loan_file,
        needs_type="government_id",
        status=NeedsItemStatus.VERIFIED,
        borrower_id=borrower.id,
        origin=NeedsItemOrigin.MANUAL,
    )
    floor_dupe = await _need(
        db_session,
        loan_file,
        needs_type="drivers_license",
        status=NeedsItemStatus.PENDING,
        borrower_id=borrower.id,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert floor_dupe.status is NeedsItemStatus.WAIVED
    assert manual.status is NeedsItemStatus.VERIFIED


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


async def test_the_refresh_keeps_the_unmatchable_note_it_would_otherwise_strip(
    db_session, monkeypatch
) -> None:
    """A LOOP, not a one-off. The create path appends the note; the refresh path assigned
    `p.reasoning` raw and took it back off — and it fired on EVERY run, because the appended note is
    exactly what makes `stale.reasoning != p.reasoning` true. Two runs of the same proposal restored
    the state LP-625 set out to fix.
    """
    from app.services import needs_ai
    from app.services.needs_ai import ProposedNeed, ReasonedNeeds, apply_ai_needs

    _company, loan_file = await _file(db_session)
    proposal = ProposedNeed(
        need_description="Documentation for the 'Other' liability",
        need_type="other_liability_documentation",  # no catalog match — nothing can close it
        reasoning="The application lists an 'Other' liability with no supporting document.",
    )

    async def _propose(_db, _loan_file):
        return ReasonedNeeds(proposals=[proposal])

    monkeypatch.setattr(needs_ai, "propose_needs", _propose)

    created = await apply_ai_needs(db_session, loan_file)
    assert len(created) == 1
    assert "cannot clear it" in created[0].reasoning, "the create path adds the note"

    await apply_ai_needs(db_session, loan_file)  # the same proposal, one run later

    assert "cannot clear it" in created[0].reasoning, (
        "the refresh must not strip the note the create path just added"
    )


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


async def test_the_duplicate_title_need_is_merged(db_session) -> None:
    """THE SECOND REPORTED PAIR (bug-009). LF-AWBB carried two rows for ONE title search: ID-7 raised
    `title_commitment` from its `requires_documents` group, and LP-69 separately proposed
    "title_report" — a type the catalog does not define, so it canonicalised to nothing, stored raw,
    and no upload could ever clear it. A processor saw one need they could satisfy and one they
    could not, for the same document.

    Aliasing stops the pair FORMING; this merges the ones already on live files. Both are needed —
    a stored row's type is not rewritten retroactively.
    """
    _company, loan_file = await _file(db_session)
    stuck = await _need(
        db_session,
        loan_file,
        needs_type="title_report",
        status=NeedsItemStatus.PENDING,
    )
    real = await _need(
        db_session,
        loan_file,
        needs_type="title_commitment",
        status=NeedsItemStatus.RECEIVED,
    )

    assert await repair_needs_for_file(db_session, loan_file.id) >= 1

    # The row a document actually reached survives; the unclearable one is merged away.
    assert real.status is NeedsItemStatus.RECEIVED
    assert stuck.status is NeedsItemStatus.WAIVED


async def test_the_title_pair_is_merged_at_the_origin_lp69_actually_creates(db_session) -> None:
    """bug-009 REVIEW — the pair on a live file is AI_REASONING, not FLOOR.

    `_EQUIVALENT_NEED_TYPES` exists to collapse the rows already on live files, and the merge only
    waived FLOOR-origin rows. LP-69 creates its proposals with `origin=AI_REASONING`
    (`needs_ai.py`), so the `title_report` row was skipped and the repair did nothing — while a
    test using a FLOOR fixture passed. This is that test with the origin production uses.

    It matters because satisfaction matches `needs_type == document_type` on the row AS STORED:
    aliasing changes what a NEW proposal is stored as and cannot rewrite a row already on a file,
    so if the merge does not reach it, nothing does and the row sits there forever.
    """
    _company, loan_file = await _file(db_session)
    stuck = await _need(
        db_session,
        loan_file,
        needs_type="title_report",
        status=NeedsItemStatus.PENDING,
        origin=NeedsItemOrigin.AI_REASONING,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    real = await _need(
        db_session,
        loan_file,
        needs_type="title_commitment",
        status=NeedsItemStatus.RECEIVED,
        origin=NeedsItemOrigin.FLOOR,
    )

    assert await repair_needs_for_file(db_session, loan_file.id) >= 1

    assert real.status is NeedsItemStatus.RECEIVED
    assert stuck.status is NeedsItemStatus.WAIVED


async def test_a_processors_own_need_is_never_merged_even_when_unactionable(db_session) -> None:
    """The boundary of the widening above. MANUAL is still never merged, whatever its type.

    The protection exists for a processor's own ask — the floor's `bank_statement` is RECEIVED and
    they add "Bank statement, Wells Fargo, November" — and waiving that loses a real requirement.
    A mistyped manual need is something they can see and correct; it is not something to waive
    underneath them.
    """
    _company, loan_file = await _file(db_session)
    manual = await _need(
        db_session,
        loan_file,
        needs_type="title_report",
        status=NeedsItemStatus.PENDING,
        origin=NeedsItemOrigin.MANUAL,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    await _need(
        db_session,
        loan_file,
        needs_type="title_commitment",
        status=NeedsItemStatus.RECEIVED,
        origin=NeedsItemOrigin.FLOOR,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert manual.status is NeedsItemStatus.PENDING


async def test_an_actionable_duplicate_is_not_merged_by_the_new_rule(db_session) -> None:
    """The widening must not reach a type a document CAN satisfy.

    `drivers_license` is in the catalog and equivalent to `government_id`, so an AI-proposed
    `drivers_license` row is a real ask a licence upload clears. Only the FLOOR rule may merge it —
    if this starts passing through the unactionable branch, the guard has gone too wide.
    """
    _company, loan_file = await _file(db_session)
    proposed = await _need(
        db_session,
        loan_file,
        needs_type="drivers_license",
        status=NeedsItemStatus.PENDING,
        origin=NeedsItemOrigin.AI_REASONING,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    await _need(
        db_session,
        loan_file,
        needs_type="government_id",
        status=NeedsItemStatus.RECEIVED,
        origin=NeedsItemOrigin.FLOOR,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    assert proposed.status is NeedsItemStatus.PENDING


async def test_an_unsatisfiable_survivor_is_reported(db_session) -> None:
    """bug-009 REVIEW — the survivor is picked by PROGRESS, not by satisfiability, so the
    unmatchable row can win.

    A processor marked the `title_report` row received by hand, so it outranks the clearable
    `title_commitment` row and becomes the keeper. Waiving the clearable one then leaves the file
    with ONLY a need no upload can reach — the reverse order of the pair this repair was written
    for, and strictly worse than doing nothing.

    "Keep the progress OR keep the actionable row" is a false choice: RENAMING the keeper does both.
    The alias map declares the two types to be the same requirement, so the rewrite changes nothing
    about what was asked for and only changes whether a document can match it.
    """
    _company, loan_file = await _file(db_session)
    stuck = await _need(
        db_session,
        loan_file,
        needs_type="title_report",
        status=NeedsItemStatus.RECEIVED,
        origin=NeedsItemOrigin.AI_REASONING,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    clearable = await _need(
        db_session,
        loan_file,
        needs_type="title_commitment",
        status=NeedsItemStatus.PENDING,
        origin=NeedsItemOrigin.FLOOR,
    )

    await repair_needs_for_file(db_session, loan_file.id)

    # The processor's progress survives...
    assert stuck.status is NeedsItemStatus.RECEIVED
    # ...and the row it survives on is now one a document can actually match.
    assert stuck.needs_type == "title_commitment"
    assert clearable.status is NeedsItemStatus.WAIVED
    # The whole point: the file is not left with a need no upload can reach.
    assert canonical_need_type(stuck.needs_type) == stuck.needs_type


async def test_a_manual_keeper_is_reported_and_not_rewritten(db_session) -> None:
    """The one case the rename must NOT take. A MANUAL row's type is what a processor typed, and
    correcting their words underneath them is what the MANUAL guard exists to prevent — so it is
    reported instead, and the signal is pinned here so it cannot go quiet."""
    _company, loan_file = await _file(db_session)
    typed_by_hand = await _need(
        db_session,
        loan_file,
        needs_type="title_report",
        status=NeedsItemStatus.RECEIVED,
        origin=NeedsItemOrigin.MANUAL,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    await _need(
        db_session,
        loan_file,
        needs_type="title_commitment",
        status=NeedsItemStatus.PENDING,
        origin=NeedsItemOrigin.FLOOR,
    )

    with structlog.testing.capture_logs() as logs:
        await repair_needs_for_file(db_session, loan_file.id)

    assert typed_by_hand.needs_type == "title_report"
    assert any(e["event"] == "needs_merge_kept_an_unsatisfiable_row" for e in logs), (
        "the merge kept a row no document can satisfy and said nothing"
    )
