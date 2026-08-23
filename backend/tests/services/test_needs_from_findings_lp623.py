"""LP-623 — the Need List learns what the rules already found.

On LF-ABRS the Need List carried thirteen items and NOT ONE was the appraisal, the title commitment,
the credit report, the rate lock or the Closing Disclosure — while ten findings said each was absent.
A processor working that list to zero would have submitted a file with no appraisal, no title and no
credit report.
"""

from __future__ import annotations

import pytest
from app.models.document import DocumentStatus
from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.needs_item import (
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)
from app.services.needs_engine import (
    _GOVERNMENT_ID_DOCUMENTS,
    apply_document_to_needs,
    rematch_needs_for_file,
)
from app.services.needs_from_findings import seed_needs_from_findings
from tests.integration import factories


async def _file(db):
    company = await factories.make_company(db, slug="acme")
    return company, await factories.make_loan_file(db, company=company)


async def _finding(
    db,
    loan_file,
    *,
    rule_id,
    outcome=EvaluationOutcome.COULDNT_CHECK,
    status=FindingStatus.YELLOW,
):
    """A governed rule finding. Built directly rather than via a factory — there is none for
    findings, and the fields that matter here (rule_id, outcome, resolution) are exactly the ones a
    generic factory would have to be told anyway."""
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id=rule_id,
        status=status,
        category=FindingCategory.DOCUMENTATION,
        message=f"{rule_id} could not complete",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        evaluation_outcome=outcome,
        resolution_status=FindingResolutionStatus.OPEN,
    )
    db.add(finding)
    await db.flush()
    return finding


async def test_a_rule_waiting_on_a_document_puts_it_on_the_need_list(db_session) -> None:
    """THE REPORTED GAP. MI-1 and PR-6 both say the appraisal is absent; the list never said so."""
    _company, loan_file = await _file(db_session)
    await _finding(db_session, loan_file, rule_id="MI-1")

    created = await seed_needs_from_findings(db_session, loan_file)

    assert [n.needs_type for n in created] == ["appraisal"]
    need = created[0]
    # CONFIRMED, not PROPOSED — a rule declaring a document and the file not holding one is
    # deterministic, the same standing as a floor need. Making a processor confirm that the appraisal
    # is really needed is the click this exists to remove.
    assert need.disposition is NeedsItemDisposition.CONFIRMED
    assert need.origin is NeedsItemOrigin.FINDING
    assert need.category is not None, "a seeded need must be groupable"
    assert "MI-1" in (need.reasoning or "")


async def test_many_findings_wanting_one_document_make_one_need(db_session) -> None:
    """Four credit-report findings are ONE errand. Per-finding needs would put four near-duplicate
    lines on a shopping list, which is the shape LP-562 removed from the request button."""
    _company, loan_file = await _file(db_session)
    for rule_id in ("CR-4", "CR-8", "CR-10"):
        await _finding(db_session, loan_file, rule_id=rule_id)

    created = await seed_needs_from_findings(db_session, loan_file)

    credit = [n for n in created if n.needs_type == "credit_report"]
    assert len(credit) == 1
    reasoning = credit[0].reasoning or ""
    for rule_id in ("CR-4", "CR-8", "CR-10"):
        assert rule_id in reasoning, "the need must name every rule waiting on it"


async def test_a_document_already_on_file_is_not_requested(db_session) -> None:
    """The rule's declaration is a PRESENCE test — a group with a member on the file is satisfied, and
    asking for what is already here is the errand this must never generate."""
    company, loan_file = await _file(db_session)
    await _finding(db_session, loan_file, rule_id="MI-1")
    await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="appraisal",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    created = await seed_needs_from_findings(db_session, loan_file)

    assert [n.needs_type for n in created] == []


async def test_running_twice_creates_nothing_new(db_session) -> None:
    """IDEMPOTENCE IS WHAT MAKES IT SAFE ON EVERY VERIFICATION. A second run must not double the list."""
    _company, loan_file = await _file(db_session)
    await _finding(db_session, loan_file, rule_id="MI-1")

    first = await seed_needs_from_findings(db_session, loan_file)
    second = await seed_needs_from_findings(db_session, loan_file)

    assert len(first) == 1
    assert second == []


async def test_a_satisfied_rule_asks_for_nothing(db_session) -> None:
    """A need appears only because a rule IN SCOPE reported a gap. A rule that passed is not waiting."""
    _company, loan_file = await _file(db_session)
    await _finding(db_session, loan_file, rule_id="MI-1", outcome=EvaluationOutcome.SATISFIED)

    assert await seed_needs_from_findings(db_session, loan_file) == []


