"""LP-801 — which findings may be requested from, and the one shape a request records.

Three properties, each of which was wrong in a way nothing on screen showed:

1. The consolidated unidentified-document finding cannot produce a borrower-facing request. It came
   out right before this ticket by two accidents (no spec file, so the missing-documents list was
   empty; and a `couldnt_check` filter in the row component), neither of which is a statement of the
   rule and neither of which survives someone giving the synthetic id a spec.
2. Both request paths write the SAME `details.docs_requested`. The bulk path wrote a bare `True`,
   which renders identically to the object the per-finding path writes — `Boolean(...)` is true for
   either — while carrying no link to what was actually requested.
3. The bulk path logs NEEDS_ITEM_CREATED, not FINDING_RESOLVED. Requesting documents does not resolve
   anything; the Phase 4.3 timeline is built on this log, so every bulk request read there as a
   resolution of findings that are still open.

Every negative assertion below is paired with a positive control, because "no request was created"
is also what a broken fixture produces.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.activity_log import ActivityLog, ActivityType
from app.models.finding import Finding, FindingCategory, FindingStatus
from app.models.needs_item import NeedsItem
from app.services.finding_requests import (
    NotRequestable,
    requestable,
    requested_needs_item_id,
)
from app.services.finding_resolution import request_docs_for_finding, request_documents_in_bulk
from app.verification.rule_engine.result import UNIDENTIFIED_DOCUMENTS_RULE_ID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file(db: AsyncSession):
    from app.models import User, UserRole
    from app.services.loan_files import create_loan_file

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"p-{uuid4().hex[:8]}@example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return loan_file, user.id


async def _finding(db: AsyncSession, loan_file, *, rule_id: str, subject: str = "loan") -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id=rule_id,
        message="2 documents in this file could not be identified",
        subject_key=subject,
        load_bearing_tags=[],
        status=FindingStatus.YELLOW,
        category=FindingCategory.DOCUMENTATION,
        confidence=1.0,
        details={},
    )
    db.add(finding)
    await db.flush()
    return finding


# --------------------------------------------------------------------------------------------- #
# 1. The predicate
# --------------------------------------------------------------------------------------------- #
async def test_the_consolidated_unidentified_row_is_not_requestable(
    db_session: AsyncSession,
) -> None:
    """The one exclusion. "Identify these files" is answered by typing documents already in the file;
    a request generated from it asks the borrower to re-send what they have already sent."""
    loan_file, _ = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id=UNIDENTIFIED_DOCUMENTS_RULE_ID)

    assert requestable(finding) is False


async def test_an_ordinary_rule_finding_is_requestable(db_session: AsyncSession) -> None:
    """The positive control for the predicate. Without it, `requestable` returning False for
    everything would satisfy every other test in this file."""
    loan_file, _ = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    assert requestable(finding) is True


async def test_the_single_finding_route_refuses_rather_than_creating_nothing(
    db_session: AsyncSession,
) -> None:
    """A processor standing in front of one specific finding is told why nothing happened. Silently
    creating no needs item would read on screen as a request that was made."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id=UNIDENTIFIED_DOCUMENTS_RULE_ID)

    with pytest.raises(NotRequestable):
        await request_docs_for_finding(
            db_session, loan_file=loan_file, finding=finding, actor_user_id=actor
        )

    assert "docs_requested" not in finding.details


async def test_the_bulk_route_drops_it_and_keeps_the_rest(db_session: AsyncSession) -> None:
    """ "Request all N" is a bulk verb: a member that cannot be honoured is dropped, and the ones that
    can still go through. The positive control is the second document — if the filter were dropping
    whole calls rather than members, this would be zero items instead of one."""
    loan_file, actor = await _loan_file(db_session)
    blocked = await _finding(db_session, loan_file, rule_id=UNIDENTIFIED_DOCUMENTS_RULE_ID)
    ordinary = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    created = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"identify these files": [blocked], "credit report": [ordinary]},
        actor_user_id=actor,
    )

    assert [item.title for item in created] == ["credit report"]
    assert "docs_requested" not in blocked.details
    assert "docs_requested" in ordinary.details


# --------------------------------------------------------------------------------------------- #
# 2. One shape, both paths
# --------------------------------------------------------------------------------------------- #
async def test_both_paths_write_the_same_marker_keys(db_session: AsyncSession) -> None:
    """The property the ticket exists for, asserted as a comparison rather than twice in parallel —
    two assertions of a literal shape can drift together and still both pass."""
    loan_file, actor = await _loan_file(db_session)
    single = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")
    bulk = await _finding(db_session, loan_file, rule_id="CR-13", subject="lia2")

    [item] = await request_docs_for_finding(
        db_session, loan_file=loan_file, finding=single, actor_user_id=actor
    )
    created = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"bank statement": [bulk]},
        actor_user_id=actor,
    )

    single_marker = single.details["docs_requested"]
    bulk_marker = bulk.details["docs_requested"]
    assert single_marker.keys() == bulk_marker.keys() == {"by", "at", "needs_item_id"}
    assert single_marker["needs_item_id"] == str(item.id)
    assert bulk_marker["needs_item_id"] == str(created[0].id)
    assert single_marker["by"] == bulk_marker["by"] == str(actor)


