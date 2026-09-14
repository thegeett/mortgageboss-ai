"""LP-1000 — the same bytes are not two documents.

Nothing in this system could express "is this the same document?". There was no hash, checksum or
digest on `documents`, and `create_document` did no duplicate check, so the only way to ask was to
compare `file_size_bytes` and hope. Staging held 22 groups of duplicate uploads across eight
document types when this was written, including one credit report present twice whose 24 tradelines
were therefore gathered as 48.

The check lives in `create_document` because all four intake routes pass through it — bulk upload,
replace, email-triage accept, borrower upload link — so one check covers four paths and whatever
route is added next.

WHAT THESE TESTS PIN, in order of how much they would hurt to get wrong:
  * the loan-file scope (a wider check would reject legitimate uploads and leak across companies);
  * the soft-delete exemption (without it, deleting a bad upload makes re-uploading it impossible);
  * the NULL fail-open (an unhashed pre-LP-1000 row must not refuse today's upload).
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.loan_file import LoanFile
from app.services import documents as documents_service
from app.services.documents import (
    DuplicateDocumentError,
    content_digest,
    create_document,
    find_duplicate,
    soft_delete_document,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

PDF_BYTES = b"%PDF-1.7\n%the same bytes twice\n"
OTHER_BYTES = b"%PDF-1.7\n%different bytes\n"


async def _company(db: AsyncSession, *, slug: str) -> tuple[Company, User]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, user


async def _add(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    filename: str,
    content: bytes = PDF_BYTES,
    user: User | None = None,
) -> Document:
    """Create one document the way every real route does."""
    document_id = uuid4()
    return await create_document(
        db,
        loan_file=loan_file,
        document_id=document_id,
        filename=filename,
        content=content,
        mime_type="application/pdf",
        size=len(content),
        storage_path=f"{loan_file.company_id}/{loan_file.id}/{document_id}.pdf",
        uploaded_by_user_id=user.id if user else None,
    )


# --------------------------------------------------------------------------- #
# The digest itself
# --------------------------------------------------------------------------- #
def test_the_digest_is_the_sha256_of_the_bytes() -> None:
    """Not a private scheme — the same hex sha256 anyone else would compute over the same file,
    which is what makes it comparable outside this codebase."""
    assert content_digest(PDF_BYTES) == hashlib.sha256(PDF_BYTES).hexdigest()
    assert content_digest(b"") == hashlib.sha256(b"").hexdigest()


async def test_the_digest_is_stored_on_the_document(db_session: AsyncSession) -> None:
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    document = await _add(db_session, loan_file, filename="paystub.pdf", user=user)

    assert document.content_sha256 == hashlib.sha256(PDF_BYTES).hexdigest()


# --------------------------------------------------------------------------- #
# The refusal
# --------------------------------------------------------------------------- #
async def test_the_same_bytes_on_one_loan_file_are_refused(db_session: AsyncSession) -> None:
    """THE SHAPE THIS TICKET EXISTS FOR: the same file uploaded twice. On staging that was three
    purchase-agreement pairs at 3,037,074 bytes each, one of each pair named "… (1).pdf"."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    first = await _add(db_session, loan_file, filename="Purchase Agreement.pdf", user=user)

    with pytest.raises(DuplicateDocumentError) as caught:
        await _add(db_session, loan_file, filename="Purchase Agreement (1).pdf", user=user)

    assert caught.value.http_status == 409
    assert caught.value.existing.id == first.id, "the caller needs the row it collided with"


async def test_the_refusal_names_the_document_it_collided_with(db_session: AsyncSession) -> None:
    """⚠️ "Duplicate rejected" with no referent is worse than accepting the duplicate: the
    processor can neither tell which of their files was refused nor find the one already there."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _add(db_session, loan_file, filename="Credit_Report_Naveen.pdf", user=user)

    with pytest.raises(DuplicateDocumentError) as caught:
        await _add(db_session, loan_file, filename="credit report copy.pdf", user=user)

    assert "Credit_Report_Naveen.pdf" in str(caught.value)


# --------------------------------------------------------------------------- #
# What must STILL be accepted — each one a way this could have been too strict
# --------------------------------------------------------------------------- #
async def test_the_same_bytes_on_a_DIFFERENT_loan_file_are_accepted(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE SCOPE, and the reason it is the loan file and not the company or the world. The same
    document legitimately appears on two loans (a blank lender form, a borrower with two
    applications). `Document` has no `company_id` of its own — it is company-scoped transitively
    through its loan file (ADR-052) — so scoping the check to the loan file is also what makes it
    tenant-safe by construction rather than by a filter somebody must remember."""
    company, user = await _company(db_session, slug="acme")
    one = await create_loan_file(db_session, company_id=company.id)
    two = await create_loan_file(db_session, company_id=company.id)

    await _add(db_session, one, filename="form.pdf", user=user)
    second = await _add(db_session, two, filename="form.pdf", user=user)

    assert second.loan_file_id == two.id


