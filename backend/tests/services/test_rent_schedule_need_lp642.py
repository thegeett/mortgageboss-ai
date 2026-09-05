"""LP-642 review — the seeded rent-schedule need must be clearable by uploading the document.

THE FAILURE SHAPE THIS GUARDS. A need is satisfied by matching `needs_type == document_type` on the
row as stored. Seed a need whose type no document can ever carry and it sits on a processor's list
forever, unclearable by the very upload it asks for — bug-001 and bug-009 both, twice over.

The new types are Tier 2 with no extractor, which is the right call (Tier 1 would claim an extractor
that does not exist), and it is also exactly the property worth pinning: nothing in `needs_engine`
reads a tier, so a Tier 2 type satisfies like any other. That is true today by absence rather than
by design, so it is asserted here rather than assumed.
"""

from __future__ import annotations

from app.documents.catalog import CATALOG
from app.models.document import DocumentStatus
from app.models.needs_item import NeedsItemStatus
from app.services.needs_engine import apply_document_to_needs, canonical_need_type
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

_FORMS = ("comparable_rent_schedule", "small_residential_income_appraisal")


def test_both_rent_schedule_types_are_types_a_document_can_carry() -> None:
    """The cheap half: a need type absent from the catalog is unsatisfiable by construction."""
    for slug in _FORMS:
        assert slug in CATALOG, f"{slug} is seeded as a need but is not a document type"
        assert canonical_need_type(slug) == slug


async def test_uploading_the_form_clears_the_need_it_was_asked_for(
    db_session: AsyncSession,
) -> None:
    """THE HALF THAT MATTERS, at the layer a processor sees. Asserting the type is in the catalog
    proves it can be classified; it does not prove the need closes. Both forms are Tier 2 with no
    extractor, and this is what says that does not matter."""
    for slug in _FORMS:
        company = await factories.make_company(db_session, slug=f"acme-{slug[:8]}")
        loan_file = await factories.make_loan_file(db_session, company=company)
        need = await factories.make_needs_item(db_session, loan_file=loan_file)
        need.needs_type = slug
        need.status = NeedsItemStatus.PENDING
        document = await factories.make_document(
            db_session,
            loan_file=loan_file,
            company=company,
            document_type=slug,
            status=DocumentStatus.COMPLETED,
        )
        await db_session.flush()

        matched = await apply_document_to_needs(db_session, document)

        assert matched is not None and matched.id == need.id, f"{slug} did not clear its own need"
        assert matched.status is not NeedsItemStatus.PENDING, (
            f"{slug} matched but left the need pending"
        )


async def test_what_the_SEEDER_emits_is_a_type_a_document_can_carry(
    db_session: AsyncSession,
) -> None:
    """THE LINK THE TWO TESTS ABOVE LEAVE OPEN, and it is the one a typo travels through.

    The first asserts a hardcoded pair of slugs is in the catalog. The second builds the need by
    setting `needs_type` directly. Neither runs `seed_floor_needs`, so neither sees what the SEEDER
    actually emits — and a slug misspelled there produces exactly the defect this file exists to
    prevent: a need on a processor's list that no upload can clear. Verified by mutation: renaming the
    seeder's slug to `comparable_rent_schedule_typo` leaves both of the above green.

    So this drives the real path end to end — seed, then upload, then assert it closed — and reads
    the type off the seeded row rather than from a constant, because a constant is the thing that
    agrees with itself.
    """
    from app.models.property import OccupancyType
    from app.services.needs_engine import seed_floor_needs

    company = await factories.make_company(db_session, slug="acme-seeded")
    loan_file = await factories.make_loan_file(db_session, company=company)
    prop = await factories.make_property(db_session, loan_file=loan_file)
    prop.occupancy_type = OccupancyType.INVESTMENT
    prop.financed_unit_count = 1
    await db_session.flush()

    await seed_floor_needs(db_session, loan_file)
    await db_session.flush()

    seeded = [n for n in await _needs_on(db_session, loan_file) if n.needs_type in _FORMS]
    assert len(seeded) == 1, "an investment subject seeds exactly one rent-schedule need"
    slug = seeded[0].needs_type
    assert slug in CATALOG, f"the seeder emitted {slug!r}, which no document can be classified as"

    document = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type=slug,
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, document)
    assert matched is not None and matched.id == seeded[0].id, (
        f"uploading a {slug} did not clear the need the seeder asked for"
    )


async def _needs_on(db: AsyncSession, loan_file):
    from app.models.helpers import only_active
    from app.models.needs_item import NeedsItem
    from sqlalchemy import select

    return (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id), NeedsItem)
        )
    ).all()
