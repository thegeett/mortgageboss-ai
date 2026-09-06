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

import pytest
from app.ai.extraction import EXTRACTORS
from app.documents.catalog import CATALOG
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
    """An alias that is itself a typo would move the defect rather than fix it — so every target
    must be something a processor can actually upload.

    CHECKED AGAINST THE CATALOG, NOT `EXTRACTORS`, for the reason spelled out above: 42 of the 163
    catalog types have no extractor, and `EXTRACTORS.get(...)` is consulted only AFTER
    classification, so a Tier-2 type is classified and filed and takes the generic path. Requiring an
    extractor here would reject `installment_loan_statement` — a real, classifiable document and the
    correct target for `installment_statement` — for a reason that has nothing to do with whether an
    upload can clear the need.
    """
    from app.documents.catalog import CATALOG

    for need_type, document_type in _NEED_TYPE_ALIASES.items():
        assert (
            document_type in CATALOG
            or document_type in _UMBRELLA_NEED_CATEGORY
            or document_type in _NEED_ALTERNATIVES
        ), f"{need_type} aliases {document_type}, which no document can satisfy"


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


# --------------------------------------------------------------------------- #
# bug-009 — the reasoner is told which types exist, instead of inventing them
# --------------------------------------------------------------------------- #
def test_the_reasoning_prompt_lists_only_types_a_document_can_satisfy() -> None:
    """THE ROOT CAUSE, not another symptom.

    The prompt used to say "use a concise lowercase snake_case need_type when an obvious document
    type fits" and give four examples. So the model invented plausible names for types that do not
    exist, and because satisfaction matches `needs_type == document_type`, each became a row on a
    real file that no upload could ever clear. Six of them were live on staging at once
    (`title_report`, `credit_card_statement`, `investment_statement`, `retirement_statement`,
    `property_tax_statement`, `credit_authorization`) across eight open needs — every one found by a
    person noticing it, one at a time.

    The classifier already had the answer: render the type list FROM the catalog so the prompt and
    the catalog cannot drift. Aliases patch the rows that exist; this stops the next name being
    invented.
    """
    from app.services.needs_ai import _render_reasoning_prompt
    from app.services.needs_engine import canonical_need_type, satisfiable_need_types

    rendered = _render_reasoning_prompt()
    assert "{satisfiable_need_types}" not in rendered, "the placeholder was never filled"

    listed = satisfiable_need_types()
    assert listed, "the prompt would offer the model no types at all"
    # Every type offered must resolve, or the prompt is inviting the defect it exists to prevent.
    unsatisfiable = sorted(t for t in listed if canonical_need_type(t) is None)
    assert not unsatisfiable, f"the prompt offers types nothing can satisfy: {unsatisfiable}"

    # And the list must actually reach the model.
    for slug in ("credit_card_statement", "title_commitment", "government_id"):
        assert f"  {slug}\n" in rendered, f"{slug} is satisfiable but not offered"


def test_the_six_invented_names_all_resolve_now() -> None:
    """The names the model actually produced on staging. Pinned individually rather than as a set,
    so a regression names the one that broke."""
    from app.services.needs_engine import canonical_need_type

    assert canonical_need_type("title_report") == "title_commitment"
    assert canonical_need_type("credit_authorization") == "authorization_to_run_credit"
    assert canonical_need_type("installment_statement") == "installment_loan_statement"
    # REVIEW CHANGE: these two resolve to THEMSELVES, as `_NEED_ALTERNATIVES` heads, rather
    # than to one twin of an interchangeable pair. Pinning the alias target is what made the
    # alias look correct while it only cleared the need when the classifier picked that twin.
    assert canonical_need_type("investment_statement") == "investment_statement"
    assert canonical_need_type("retirement_statement") == "retirement_statement"
    assert canonical_need_type("property_tax_statement") == "property_tax_bill"
    # The one that was a genuine CATALOG GAP rather than a synonym: the catalog carried
    # `installment_loan_statement` and `student_loan_statement` and nothing for the commonest
    # consumer debt of all, so this one was added as a real document type.
    assert canonical_need_type("credit_card_statement") == "credit_card_statement"


def test_every_liability_need_the_coverage_pass_knows_can_be_satisfied() -> None:
    """`needs_coverage._LIABILITY_DOC_NEEDS` names the need types whose precondition it can check.
    Two of its keys were types no document could satisfy, which is how they were found — a coverage
    predicate is worth nothing on a row a processor cannot clear even after acting on it."""
    from app.services.needs_coverage import _LIABILITY_DOC_NEEDS
    from app.services.needs_engine import canonical_need_type

    unsatisfiable = sorted(t for t in _LIABILITY_DOC_NEEDS if canonical_need_type(t) is None)
    assert not unsatisfiable, f"the coverage pass flags needs nothing can clear: {unsatisfiable}"


# --------------------------------------------------------------------------- #
# bug-009 REVIEW — an invented name whose catalog target has an interchangeable twin
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("head", "members"),
    [
        ("investment_statement", ("investment_account", "brokerage_statement")),
        ("retirement_statement", ("retirement_account", "ira_401k")),
    ],
)
def test_an_invented_name_with_twin_targets_accepts_either(
    head: str, members: tuple[str, ...]
) -> None:
    """Aliasing to ONE of two interchangeable catalog types clears the need only by luck.

    The classifier's own indicators describe the same paper — `investment_account` says "a BROKERAGE
    or investment account statement" and `brokerage_statement` says "a securities BROKERAGE
    statement"; `ira_401k` states outright that it "overlaps the generic retirement_account". So an
    alias to one twin leaves the need open whenever the classifier picked the other, silently, in
    the direction where a processor chases a document already in the file.

    `_NEED_ALTERNATIVES` is the mechanism for "a need any one of several documents satisfies", and
    it is what these want. Asserted as membership rather than as an alias target, so reverting to
    the alias fails here.
    """
    from app.services.needs_engine import _NEED_ALTERNATIVES

    assert head in _NEED_ALTERNATIVES, f"{head} should be an alternatives head, not an alias"
    for member in members:
        assert member in _NEED_ALTERNATIVES[head], f"{member} cannot satisfy {head}"
        assert member in CATALOG, f"{member} is not a document the classifier can produce"


def test_a_pension_statement_does_not_satisfy_a_retirement_account_need() -> None:
    """The boundary of the widening above.

    `pension_statement` is INCOME_EMPLOYMENT — an income stream, not an account balance. It shares
    the word "retirement" and answers a different ask, so letting it clear a retirement-ACCOUNT need
    would be a false green rather than a tolerance."""
    from app.services.needs_engine import _NEED_ALTERNATIVES

    assert "pension_statement" not in _NEED_ALTERNATIVES["retirement_statement"]


def test_the_invented_names_still_canonicalise_and_are_offered() -> None:
    """Being an alternatives head must not take them out of either path the fix depends on:
    `canonical_need_type` has to accept them (or a proposal is stored raw and unclearable), and
    `satisfiable_need_types` has to still offer them to the model."""
    from app.services.needs_engine import canonical_need_type, satisfiable_need_types

    for head in ("investment_statement", "retirement_statement"):
        assert canonical_need_type(head) == head
        assert head in satisfiable_need_types()