async def test_another_companys_identical_document_does_not_block(
    db_session: AsyncSession,
) -> None:
    """The cross-tenant case stated separately from the cross-file one, because it is the one that
    would be a security bug rather than an annoyance: company B must never learn that company A
    holds a file, and must never be refused because of it."""
    company_a, user_a = await _company(db_session, slug="acme")
    company_b, user_b = await _company(db_session, slug="globex")
    file_a = await create_loan_file(db_session, company_id=company_a.id)
    file_b = await create_loan_file(db_session, company_id=company_b.id)

    await _add(db_session, file_a, filename="w2.pdf", user=user_a)
    theirs = await _add(db_session, file_b, filename="w2.pdf", user=user_b)

    assert theirs.loan_file_id == file_b.id


async def test_a_soft_deleted_twin_does_not_block_re_uploading_it(
    db_session: AsyncSession,
) -> None:
    """⚠️ WITHOUT THIS THERE IS NO WAY OUT. A processor who uploads the wrong file and deletes it
    must be able to upload it again; matching against deleted rows would refuse them forever with a
    message pointing at a document they can no longer see."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    mistake = await _add(db_session, loan_file, filename="wrong.pdf", user=user)
    await soft_delete_document(db_session, document=mistake)

    again = await _add(db_session, loan_file, filename="wrong.pdf", user=user)

    assert again.id != mistake.id


async def test_different_bytes_with_the_same_name_are_accepted(db_session: AsyncSession) -> None:
    """The check is on CONTENT, never on the filename. Two statements both saved as "statement.pdf"
    are two documents; refusing on the name would reject the ordinary case."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    await _add(db_session, loan_file, filename="statement.pdf", user=user)
    other = await _add(
        db_session, loan_file, filename="statement.pdf", content=OTHER_BYTES, user=user
    )

    assert other.content_sha256 == hashlib.sha256(OTHER_BYTES).hexdigest()


async def test_a_row_with_no_digest_does_not_refuse_todays_upload(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE FAIL-OPEN DIRECTION, chosen deliberately. Every document uploaded before this column
    existed has `content_sha256 = NULL` and cannot be backfilled without re-reading every blob out
    of object storage. So NULL means "uploaded before LP-1000", never "this file has no content" —
    and refusing an upload because an old row happens to be unhashed would be a worse error than
    accepting a duplicate."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    legacy = await _add(db_session, loan_file, filename="legacy.pdf", user=user)
    legacy.content_sha256 = None  # a pre-LP-1000 row
    await db_session.flush()

    accepted = await _add(db_session, loan_file, filename="legacy again.pdf", user=user)

    assert accepted.id != legacy.id


# --------------------------------------------------------------------------- #
# Replace — the one route whose collision is with ITSELF (LP-1000 review)
# --------------------------------------------------------------------------- #
async def test_find_duplicate_excluding_the_target_is_how_replace_must_ask(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE DEFECT THIS FILE DID NOT COVER, and the reason it went unnoticed: nothing here
    exercised the replace route at all.

    `replace` calls `create_document` BEFORE `supersede_document`, so when the check fires the
    document being replaced is still `is_current` and not deleted — which is to say ACTIVE, exactly
    what `find_duplicate` looks for. An identical replace therefore collided with its own target,
    and the backstop's message told the processor "this file is already on the loan as <the document
    you are replacing> … replace the existing document if this one supersedes it": advice to do the
    thing they had just done.

    The question the route has to ask is "is anything OTHER than the target the same?", which is
    what `exclude_id` exists for. Pinned at the seam rather than through the endpoint, because the
    endpoint needs an HTTP client and this is the predicate the fix turns on.
    """
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    target = await _add(db_session, loan_file, filename="Appraisal v1.pdf", user=user)
    digest = content_digest(PDF_BYTES)

    # Asked the way the backstop asks it, the target itself is the "duplicate" — the bug.
    assert await find_duplicate(db_session, loan_file_id=loan_file.id, digest=digest) is target
    # Asked the way replace must ask it, there is no collision: the only match IS the target.
    assert (
        await find_duplicate(
            db_session, loan_file_id=loan_file.id, digest=digest, exclude_id=target.id
        )
        is None
    )


async def test_a_third_document_still_collides_with_a_replace(db_session: AsyncSession) -> None:
    """Excluding the target must not excuse a real collision. Replacing document A with bytes that
    match document B is still refused — B is a different document on the same loan file, and the
    replacement would put the same bytes on the loan twice."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    target = await _add(
        db_session, loan_file, filename="Appraisal v1.pdf", content=OTHER_BYTES, user=user
    )
    third = await _add(db_session, loan_file, filename="Survey.pdf", user=user)

    found = await find_duplicate(
        db_session,
        loan_file_id=loan_file.id,
        digest=content_digest(PDF_BYTES),
        exclude_id=target.id,
    )

    assert found is not None and found.id == third.id


# --------------------------------------------------------------------------- #
# find_duplicate on its own — the seam the bulk upload's stage 1 uses
# --------------------------------------------------------------------------- #
async def test_find_duplicate_can_exclude_a_document(db_session: AsyncSession) -> None:
    """`exclude_id` is what lets a caller ask "is anything OTHER than this one the same?" — needed
    by any later reconciliation of the duplicates already in the database, which is the half
    LP-1000 does not fix."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    only = await _add(db_session, loan_file, filename="one.pdf", user=user)
    digest = content_digest(PDF_BYTES)

    assert await find_duplicate(db_session, loan_file_id=loan_file.id, digest=digest) is not None
    assert (
        await find_duplicate(
            db_session, loan_file_id=loan_file.id, digest=digest, exclude_id=only.id
        )
        is None
    )


# --------------------------------------------------------------------------- #
# The race — `uq_documents_loan_file_content_sha256` (b8e2f5a91c73)
#
# The pre-check above is a SELECT and the insert is an INSERT, separated by an object-storage write
# per file and the caller's commit. Two requests for one loan file can both read clean and both
# insert; a double-click does it. These pin the database refusing what the check cannot.
# --------------------------------------------------------------------------- #
async def test_the_database_refuses_a_second_active_row_with_the_same_digest(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE GUARANTEE ITSELF, tested by BYPASSING the service check entirely — which is what a
    racing request effectively does. If this test ever passes without raising, the constraint is
    missing from the schema and every other test in this section proves nothing."""
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _add(db_session, loan_file, filename="first.pdf", user=user)

    twin = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="racing-second.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(PDF_BYTES),
        content_sha256=content_digest(PDF_BYTES),
        storage_path=f"{loan_file.company_id}/{loan_file.id}/twin.pdf",
        status=DocumentStatus.PENDING,
        upload_source=UploadSource.USER_UPLOAD,
    )

    # In a SAVEPOINT so the violation does not poison this test's session — the same containment
    # `create_document` uses, for the same reason.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(twin)
            await db_session.flush()


