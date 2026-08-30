"""The pipeline's Attention derivation (LP-UI-013).

Two properties matter more than the strings. First, the DECISION LADDER: the
column shows the single most important thing wrong, so what outranks what is the
behaviour. Second, AGREEMENT: the counts here are the same counts the file screen
shows, because a dashboard that disagrees with the screen it links to is worse
than either being wrong alone — the processor cannot tell which to believe.
"""

from datetime import date

from app.models import (
    Company,
    Document,
    DocumentStatus,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    LoanFile,
    LoanFileStatus,
    NeedsItem,
    NeedsItemStatus,
    UploadSource,
    User,
    UserRole,
)
from app.models.finding import FindingResolutionStatus
from app.services.attention import AttentionTone, attention_for_files
from app.services.loan_files import create_loan_file
from app.verification.confidence import AggressionLevel
from sqlalchemy.ext.asyncio import AsyncSession


async def _company_and_user(db_session: AsyncSession) -> tuple[Company, User]:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email="u@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return company, user


async def _file(db_session: AsyncSession, company: Company, **kw) -> LoanFile:
    """Through the real factory — a hand-built LoanFile misses inbox_token and other defaults."""
    loan_file = await create_loan_file(db_session, company_id=company.id)
    for field, value in kw.items():
        setattr(loan_file, field, value)
    await db_session.flush()
    return loan_file


async def _finding(db_session: AsyncSession, loan_file: LoanFile, **kw) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.income_variance",
        origin=kw.pop("origin", FindingOrigin.AI_CROSS_SOURCE),
        confidence=kw.pop("confidence", 0.9),
        status=kw.pop("status", FindingStatus.RED),
        category=FindingCategory.INCOME,
        message="A discrepancy.",
        **kw,
    )
    db_session.add(finding)
    await db_session.flush()
    return finding


async def _need(
    db_session: AsyncSession, loan_file: LoanFile, status: NeedsItemStatus
) -> NeedsItem:
    item = NeedsItem(
        loan_file_id=loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        status=status,
    )
    db_session.add(item)
    await db_session.flush()
    return item