async def test_a_resolved_finding_asks_for_nothing(db_session) -> None:
    """A processor who overrode or waived a finding has answered it; re-raising the document as a need
    would put their own dismissal back on their list."""
    _company, loan_file = await _file(db_session)
    finding = await _finding(db_session, loan_file, rule_id="MI-1")
    finding.resolution_status = FindingResolutionStatus.OVERRIDDEN
    await db_session.flush()

    assert await seed_needs_from_findings(db_session, loan_file) == []


async def test_a_red_finding_makes_the_need_blocking(db_session) -> None:
    """The document inherits the severity of the worst reason it is wanted for."""
    _company, loan_file = await _file(db_session)
    await _finding(db_session, loan_file, rule_id="MI-1", status=FindingStatus.RED)

    created = await seed_needs_from_findings(db_session, loan_file)

    assert created[0].priority is NeedsItemPriority.BLOCKING


async def test_in13_no_longer_asks_for_a_social_security_award_letter(db_session) -> None:
    """IN-13 covers ALL "other" income and declared only three award-letter types, so every one of its
    findings asked for a Social Security award letter — including LF-ABRS's, which is about
    CONTRACT-BASIS income on a file stating no Social Security income anywhere. A group names its
    FIRST member as the ask, so a heterogeneous group cannot be declared at all."""
    _company, loan_file = await _file(db_session)
    await _finding(db_session, loan_file, rule_id="IN-13")

    created = await seed_needs_from_findings(db_session, loan_file)

    assert [n.needs_type for n in created] == []


# --------------------------------------------------------------------------------------------- #
# Re-matching over documents already on the file
# --------------------------------------------------------------------------------------------- #
async def test_a_document_that_arrived_before_the_rule_changed_still_clears_its_need(
    db_session,
) -> None:
    """THE bug-001 TAIL. Matching fires once, on arrival, so the alias shipped after LF-ABRS's mortgage
    statement was uploaded and the need sat PENDING beside the document that answers it — forever,
    because nothing ever re-evaluates."""
    company, loan_file = await _file(db_session)
    document = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="mortgage_statement",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()
    # The need is minted AFTER the document, so arrival-time matching never saw it.
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "existing_mortgage_statement"
    need.status = NeedsItemStatus.PENDING
    await db_session.flush()

    advanced = await rematch_needs_for_file(db_session, loan_file.id)

    assert [n.id for n in advanced] == [need.id]
    assert need.status is NeedsItemStatus.VERIFIED
    assert need.satisfied_by_document_id == document.id


async def test_rematching_a_settled_file_changes_nothing(db_session) -> None:
    """Idempotent, so it costs a query and nothing else on every verification of a settled file."""
    company, loan_file = await _file(db_session)
    document = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="mortgage_statement",
        status=DocumentStatus.COMPLETED,
    )
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "existing_mortgage_statement"
    await db_session.flush()
    await apply_document_to_needs(db_session, document)

    assert await rematch_needs_for_file(db_session, loan_file.id) == []


# --------------------------------------------------------------------------------------------- #
# A rejected need must not strand a good document
# --------------------------------------------------------------------------------------------- #
async def test_a_good_document_clears_a_need_a_bad_one_already_rejected(db_session) -> None:
    """LF-ABRS carried TWO W-2s — one COMPLETED, one NEEDS_REVIEW. The bad one claimed the need, the
    need went REJECTED, and REJECTED was not an open state, so the good W-2 that followed matched
    nothing: the list reported "did not pass processing" beside a perfectly usable document and a
    processor would re-ask the borrower for what they already had."""
    company, loan_file = await _file(db_session)
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "w2"
    await db_session.flush()

    unreadable = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="w2",
        status=DocumentStatus.NEEDS_REVIEW,
    )
    await db_session.flush()
    await apply_document_to_needs(db_session, unreadable)
    assert need.status is NeedsItemStatus.REJECTED

    good = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="w2",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, good)

    assert matched is not None and matched.id == need.id
    # RECEIVED, not VERIFIED: `w2` is a GRADED need (LP-108) — one document does not prove the full
    # requirement, so the processor confirms coverage. What matters here is that it left REJECTED at
    # all, which it could not do before.
    assert need.status is NeedsItemStatus.RECEIVED
    assert need.satisfied_by_document_id == good.id