async def test_a_finding_wanting_two_documents_is_marked_once(db_session: AsyncSession) -> None:
    """`needs_item_id` is singular, so a finding contributing to two documents links the FIRST item
    rather than whichever the loop happened to reach last. Both items exist; the reverse link is
    their `reasoning`, which names the rule ids waiting on them."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    created = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"credit report": [finding], "bank statement": [finding]},
        actor_user_id=actor,
    )

    assert len(created) == 2
    assert finding.details["docs_requested"]["needs_item_id"] == str(created[0].id)


# --------------------------------------------------------------------------------------------- #
# 3. The activity type
# --------------------------------------------------------------------------------------------- #
async def test_a_bulk_request_is_logged_as_a_needs_item_not_a_resolution(
    db_session: AsyncSession,
) -> None:
    """The timeline claim. It logged FINDING_RESOLVED for an action its own docstring says does not
    resolve the finding — so asserting only "no FINDING_RESOLVED row" would pass if the function
    stopped logging entirely. The positive half is the NEEDS_ITEM_CREATED row and its link."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    created = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"credit report": [finding]},
        actor_user_id=actor,
    )

    rows = (
        (
            await db_session.execute(
                select(ActivityLog).where(ActivityLog.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    types = [row.activity_type for row in rows]
    assert ActivityType.NEEDS_ITEM_CREATED in types
    assert ActivityType.FINDING_RESOLVED not in types
    logged = next(row for row in rows if row.activity_type is ActivityType.NEEDS_ITEM_CREATED)
    assert logged.detail["needs_item_ids"] == [str(created[0].id)]

    # And the needs item really is on the file, so none of the above is asserting about an empty run.
    items = (
        (await db_session.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert [item.title for item in items] == ["credit report"]


# --------------------------------------------------------------------------------------------- #
# 4. The dedupe, which only worked for catalogued labels (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_a_second_click_does_not_duplicate_an_UNTYPED_request(
    db_session: AsyncSession,
) -> None:
    """The docstring's promise — "a second click must not produce a second copy" — held only when the
    document label happened to be in the catalog.

    `canonical_need_type` returns None for a label it does not carry, which is EVERY sentence coming
    through LP-620's `requested_documents` channel, including the "One more source stating the ..."
    this ticket rewrote. The dedupe compared the raw slug against the `needs_type` of open needs, and
    an untyped need has no `needs_type` to compare, so it never matched itself. Measured before the
    fix: two items for one ask.
    """
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="ID-2", subject="b1")
    document = "One more source stating the date of birth"

    first = await request_documents_in_bulk(
        db_session, loan_file=loan_file, by_document={document: [finding]}, actor_user_id=actor
    )
    second = await request_documents_in_bulk(
        db_session, loan_file=loan_file, by_document={document: [finding]}, actor_user_id=actor
    )

    assert [item.title for item in first] == [document]
    assert first[0].needs_type is None  # the condition that defeated the old key
    assert second == []
    total = (
        (await db_session.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert len(total) == 1


async def test_a_second_click_does_not_duplicate_an_ALIASED_request(
    db_session: AsyncSession,
) -> None:
    """The other half the old key missed. `canonical_need_type` ALIASES — a
    `verification_of_employment` label is stored as `voe` — so the raw slug never matched the type it
    had just been stored under, and the second click duplicated it too."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="IN-8", subject="emp1")

    first = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"verification of employment": [finding]},
        actor_user_id=actor,
    )
    second = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"verification of employment": [finding]},
        actor_user_id=actor,
    )

    assert len(first) == 1
    assert first[0].needs_type != "verification_of_employment"  # it aliased
    assert second == []


async def test_a_catalogued_label_still_dedupes(db_session: AsyncSession) -> None:
    """The positive control, and the case that always worked — kept so a fix that broke the ordinary
    path could not pass by making everything look like a duplicate."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    first = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"credit report": [finding]},
        actor_user_id=actor,
    )
    second = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={"credit report": [finding]},
        actor_user_id=actor,
    )

    assert [item.needs_type for item in first] == ["credit_report"]
    assert second == []


async def test_two_different_documents_are_both_created(db_session: AsyncSession) -> None:
    """The second positive control: the new key must not collapse DISTINCT asks. Two untyped
    sentences share `needs_type is None`, so keying on the type alone would have made the second one
    look like a duplicate of the first."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="ID-2", subject="b1")

    created = await request_documents_in_bulk(
        db_session,
        loan_file=loan_file,
        by_document={
            "One more source stating the date of birth": [finding],
            "One more source stating the current address": [finding],
        },
        actor_user_id=actor,
    )

    assert len(created) == 2
    assert all(item.needs_type is None for item in created)


# --------------------------------------------------------------------------------------------- #
# 5. Reading the marker back, across both shapes (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_the_marker_reads_back_from_the_new_shape(db_session: AsyncSession) -> None:
    """The forward link LP-810 follows, on a row this build wrote."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    [item] = await request_docs_for_finding(
        db_session, loan_file=loan_file, finding=finding, actor_user_id=actor
    )

    assert requested_needs_item_id(finding) == item.id


async def test_the_marker_reads_back_as_None_from_the_PRE_LP801_shape(
    db_session: AsyncSession,
) -> None:
    """The bare `True` every bulk request wrote before this ticket. It still means "documents were
    requested" — the key is present — but there is no needs item to follow, and reaching into it
    positionally raises rather than returning nothing."""
    loan_file, _ = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")
    finding.details = {**finding.details, "docs_requested": True}

    assert requested_needs_item_id(finding) is None
    assert "docs_requested" in finding.details  # still the "was requested" signal
    with pytest.raises(TypeError):
        _ = finding.details["docs_requested"]["needs_item_id"]  # type: ignore[index]


async def test_the_marker_reads_back_as_None_when_never_requested(
    db_session: AsyncSession,
) -> None:
    """The negative control — an unrequested finding and an old-shape one must not be confused by a
    reader that only checks for None."""
    loan_file, _ = await _loan_file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="CR-6", subject="lia1")

    assert requested_needs_item_id(finding) is None
    assert "docs_requested" not in finding.details
