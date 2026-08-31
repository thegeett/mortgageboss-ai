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
    _NEED_ALTERNATIVES,
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
        # LP-623 — the fourth way a need can be satisfiable: a named set of ALTERNATIVES, any one of
        # which answers it. `government_id` is not a document type and never will be; a passport, a
        # licence, a military ID or a green card each provide it.
        and need not in _NEED_ALTERNATIVES
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


# --------------------------------------------------------------------------- #
# LP-623 — alternatives
# --------------------------------------------------------------------------- #
def test_every_alternative_is_a_real_document_type() -> None:
    """An alternative that is itself a typo can never be uploaded, which is bug-001's defect wearing a
    new hat.

    Checked against the CATALOG rather than EXTRACTORS, and the difference matters: 42 of the 163
    catalog types have no extractor, and `EXTRACTORS.get(document.document_type)` is looked up AFTER
    classification — so a document CAN be classified `military_id` and simply take the generic
    extraction path. Requiring an extractor here would drop a veteran's military ID from the documents
    that answer "Government ID" for no reason that has anything to do with identity."""
    from app.documents.catalog import CATALOG

    for need_type, documents in _NEED_ALTERNATIVES.items():
        unknown = sorted(d for d in documents if d not in CATALOG)
        assert not unknown, f"{need_type} accepts {unknown}, which are not document types"


def test_a_government_id_is_not_satisfied_by_any_borrower_info_document() -> None:
    """The mechanism that already existed — an umbrella CATEGORY — is wrong for identity: BORROWER_INFO
    also holds divorce decrees, marriage certificates, trust agreements and eight kinds of letter of
    explanation. Named alternatives are what keep a divorce decree from clearing an ID requirement."""
    assert "government_id" not in _UMBRELLA_NEED_CATEGORY
    for not_an_id in ("divorce_decree", "marriage_certificate", "letter_of_explanation"):
        assert not_an_id not in _NEED_ALTERNATIVES["government_id"]


# --------------------------------------------------------------------------- #
# bug-009 — the title pair
# --------------------------------------------------------------------------- #
def test_every_alias_target_is_a_real_document_type() -> None:
    """The same guard as above, aimed at the ALIAS map. An alias is a promise that the target is
    something a processor can actually upload; pointing one at a type the catalog does not define
    would turn every aliased need permanently unclearable — bug-001's defect, laundered through the
    map that exists to prevent it."""
    from app.documents.catalog import CATALOG
    from app.services.needs_engine import _NEED_TYPE_ALIASES

    for source, target in _NEED_TYPE_ALIASES.items():
        assert target in CATALOG or target in _NEED_ALTERNATIVES, (
            f"{source} aliases to {target}, which no document can satisfy"
        )


def test_a_proposed_title_report_is_stored_as_the_type_the_catalog_defines() -> None:
    """LP-69 proposes "title_report". The catalog carries `title_commitment` and
    `preliminary_title_report` and not that, so the proposal used to fail canonicalisation and get
    stored raw — leaving a need beside ID-7's `title_commitment` for the same title search, and no
    upload that could clear it.

    `title_commitment` and not `preliminary_title_report` because that is what ID-7's own
    `requires_documents` group names first.
    """
    from app.services.needs_engine import canonical_need_type

    assert canonical_need_type("title_report") == "title_commitment"


async def test_the_title_row_a_processor_kept_can_be_cleared_by_an_upload(db_session) -> None:
    """bug-009 at the layer the defect was actually visible: an upload that does not clear the need.

    Everything else about this fix is tested one layer down — the alias resolves, the merge collapses
    the pair, the keeper is renamed. None of that is what a processor sees. What they saw is a title
    need still sitting open with the title commitment already in the file, because satisfaction
    matches `needs_type == document_type` on the row AS STORED and `title_report` is not a document
    type.

    So this drives the whole path: the unmatchable row is the further-along one, survives the merge,
    gets renamed, and THEN the document clears it.

    REJECTED for the keeper, not RECEIVED, and the distinction is the point rather than a fixture
    detail. RECEIVED is not an OPEN state — a row with a document already attached is deliberately
    not re-matched, so it could not demonstrate anything about uploads. REJECTED outranks PENDING on
    `_PROGRESS_RANK` (3 vs 1) AND is still open, which is exactly the shape where the rename decides
    whether the processor's next upload lands: a title commitment came in, was rejected as illegible,
    and the replacement is on its way.
    """
    from app.models.document import DocumentStatus
    from app.models.needs_item import NeedsItemOrigin, NeedsItemStatus
    from app.services.needs_engine import apply_document_to_needs, repair_needs_for_file
    from tests.integration import factories

    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)

    stuck = await factories.make_needs_item(db_session, loan_file=loan_file)
    stuck.needs_type = "title_report"
    stuck.status = NeedsItemStatus.REJECTED
    stuck.origin = NeedsItemOrigin.AI_REASONING
    clearable = await factories.make_needs_item(db_session, loan_file=loan_file)
    clearable.needs_type = "title_commitment"
    clearable.status = NeedsItemStatus.PENDING
    clearable.origin = NeedsItemOrigin.FLOOR
    await db_session.flush()

    await repair_needs_for_file(db_session, loan_file.id)

    doc = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="title_commitment",
        status=DocumentStatus.COMPLETED,
    )
    await db_session.flush()

    matched = await apply_document_to_needs(db_session, doc)

    # Before the fix this matched the WAIVED row or nothing at all, and the open need stayed open.
    assert matched is not None and matched.id == stuck.id
    assert matched.status is NeedsItemStatus.VERIFIED
    assert clearable.status is NeedsItemStatus.WAIVED