async def test_the_rejected_reason_sends_the_processor_for_a_clean_copy(db_session) -> None:
    """ "Rejected" reads as "the borrower sent the wrong thing", and the errand that implies — ask
    again — is the wrong one. The document is IN the file; what is needed is a legible copy."""
    company, loan_file = await _file(db_session)
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "drivers_license"
    await db_session.flush()
    unreadable = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="drivers_license",
        status=DocumentStatus.NEEDS_REVIEW,
    )
    await db_session.flush()

    await apply_document_to_needs(db_session, unreadable)

    reason = need.reason or ""
    assert "in the file" in reason
    assert "clean, legible copy" in reason
    assert "re-request" in reason


# --------------------------------------------------------------------------------------------- #
# The floor was frozen at MISMO import
# --------------------------------------------------------------------------------------------- #
async def test_a_borrower_added_after_import_gets_their_own_id_need(db_session) -> None:
    """THE ONE-SHOT DEFECT. The guard asked "does this file have ANY floor need" and bailed, so the
    per-borrower loop only ever saw the borrowers who existed at import. A co-borrower added
    afterwards never got a Government ID — and the AI half, asked what is DISTINCTIVE about a file,
    is the least likely thing to propose one."""
    from app.services.needs_engine import seed_floor_needs

    _company, loan_file = await _file(db_session)
    first = await factories.make_borrower(db_session, loan_file=loan_file)
    await db_session.flush()
    seeded = await seed_floor_needs(db_session, loan_file)
    assert [n.borrower_id for n in seeded if n.needs_type == "government_id"] == [first.id]

    second = await factories.make_borrower(db_session, loan_file=loan_file)
    second.borrower_position = 2
    await db_session.flush()

    again = await seed_floor_needs(db_session, loan_file)

    assert [n.borrower_id for n in again if n.needs_type == "government_id"] == [second.id], (
        "the co-borrower must get their OWN ID need — a file-level type check would read the "
        "primary's need as covering them"
    )


async def test_re_deriving_the_floor_creates_no_duplicates(db_session) -> None:
    """Idempotence moved from per FILE to per NEED, so it has to still hold: running twice on an
    unchanged file must add nothing."""
    from app.services.needs_engine import seed_floor_needs

    _company, loan_file = await _file(db_session)
    await factories.make_borrower(db_session, loan_file=loan_file)
    await db_session.flush()

    first = await seed_floor_needs(db_session, loan_file)
    second = await seed_floor_needs(db_session, loan_file)

    assert first != []
    assert second == []


async def test_the_floor_never_resurrects_a_waived_need(db_session) -> None:
    """A processor who waived a need has answered it. Re-deriving must not put their own dismissal
    back on their list — which is why the match is against every need in ANY status, not the open
    ones."""
    from app.models.needs_item import NeedsItemStatus
    from app.services.needs_engine import seed_floor_needs, waive_need

    _company, loan_file = await _file(db_session)
    await factories.make_borrower(db_session, loan_file=loan_file)
    await db_session.flush()
    seeded = await seed_floor_needs(db_session, loan_file)
    ident = next(n for n in seeded if n.needs_type == "government_id")
    await waive_need(db_session, need=ident, reason="ID already verified in person")
    assert ident.status is NeedsItemStatus.WAIVED

    again = await seed_floor_needs(db_session, loan_file)

    assert [n.needs_type for n in again] == []


async def test_the_floor_does_not_duplicate_what_another_source_already_raised(db_session) -> None:
    """The floor matches against every need on the file, not only its own — so a type another origin
    already raised FOR THIS BORROWER is not raised a second time under a different origin."""
    from app.models.needs_item import NeedsItemOrigin as Origin
    from app.services.needs_engine import seed_floor_needs

    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    prior = await factories.make_needs_item(db_session, loan_file=loan_file)
    prior.needs_type = "government_id"
    prior.borrower_id = borrower.id
    prior.origin = Origin.AI_REASONING
    await db_session.flush()

    seeded = await seed_floor_needs(db_session, loan_file)

    assert "government_id" not in [n.needs_type for n in seeded]


async def test_an_unattributed_id_need_does_not_cover_a_specific_borrower(db_session) -> None:
    """DELIBERATE, and the reason the per-borrower key includes the borrower. An ID need attached to
    NO borrower cannot establish that a particular borrower's ID is covered — on a two-borrower file
    one unattributed line would silently satisfy both. Cross-origin near-duplicates like this are
    LP-111's consolidation pass to reconcile, not something to paper over by loosening the key."""
    from app.models.needs_item import NeedsItemOrigin as Origin
    from app.services.needs_engine import seed_floor_needs

    _company, loan_file = await _file(db_session)
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    prior = await factories.make_needs_item(db_session, loan_file=loan_file)
    prior.needs_type = "government_id"
    prior.borrower_id = None
    prior.origin = Origin.AI_REASONING
    await db_session.flush()

    seeded = await seed_floor_needs(db_session, loan_file)

    attributed = [n for n in seeded if n.needs_type == "government_id"]
    assert [n.borrower_id for n in attributed] == [borrower.id]