async def test_a_lost_race_is_the_same_409_and_not_a_500(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The constraint's job is to refuse; translating its refusal is `create_document`'s.

    The pre-check is blinded ONCE — exactly what the loser of a race experiences: it looked, saw
    nothing, and by the time it inserted the winner had committed. The processor must still get the
    sentence naming the file they collided with, not a driver error.
    """
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    winner = await _add(db_session, loan_file, filename="winner.pdf", user=user)

    real_find_duplicate = documents_service.find_duplicate
    calls = {"n": 0}

    async def blind_on_the_first_look(*args: object, **kwargs: object) -> Document | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # the race: the twin is not visible yet
        return await real_find_duplicate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(documents_service, "find_duplicate", blind_on_the_first_look)

    with pytest.raises(DuplicateDocumentError) as caught:
        await _add(db_session, loan_file, filename="loser.pdf", user=user)

    assert caught.value.existing is not None
    assert caught.value.existing.id == winner.id
    assert "winner.pdf" in caught.value.message, "the refusal must name the file it collided with"


async def test_losing_the_race_does_not_poison_the_rest_of_the_batch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE REASON THE INSERT RUNS INSIDE `begin_nested()`, and the failure that would hurt most.

    A failed flush poisons the session: without the SAVEPOINT the caller's transaction is unusable
    after the violation and their commit raises PendingRollbackError — so one duplicate in a
    ten-file upload would take the whole request down, activity log included. Here the next document
    must still save.
    """
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _add(db_session, loan_file, filename="winner.pdf", user=user)

    real_find_duplicate = documents_service.find_duplicate
    calls = {"n": 0}

    async def blind_on_the_first_look(*args: object, **kwargs: object) -> Document | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_find_duplicate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(documents_service, "find_duplicate", blind_on_the_first_look)
    with pytest.raises(DuplicateDocumentError):
        await _add(db_session, loan_file, filename="loser.pdf", user=user)
    monkeypatch.setattr(documents_service, "find_duplicate", real_find_duplicate)

    survivor = await _add(
        db_session, loan_file, filename="next-in-the-batch.pdf", content=OTHER_BYTES, user=user
    )

    assert survivor.id is not None
    assert survivor.content_sha256 == content_digest(OTHER_BYTES)


async def test_a_deleted_twin_and_its_replacement_coexist_under_the_constraint(
    db_session: AsyncSession,
) -> None:
    """⚠️ WHAT A TOTAL UNIQUE INDEX WOULD HAVE BROKEN, which is why the index is PARTIAL.

    Deleting a bad upload and re-adding the same file leaves TWO rows with one digest on one loan
    file — one soft-deleted, one active. `deleted_at IS NULL` in the predicate is what permits that,
    and it is the same filter `find_duplicate` applies, so the index and the service agree.
    """
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    first = await _add(db_session, loan_file, filename="mistake.pdf", user=user)
    await soft_delete_document(db_session, document=first)

    again = await _add(db_session, loan_file, filename="mistake.pdf", user=user)

    rows = (
        await db_session.scalars(
            select(Document).where(
                Document.loan_file_id == loan_file.id,
                Document.content_sha256 == content_digest(PDF_BYTES),
            )
        )
    ).all()
    assert {row.id for row in rows} == {first.id, again.id}
    assert again.deleted_at is None
