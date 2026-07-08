"""Tests for borrower↔document matching (LP-118.8) — whose-document assignment.

Two layers: the PURE matcher (conservative name matching + the safety rule) and the DB service +
fact-namespace wiring (persisted links → borrowers[].documents[]). The heart is the SAFETY RULE: a
wrong assignment is worse than none — cross-assignment must never happen, and ambiguous/no-match
documents stay unassigned. **No test executes a verification rule.**
"""

from app.models.document_borrower_link import DocumentBorrowerLink
from app.services.document_borrower_matching import (
    BorrowerRef,
    DocumentNames,
    _extract_names,
    assign_documents_to_borrowers,
    match_documents,
)
from app.verification.fact_namespace import assemble_fact_namespace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import (
    make_borrower,
    make_company,
    make_document,
    make_extraction,
    make_loan_file,
)

_BANSARI = BorrowerRef("b-id", "Bansari", "Patel", "Bansari Patel")
_AKASH = BorrowerRef("a-id", "Akash", "Patel", "Akash Patel")


def _one(names: tuple[str, ...]):
    return match_documents([_BANSARI, _AKASH], [DocumentNames("d", names)])[0]


# --------------------------------------------------------------------------- #
# Pure matcher — the safety rule
# --------------------------------------------------------------------------- #


def test_confident_match_assigns_the_right_borrower() -> None:
    assert _one(("Bansari Patel",)).links[0].borrower_id == "b-id"
    assert _one(("Akash Patel",)).links[0].borrower_id == "a-id"


def test_no_cross_assignment_on_shared_surname() -> None:
    # The exact bug to prevent: Bansari's doc must NOT land on Akash (same last name).
    a = _one(("Bansari Patel",))
    assert a.status == "assigned"
    assert [link.borrower_id for link in a.links] == ["b-id"]  # only Bansari


def test_name_variations_match_via_fuzzy() -> None:
    assert _one(("Bansari K Patel",)).links[0].borrower_id == "b-id"  # middle name
    assert _one(("Bansari Patel Jr",)).links[0].borrower_id == "b-id"  # suffix
    assert _one(("B. Patel",)).links[0].borrower_id == "b-id"  # initial (unique here)


def test_no_name_document_is_unassigned() -> None:
    a = _one(())
    assert a.status == "unassigned" and a.note == "no_name" and a.links == ()


def test_no_match_document_is_unassigned() -> None:
    a = _one(("Chris Johnson",))
    assert a.status == "unassigned" and a.note == "no_match"


def test_ambiguous_match_is_left_unassigned_not_guessed() -> None:
    # Two same-initial Patels + "C. Patel" → cannot pick → UNASSIGNED (never a forced guess).
    chris = BorrowerRef("c1", "Chris", "Patel", "Chris Patel")
    christine = BorrowerRef("c2", "Christine", "Patel", "Christine Patel")
    a = match_documents([chris, christine], [DocumentNames("d", ("C. Patel",))])[0]
    assert a.status == "unassigned" and a.note == "ambiguous" and a.links == ()


def test_joint_document_links_both_borrowers() -> None:
    names = _extract_names({"account_holder_name": {"value": "Bansari Patel and Akash Patel"}})
    a = match_documents([_BANSARI, _AKASH], [DocumentNames("d", names)])[0]
    assert a.status == "joint"
    assert {link.borrower_id for link in a.links} == {"b-id", "a-id"}


def test_extract_names_uses_owner_keys_and_excludes_donor_buyer() -> None:
    # recipient_name (the borrower) counts; donor_name does NOT (ambiguous ownership).
    assert _extract_names(
        {"donor_name": {"value": "Rich Uncle"}, "recipient_name": {"value": "Bansari Patel"}}
    ) == ("Bansari Patel",)
    # A purchase contract's buyer/seller names are not owner keys → no candidate → unassigned.
    assert _extract_names({"buyer_name": {"value": "Bansari Patel"}}) == ()


# --------------------------------------------------------------------------- #
# DB service + fact-namespace wiring
# --------------------------------------------------------------------------- #


def _field(value: str) -> dict[str, object]:
    return {"value": value, "source": {"page": 1, "snippet": value}}