async def _document(db_session: AsyncSession, loan_file: LoanFile, **kw) -> Document:
    doc = Document(
        loan_file_id=loan_file.id,
        original_filename=kw.pop("original_filename", "stub.pdf"),
        mime_type="application/pdf",
        file_size_bytes=1024,
        upload_source=UploadSource.USER_UPLOAD,
        storage_path=kw.pop("storage_path", "s3://x/stub.pdf"),
        status=kw.pop("status", DocumentStatus.COMPLETED),
        is_current=True,
        **kw,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


async def _attention(db_session: AsyncSession, loan_file: LoanFile, user: User):
    result = await attention_for_files(db_session, [loan_file], user=user, today=date(2026, 6, 1))
    return result[loan_file.id]


class TestBlockingAgreesWithTheFileScreen:
    """`finding_blocking.py` owns what "blocks submission" means. So does this."""

    async def test_a_finding_below_the_cutoff_does_not_block(
        self, db_session: AsyncSession, monkeypatch
    ) -> None:
        # The dial exists so a low-confidence hunch does not block. Counting it
        # here would have the dashboard call a file blocked that its own
        # verification screen calls clear.
        company, user = await _company_and_user(db_session)
        user.default_aggression_level = AggressionLevel.CONSERVATIVE  # cutoff 0.8
        loan_file = await _file(db_session, company)
        await _finding(db_session, loan_file, confidence=0.6, status=FindingStatus.RED)
        await _document(db_session, loan_file)

        assert (await _attention(db_session, loan_file, user)).tone is not AttentionTone.BLOCKING

    async def test_the_same_finding_blocks_at_a_lower_cutoff(
        self, db_session: AsyncSession
    ) -> None:
        """Same row, different dial — the count follows the file's cutoff, not a constant."""
        company, user = await _company_and_user(db_session)
        user.default_aggression_level = AggressionLevel.THOROUGH  # cutoff 0.0
        loan_file = await _file(db_session, company)
        await _finding(db_session, loan_file, confidence=0.6)
        await _document(db_session, loan_file)

        result = await _attention(db_session, loan_file, user)
        assert result.tone is AttentionTone.BLOCKING
        assert result.label == "1 finding blocks submission"

    async def test_a_per_file_override_beats_the_user_default(
        self, db_session: AsyncSession
    ) -> None:
        company, user = await _company_and_user(db_session)
        user.default_aggression_level = AggressionLevel.CONSERVATIVE  # 0.8
        loan_file = await _file(db_session, company)
        loan_file.aggression_level_override = AggressionLevel.THOROUGH  # 0.0
        await _finding(db_session, loan_file, confidence=0.1)
        await _document(db_session, loan_file)

        assert (await _attention(db_session, loan_file, user)).tone is AttentionTone.BLOCKING

    async def test_an_ai_finding_with_no_rule_outcome_still_counts(
        self, db_session: AsyncSession
    ) -> None:
        # The first version filtered `evaluation_outcome == OPEN`, which AI
        # cross-source findings do not carry — so a blocking file read as clear.
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        finding = await _finding(db_session, loan_file, confidence=0.95)
        assert finding.evaluation_outcome is None
        await _document(db_session, loan_file)

        assert (await _attention(db_session, loan_file, user)).tone is AttentionTone.BLOCKING

    async def test_a_green_finding_never_blocks(self, db_session: AsyncSession) -> None:
        """Green is a passed check, not a problem."""
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _finding(db_session, loan_file, status=FindingStatus.GREEN, confidence=1.0)
        await _document(db_session, loan_file)

        assert (await _attention(db_session, loan_file, user)).tone is not AttentionTone.BLOCKING

    async def test_a_resolved_finding_never_blocks(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _finding(
            db_session, loan_file, confidence=1.0, resolution_status=FindingResolutionStatus.APPLIED
        )
        await _document(db_session, loan_file)

        assert (await _attention(db_session, loan_file, user)).tone is not AttentionTone.BLOCKING


class TestNeedsAgreeWithTheNeedsScreen:
    """`NEEDS_GROUP`'s `needs_action` bucket is what the file's needs list counts."""

    async def test_received_is_not_waiting_on_a_document(self, db_session: AsyncSession) -> None:
        # `received` means the document ARRIVED. Counting it as waiting had the
        # dashboard say "Waiting on 2" where the needs screen said 0.
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _document(db_session, loan_file)
        await _need(db_session, loan_file, NeedsItemStatus.RECEIVED)
        await _need(db_session, loan_file, NeedsItemStatus.RECEIVED)

        result = await _attention(db_session, loan_file, user)
        assert result.label == "2 documents to review"

    async def test_pending_requested_and_rejected_are_all_waiting(
        self, db_session: AsyncSession
    ) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _document(db_session, loan_file)
        for status in (
            NeedsItemStatus.PENDING,
            NeedsItemStatus.REQUESTED,
            NeedsItemStatus.REJECTED,
        ):
            await _need(db_session, loan_file, status)

        assert (await _attention(db_session, loan_file, user)).label == "Waiting on 3 documents"

    async def test_verified_and_waived_are_neither(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _document(db_session, loan_file)
        await _need(db_session, loan_file, NeedsItemStatus.VERIFIED)
        await _need(db_session, loan_file, NeedsItemStatus.WAIVED)

        result = await _attention(db_session, loan_file, user)
        assert result.label == "Nothing outstanding"
        assert (result.needs_total, result.needs_satisfied) == (2, 2)


class TestTheLadder:
    async def test_a_terminal_file_says_so_calmly(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company, status=LoanFileStatus.WITHDRAWN)
        await _finding(db_session, loan_file, confidence=1.0)

        result = await _attention(db_session, loan_file, user)
        assert (result.tone, result.label) == (AttentionTone.NEUTRAL, "Withdrawn")

    async def test_blocking_outranks_a_failed_extraction(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _finding(db_session, loan_file, confidence=1.0)
        await _document(db_session, loan_file, status=DocumentStatus.FAILED)

        assert (await _attention(db_session, loan_file, user)).tone is AttentionTone.BLOCKING

    async def test_a_failed_extraction_outranks_waiting(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _document(
            db_session, loan_file, status=DocumentStatus.FAILED, document_type="pay_stub"
        )
        await _need(db_session, loan_file, NeedsItemStatus.PENDING)

        result = await _attention(db_session, loan_file, user)
        assert result.tone is AttentionTone.ATTENTION
        assert result.label == "Pay stub failed extraction"

    async def test_a_new_file_with_needs_is_not_calm(self, db_session: AsyncSession) -> None:
        # No documents AND eight needs. "No documents yet" is neutral, and this
        # is the most actionable row on the page — the ordering used to put the
        # empty-documents line first and paint it grey.
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        for _ in range(8):
            await _need(db_session, loan_file, NeedsItemStatus.PENDING)

        result = await _attention(db_session, loan_file, user)
        assert result.tone is AttentionTone.ATTENTION
        assert result.label == "Waiting on 8 documents"

    async def test_an_empty_file_with_nothing_pending_says_no_documents(
        self, db_session: AsyncSession
    ) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)

        result = await _attention(db_session, loan_file, user)
        assert (result.tone, result.label) == (AttentionTone.NEUTRAL, "No documents yet")

    async def test_a_clean_file_reads_clean(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _document(db_session, loan_file)

        result = await _attention(db_session, loan_file, user)
        assert (result.tone, result.label) == (AttentionTone.VERIFIED, "Nothing outstanding")

    async def test_the_singular_reads_as_english(self, db_session: AsyncSession) -> None:
        company, user = await _company_and_user(db_session)
        loan_file = await _file(db_session, company)
        await _document(db_session, loan_file)
        await _need(db_session, loan_file, NeedsItemStatus.PENDING)

        assert (await _attention(db_session, loan_file, user)).label == "Waiting on 1 document"


async def test_no_files_makes_no_queries(db_session: AsyncSession) -> None:
    _company, user = await _company_and_user(db_session)
    assert await attention_for_files(db_session, [], user=user) == {}