async def test_an_aliased_need_already_on_the_list_is_not_raised_again(db_session) -> None:
    """CAUGHT BY TRACING LF-ABRS BEFORE DEPLOY. The file carries an AI need stored as
    `verification_of_employment` while IN-4 and IN-8 declare `voe` — the same document under two
    names. Compared raw, neither suppresses the other and the list grows a second line for one
    errand. The matcher has forgiven this alias since bug-001; seeding has to ask the same question
    earlier."""
    _company, loan_file = await _file(db_session)
    prior = await factories.make_needs_item(db_session, loan_file=loan_file)
    prior.needs_type = "verification_of_employment"
    await db_session.flush()
    await _finding(db_session, loan_file, rule_id="IN-8")

    created = await seed_needs_from_findings(db_session, loan_file)

    assert [n.needs_type for n in created] == [], (
        "a VOE is already on the list under its other name — asking again is one errand, two lines"
    )


# --------------------------------------------------------------------------------------------- #
# "Government ID" is not a driver's licence
# --------------------------------------------------------------------------------------------- #
async def test_a_permanent_resident_card_satisfies_the_government_id_need(db_session) -> None:
    """THE REPORTED CASE. LF-ABRS's borrower holds a permanent resident card — an unexpired
    government-issued photo ID — and the need, typed `drivers_license` because that is the one slug
    the floor happened to name, sat REJECTED beside it. The processor is told to chase an ID that is
    already in the file."""
    from app.services.needs_engine import seed_floor_needs

    company, loan_file = await _file(db_session)
    await factories.make_borrower(db_session, loan_file=loan_file)
    await db_session.flush()
    seeded = await seed_floor_needs(db_session, loan_file)
    ident = next(n for n in seeded if n.needs_type == "government_id")

    card = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="permanent_resident_card",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, card)

    assert matched is not None and matched.id == ident.id
    assert ident.status is NeedsItemStatus.VERIFIED


@pytest.mark.parametrize("document_type", sorted(_GOVERNMENT_ID_DOCUMENTS))
async def test_every_kind_of_government_id_answers_the_need(db_session, document_type) -> None:
    """One ID is the whole requirement, whichever kind it is — so each alternative must clear it on its
    own, not merely be listed. Parametrized rather than looped so a type that stops working names
    itself instead of failing the set."""
    from app.services.needs_engine import seed_floor_needs

    company = await factories.make_company(db_session, slug=f"acme-{document_type}")
    loan_file = await factories.make_loan_file(db_session, company=company)
    await factories.make_borrower(db_session, loan_file=loan_file)
    await db_session.flush()
    seeded = await seed_floor_needs(db_session, loan_file)
    ident = next(n for n in seeded if n.needs_type == "government_id")

    document = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    await apply_document_to_needs(db_session, document)

    assert ident.status is NeedsItemStatus.VERIFIED, f"{document_type} did not clear the ID need"


async def test_a_divorce_decree_does_not_clear_the_government_id_need(db_session) -> None:
    """The guard on the mechanism. An umbrella CATEGORY was the tempting fix and would have let any
    BORROWER_INFO document through — the category also holds divorce decrees, marriage certificates,
    trust agreements and eight kinds of letter of explanation."""
    from app.services.needs_engine import seed_floor_needs

    company, loan_file = await _file(db_session)
    await factories.make_borrower(db_session, loan_file=loan_file)
    await db_session.flush()
    seeded = await seed_floor_needs(db_session, loan_file)
    ident = next(n for n in seeded if n.needs_type == "government_id")

    decree = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="divorce_decree",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    assert await apply_document_to_needs(db_session, decree) is None
    assert ident.status is NeedsItemStatus.PENDING


async def test_an_id_need_already_raised_under_the_old_name_still_clears(db_session) -> None:
    """Every ID need on a live file is stored as `drivers_license`, and a stored row cannot be renamed
    retroactively — so the old name keeps working and accepts the same alternatives. Without this,
    fixing the type would have STRANDED every ID need already on every file."""
    company, loan_file = await _file(db_session)
    legacy = await factories.make_needs_item(db_session, loan_file=loan_file)
    legacy.needs_type = "drivers_license"
    await db_session.flush()

    passport = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="passport",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, passport)

    assert matched is not None and matched.id == legacy.id
    assert legacy.status is NeedsItemStatus.VERIFIED