async def _multi_borrower_file(db: AsyncSession):
    """LF-6T3N-style: Bansari + Akash Patel, with each one's doc + a contract + a joint statement."""
    company = await make_company(db, slug="dbm")
    lf = await make_loan_file(db, company=company)
    b = await make_borrower(
        db, loan_file=lf, first_name="Bansari", last_name="Patel", ssn="111-11-1111"
    )
    a = await make_borrower(
        db, loan_file=lf, first_name="Akash", last_name="Patel", ssn="222-22-2222"
    )
    a.borrower_position = 2

    w2 = await make_document(db, loan_file=lf, company=company, document_type="w2")
    await make_extraction(db, document=w2, data={"employee_name": _field("Bansari Patel")})
    bank = await make_document(db, loan_file=lf, company=company, document_type="bank_statement")
    await make_extraction(db, document=bank, data={"account_holder_name": _field("Akash Patel")})
    contract = await make_document(
        db, loan_file=lf, company=company, document_type="purchase_agreement"
    )
    await make_extraction(
        db, document=contract, data={"buyer_name": _field("Bansari Patel")}
    )  # not an owner key
    joint = await make_document(db, loan_file=lf, company=company, document_type="bank_statement")
    await make_extraction(
        db, document=joint, data={"account_holder_name": _field("Bansari Patel and Akash Patel")}
    )
    await db.flush()
    return lf, {
        "bansari": b,
        "akash": a,
        "w2": w2,
        "bank": bank,
        "contract": contract,
        "joint": joint,
    }


async def test_assign_persists_links_and_notes(db_session: AsyncSession) -> None:
    lf, o = await _multi_borrower_file(db_session)
    assignments = await assign_documents_to_borrowers(db_session, lf)
    by_doc = {a.document_id: a for a in assignments}

    assert by_doc[str(o["w2"].id)].links[0].borrower_id == str(o["bansari"].id)
    assert by_doc[str(o["bank"].id)].links[0].borrower_id == str(o["akash"].id)
    assert by_doc[str(o["contract"].id)].status == "unassigned"
    assert by_doc[str(o["contract"].id)].note == "no_name"  # buyer_name is not an owner key
    assert by_doc[str(o["joint"].id)].status == "joint"

    # Persisted link rows + the unassigned note on the contract.
    links = (await db_session.execute(select(DocumentBorrowerLink))).scalars().all()
    assert len(links) == 4  # w2(1) + bank(1) + joint(2)
    await db_session.refresh(o["contract"])
    assert o["contract"].borrower_match_note == "no_name"
    assert all(link.confidence > 0 for link in links)  # provenance recorded


async def test_no_cross_assignment_in_namespace(db_session: AsyncSession) -> None:
    lf, o = await _multi_borrower_file(db_session)
    await assign_documents_to_borrowers(db_session, lf)
    ns = await assemble_fact_namespace(db_session, lf)

    by_name = {f"{bf.first_name}": bf for bf in ns.borrowers}
    bansari_docs = {d.document_id for d in by_name["Bansari"].documents}
    akash_docs = {d.document_id for d in by_name["Akash"].documents}

    # Each borrower has their own doc + the joint; NEITHER has the other's single-owner doc.
    assert str(o["w2"].id) in bansari_docs and str(o["w2"].id) not in akash_docs
    assert str(o["bank"].id) in akash_docs and str(o["bank"].id) not in bansari_docs
    assert str(o["joint"].id) in bansari_docs and str(o["joint"].id) in akash_docs
    # The contract (no owner name) is on nobody.
    assert str(o["contract"].id) not in bansari_docs | akash_docs

    # Each per-borrower ref carries THAT borrower's id.
    assert all(
        d.borrower_id == str(by_name["Bansari"].borrower_id) for d in by_name["Bansari"].documents
    )

    # File-level documents[]: single-owner has borrower_id set; joint + unassigned are None.
    file_docs = {d.document_id: d for d in ns.documents}
    assert file_docs[str(o["w2"].id)].borrower_id == str(o["bansari"].id)
    assert file_docs[str(o["joint"].id)].borrower_id is None  # joint → no single owner
    assert file_docs[str(o["contract"].id)].borrower_id is None


async def test_reassign_replaces_links(db_session: AsyncSession) -> None:
    lf, _ = await _multi_borrower_file(db_session)
    await assign_documents_to_borrowers(db_session, lf)
    first = (await db_session.execute(select(DocumentBorrowerLink))).scalars().all()
    await assign_documents_to_borrowers(db_session, lf)  # re-run
    second = (await db_session.execute(select(DocumentBorrowerLink))).scalars().all()
    assert len(first) == len(second) == 4  # replaced, not duplicated
