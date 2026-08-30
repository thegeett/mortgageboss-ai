"""What a proposed overlay would change, before it is saved (LP-UI-027).

The estimate COMPUTES rather than reads. Reading stored findings would answer "no
files affected" for every proposal, because `services/verification_engine` — the
only caller of the overlay-aware `evaluate()` — has no production caller, so no
finding on any file comes from a rule an overlay can target. Measured: zero
findings exist for any `conv.*`, `fha.*` or sample rule id.

"No files affected" is the most dangerous answer a blast radius can give, because
it reads as reassurance. So the estimate resolves each file's rules, swaps in the
proposed thresholds, and evaluates the pure engine twice.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models import (
    Borrower,
    Company,
    Lender,
    LoanFile,
    LoanFileStatus,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    User,
    UserRole,
)
from app.schemas.overlay_admin import OverlayOverrideInput
from app.services.loan_files import create_loan_file
from app.services.overlay_blast_radius import estimate_blast_radius
from app.verification.registry import default_registry
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession) -> Company:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    db.add(
        User(
            company_id=company.id,
            email=f"u{uuid4().hex[:6]}@acme.com",
            hashed_password="x",  # pragma: allowlist secret
            first_name="T",
            last_name="U",
            role=UserRole.ADMIN,
            is_active=True,
        )
    )
    await db.flush()
    return company


async def _lender(db: AsyncSession, company: Company) -> Lender:
    lender = Lender(
        company_id=company.id,
        name="UWM",
        slug=f"uwm-{uuid4().hex[:6]}",
        supported_programs=["conventional"],
        lender_overlays={},
    )
    db.add(lender)
    await db.flush()
    return lender


async def _file(
    db: AsyncSession, company: Company, lender: Lender, status: LoanFileStatus
) -> LoanFile:
    loan_file = await create_loan_file(db, company_id=company.id)
    loan_file.lender_id = lender.id
    loan_file.status = status
    await db.flush()
    return loan_file


def _a_sample_rule_id() -> str:
    """A real rule id from the registry — never a literal, which could go stale."""
    return next(r.rule_id for r in default_registry().rules)


class TestTheEstimate:
    async def test_is_scoped_to_the_callers_company(self, db_session: AsyncSession) -> None:
        mine = await _company(db_session)
        theirs = await _company(db_session)
        lender = await _lender(db_session, theirs)
        result = await estimate_blast_radius(
            db_session, company_id=mine.id, lender_id=lender.id, overrides=[]
        )
        assert result is None

    async def test_counts_only_the_lenders_open_files(self, db_session: AsyncSession) -> None:
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        other = await _lender(db_session, company)
        await _file(db_session, company, lender, LoanFileStatus.IN_PROCESSING)
        await _file(db_session, company, lender, LoanFileStatus.CLOSED)  # history
        await _file(db_session, company, other, LoanFileStatus.IN_PROCESSING)  # another lender

        result = await estimate_blast_radius(
            db_session, company_id=company.id, lender_id=lender.id, overrides=[]
        )
        assert result is not None
        assert result.evaluated_files == 1

    async def test_an_empty_proposal_moves_nothing(self, db_session: AsyncSession) -> None:
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        await _file(db_session, company, lender, LoanFileStatus.IN_PROCESSING)
        result = await estimate_blast_radius(
            db_session, company_id=company.id, lender_id=lender.id, overrides=[]
        )
        assert result is not None
        assert result.newly_blocking == []
        assert result.newly_clearing == []
        assert result.changed_only == []

    async def test_an_unknown_rule_is_skipped_not_raised(self, db_session: AsyncSession) -> None:
        # The PUT rejects an unknown rule_id; this read-only estimate skips it, so
        # a half-typed proposal still answers for the rules it does name.
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        await _file(db_session, company, lender, LoanFileStatus.IN_PROCESSING)
        result = await estimate_blast_radius(
            db_session,
            company_id=company.id,
            lender_id=lender.id,
            overrides=[OverlayOverrideInput(rule_id="no.such.rule", value=Decimal("1"))],
        )
        assert result is not None
        assert result.evaluated_files == 1

    async def test_says_the_overlay_is_not_in_force_today(self, db_session: AsyncSession) -> None:
        # The column this editor writes is not read by the registry. A screen
        # showing this estimate must not imply the change takes effect on save.
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        result = await estimate_blast_radius(
            db_session, company_id=company.id, lender_id=lender.id, overrides=[]
        )
        assert result is not None
        assert result.applies_today is False

    async def test_writes_nothing(self, db_session: AsyncSession) -> None:
        # THE acceptance criterion: read-only, no writes, no runs enqueued.
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        loan_file = await _file(db_session, company, lender, LoanFileStatus.IN_PROCESSING)
        before = loan_file.updated_at
        stored = dict(lender.lender_overlays or {})

        await estimate_blast_radius(
            db_session,
            company_id=company.id,
            lender_id=lender.id,
            overrides=[OverlayOverrideInput(rule_id=_a_sample_rule_id(), value=Decimal("1"))],
        )
        assert lender.lender_overlays == stored
        assert loan_file.updated_at == before

    @pytest.mark.parametrize("status", [LoanFileStatus.CLOSED, LoanFileStatus.WITHDRAWN])
    async def test_a_settled_file_is_not_examined(
        self, db_session: AsyncSession, status: LoanFileStatus
    ) -> None:
        # A closed or withdrawn file is history; a threshold change cannot move it.
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        await _file(db_session, company, lender, status)
        result = await estimate_blast_radius(
            db_session, company_id=company.id, lender_id=lender.id, overrides=[]
        )
        assert result is not None
        assert result.evaluated_files == 0


class TestAFileThatActuallyMoves:
    """The load-bearing case. Every test above passes against an estimator that
    always returns empty lists — these are the ones that do not.

    `conv.dti.back_end_max` is `<= 50` and red. A file at 48% passes today;
    proposing 45 makes it fail, and the file newly blocks.
    """

    async def _conventional_file_at_48_percent(
        self, db: AsyncSession, company: Company, lender: Lender
    ) -> LoanFile:
        loan_file = await _file(db, company, lender, LoanFileStatus.IN_PROCESSING)
        loan_file.loan_program = LoanProgram.CONVENTIONAL
        borrower = Borrower(loan_file_id=loan_file.id, first_name="Dana", last_name="Sample")
        db.add(borrower)
        await db.flush()
        # 4,800 / 10,000 = 48.00%
        db.add(StatedIncomeItem(borrower_id=borrower.id, monthly_amount=Decimal("10000")))
        db.add(StatedLiability(loan_file_id=loan_file.id, monthly_payment=Decimal("4800")))
        await db.flush()
        return loan_file

    async def test_a_tightened_threshold_newly_blocks_a_file(
        self, db_session: AsyncSession
    ) -> None:
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        loan_file = await self._conventional_file_at_48_percent(db_session, company, lender)

        result = await estimate_blast_radius(
            db_session,
            company_id=company.id,
            lender_id=lender.id,
            overrides=[OverlayOverrideInput(rule_id="conv.dti.back_end_max", value=Decimal("45"))],
        )
        assert result is not None
        assert [f.display_id for f in result.newly_blocking] == [loan_file.display_id]
        assert result.newly_clearing == []
        assert "conv.dti.back_end_max" in result.newly_blocking[0].rules

    async def test_a_loosened_threshold_newly_clears_a_file(self, db_session: AsyncSession) -> None:
        # The same file against a threshold it already fails: 48% > 40, so it
        # blocks today; proposing 55 clears it.
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        loan_file = await self._conventional_file_at_48_percent(db_session, company, lender)
        lender.lender_overlays = {}
        # Tighten the BASE by hand is not possible (it is code), so this asserts
        # the reverse direction using a file that fails the shipped 50% rule.
        db_session.add(StatedLiability(loan_file_id=loan_file.id, monthly_payment=Decimal("500")))
        await db_session.flush()  # 5,300 / 10,000 = 53% → fails <= 50 today

        result = await estimate_blast_radius(
            db_session,
            company_id=company.id,
            lender_id=lender.id,
            overrides=[OverlayOverrideInput(rule_id="conv.dti.back_end_max", value=Decimal("55"))],
        )
        assert result is not None
        assert [f.display_id for f in result.newly_clearing] == [loan_file.display_id]
        assert result.newly_blocking == []

    async def test_a_threshold_that_does_not_cross_the_value_moves_nothing(
        self, db_session: AsyncSession
    ) -> None:
        # 48% against a proposal of 49 still passes. The estimate must report the
        # file only when the VERDICT changes, not whenever a number does.
        company = await _company(db_session)
        lender = await _lender(db_session, company)
        await self._conventional_file_at_48_percent(db_session, company, lender)

        result = await estimate_blast_radius(
            db_session,
            company_id=company.id,
            lender_id=lender.id,
            overrides=[OverlayOverrideInput(rule_id="conv.dti.back_end_max", value=Decimal("49"))],
        )
        assert result is not None
        assert result.newly_blocking == []
        assert result.newly_clearing == []
        assert result.changed_only == []
