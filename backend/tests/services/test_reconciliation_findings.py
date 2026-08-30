"""A20 — where the engine has ruled, the ledger row defers to it.

The design amendment behind these tests: the ledger's verdict is not always the
engine's. LP-80 makes the income variance overlay-overrideable per lender, and
the read model does not resolve overlays — so under an overlay the two disagree
about the same two numbers. Rather than average them or pick one silently, a row
carries the finding and shows its own comparison as the evidence beneath.

Two of the filters matter as much as the join itself, and each has its own test:
an AI finding must never become a ledger row's verdict (LP-375's separation), and
a finding a processor has already resolved must not be presented again.
"""

from app.models import (
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    LoanFile,
    User,
    UserRole,
)
from app.models.finding import FindingResolutionStatus
from app.services.loan_files import create_loan_file
from app.services.reconciliation import _ROW_RULE, reconcile_loan_file
from sqlalchemy.ext.asyncio import AsyncSession

EMPLOYER_RULE = "xsrc.income.employer_name_consistency"


async def _company(db_session: AsyncSession) -> Company:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        User(
            company_id=company.id,
            email="u@acme.com",
            hashed_password="x",  # pragma: allowlist secret
            first_name="T",
            last_name="U",
            role=UserRole.PROCESSOR,
            is_active=True,
        )
    )
    await db_session.flush()
    return company


async def _file(db_session: AsyncSession, company: Company | None = None) -> LoanFile:
    company = company or await _company(db_session)
    return await create_loan_file(db_session, company_id=company.id)


async def _finding(db_session: AsyncSession, loan_file: LoanFile, **kw) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id=kw.pop("rule_id", EMPLOYER_RULE),
        origin=kw.pop("origin", FindingOrigin.DETERMINISTIC_RULE),
        resolution_status=kw.pop("resolution_status", FindingResolutionStatus.OPEN),
        confidence=kw.pop("confidence", 0.9),
        status=kw.pop("status", FindingStatus.YELLOW),
        category=FindingCategory.INCOME,
        message=kw.pop("message", "Documented employer not among the stated employers."),
        **kw,
    )
    db_session.add(finding)
    await db_session.flush()
    return finding


def _row(rows: list, field_key: str):
    return next(r for r in rows if r.field_key == field_key)


class TestTheEngineIsTheAuthority:
    async def test_an_open_deterministic_finding_reaches_its_row(
        self, db_session: AsyncSession
    ) -> None:
        loan_file = await _file(db_session)
        finding = await _finding(db_session, loan_file)
        rows = await reconcile_loan_file(db_session, loan_file)
        employer = _row(rows, "employer")
        assert employer.finding is not None
        assert employer.finding.finding_id == finding.id
        assert employer.finding.rule_id == EMPLOYER_RULE

    async def test_an_ai_finding_is_never_a_ledger_verdict(self, db_session: AsyncSession) -> None:
        # The same table holds the legacy AI cross-source sweep. Those two are
        # never merged or summed (LP-375), and a row deferring to an AI finding
        # would put that separation inside the redesign's centrepiece. Same rule
        # id, same file — only the origin differs.
        loan_file = await _file(db_session)
        await _finding(db_session, loan_file, origin=FindingOrigin.AI_CROSS_SOURCE)
        rows = await reconcile_loan_file(db_session, loan_file)
        assert _row(rows, "employer").finding is None

    async def test_a_resolved_finding_is_not_shown_again(self, db_session: AsyncSession) -> None:
        # OVERRIDDEN means a processor dismissed it with a recorded reason. The
        # row goes back to reporting its own comparison rather than re-asking a
        # question that has been answered.
        loan_file = await _file(db_session)
        await _finding(
            db_session,
            loan_file,
            resolution_status=FindingResolutionStatus.OVERRIDDEN,
            resolution_note="Legal name differs from the DBA; verified by VOE.",
        )
        rows = await reconcile_loan_file(db_session, loan_file)
        assert _row(rows, "employer").finding is None

    async def test_a_row_counts_every_open_finding_it_defers_to(
        self, db_session: AsyncSession
    ) -> None:
        # A row shows ONE verdict but must not imply it is the only one.
        loan_file = await _file(db_session)
        await _finding(db_session, loan_file)
        await _finding(db_session, loan_file, message="A second documented employer.")
        rows = await reconcile_loan_file(db_session, loan_file)
        employer = _row(rows, "employer")
        assert employer.finding is not None
        assert employer.finding.count == 2

    async def test_a_finding_does_not_leak_onto_other_rows(self, db_session: AsyncSession) -> None:
        loan_file = await _file(db_session)
        await _finding(db_session, loan_file)
        rows = await reconcile_loan_file(db_session, loan_file)
        others = [r for r in rows if r.field_key != "employer"]
        assert [r.field_key for r in others if r.finding is not None] == []

    async def test_an_unmapped_rule_never_becomes_a_verdict(self, db_session: AsyncSession) -> None:
        # `xsrc.asset.stated_missing_document` asks whether a stated asset has a
        # document at all — this ledger's `missing` case, not its comparison.
        # Deliberately absent from the map; this pins that it stays absent.
        loan_file = await _file(db_session)
        await _finding(db_session, loan_file, rule_id="xsrc.asset.stated_missing_document")
        rows = await reconcile_loan_file(db_session, loan_file)
        assert all(r.finding is None for r in rows)
        assert "xsrc.asset.stated_missing_document" not in _ROW_RULE.values()

    async def test_a_files_findings_do_not_reach_another_file(
        self, db_session: AsyncSession
    ) -> None:
        # Same company, two files: the scoping under test is per FILE, and two
        # companies would have passed even if the query ignored the file id.
        company = await _company(db_session)
        loan_file = await _file(db_session, company)
        other = await _file(db_session, company)
        await _finding(db_session, loan_file)
        rows = await reconcile_loan_file(db_session, other)
        assert _row(rows, "employer").finding is None
