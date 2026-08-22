"""bug-001 — two needs named a document nobody can upload.

Satisfaction matches `needs_type == document_type`. `existing_mortgage_statement` and
`verification_of_employment` are declared SIMPLE-PRESENCE needs — one document is the whole
requirement — but neither string is a document type the classifier can produce, and neither is an
umbrella. The need was raised, the processor uploaded exactly the right document, and it stayed
pending forever with no way to clear it.

Both were pending on a real file WHILE THE DOCUMENT SAT IN IT: `existing_mortgage_statement` beside
an extracted `mortgage_statement`, and `verification_of_employment` beside the `voe` slug it means.
"""

from __future__ import annotations

from app.ai.extraction import EXTRACTORS
from app.services.needs_engine import (
    _NEED_TYPE_ALIASES,
    _SIMPLE_PRESENCE_NEEDS_TYPES,
    _UMBRELLA_NEED_CATEGORY,
)


def test_every_simple_presence_need_can_actually_be_satisfied() -> None:
    """The guard that would have caught this when the need type was minted, rather than on a real
    file months later. A simple-presence need must name a real document type, be an umbrella, or
    carry an alias — otherwise it is unsatisfiable by construction."""
    unsatisfiable = sorted(
        need
        for need in _SIMPLE_PRESENCE_NEEDS_TYPES
        if need not in EXTRACTORS
        and need not in _UMBRELLA_NEED_CATEGORY
        and need not in _NEED_TYPE_ALIASES
    )
    assert not unsatisfiable, (
        "These need types match no document type, no umbrella category and no alias, so uploading "
        "the right document can never clear them:\n  " + "\n  ".join(unsatisfiable)
    )


def test_each_alias_points_at_a_real_document_type() -> None:
    """An alias that is itself a typo would move the defect rather than fix it."""
    for need_type, document_type in _NEED_TYPE_ALIASES.items():
        assert document_type in EXTRACTORS, (
            f"{need_type} aliases {document_type}, which is not a document type"
        )


def test_the_two_from_the_real_file_are_aliased_to_what_the_processor_uploads() -> None:
    assert _NEED_TYPE_ALIASES["existing_mortgage_statement"] == "mortgage_statement"
    assert _NEED_TYPE_ALIASES["verification_of_employment"] == "voe"


def test_an_alias_never_shadows_a_real_document_type() -> None:
    """If a need type is BOTH a real document type and an alias, the alias is redundant at best and
    a silent redirect at worst — the document would satisfy a different need than its own."""
    shadowing = sorted(n for n in _NEED_TYPE_ALIASES if n in EXTRACTORS)
    assert not shadowing, f"aliased need types that are already real document types: {shadowing}"


# --------------------------------------------------------------------------- #
# End to end — the document a processor actually uploads clears the need.
# --------------------------------------------------------------------------- #
async def test_a_mortgage_statement_clears_the_existing_mortgage_statement_need(
    db_session,
) -> None:
    """The reported case. On the real file this need sat PENDING while an extracted
    `mortgage_statement` was already in the file."""
    from app.models.document import DocumentStatus
    from app.models.needs_item import NeedsItemStatus
    from app.services.needs_engine import apply_document_to_needs
    from tests.integration import factories

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "existing_mortgage_statement"
    doc = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="mortgage_statement",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, doc)

    assert matched is not None and matched.id == need.id
    # SIMPLE-PRESENCE: one document IS the requirement, so the match is the verification.
    assert matched.status is NeedsItemStatus.VERIFIED
    assert matched.satisfied_by_document_id == doc.id


async def test_a_voe_clears_the_verification_of_employment_need(db_session) -> None:
    from app.models.document import DocumentStatus
    from app.models.needs_item import NeedsItemStatus
    from app.services.needs_engine import apply_document_to_needs
    from tests.integration import factories

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "verification_of_employment"
    doc = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="voe",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, doc)
    assert matched is not None and matched.status is NeedsItemStatus.VERIFIED


async def test_an_unreadable_scan_still_rejects_rather_than_verifies(db_session) -> None:
    """The alias must not weaken the quality gate. On the real file the licence and one W-2 were
    image-only scans that reached `needs_review`, and their needs were REJECTED — correctly, since a
    document the extractor could not read has not satisfied anything."""
    from app.models.document import DocumentStatus
    from app.models.needs_item import NeedsItemStatus
    from app.services.needs_engine import apply_document_to_needs
    from tests.integration import factories

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    need = await factories.make_needs_item(db_session, loan_file=loan_file)
    need.needs_type = "existing_mortgage_statement"
    doc = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="mortgage_statement",
        status=DocumentStatus.NEEDS_REVIEW,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, doc)
    assert matched is not None and matched.status is NeedsItemStatus.REJECTED
