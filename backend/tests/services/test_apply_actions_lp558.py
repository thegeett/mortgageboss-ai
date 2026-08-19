"""LP-558 — Apply writes the finding into the LOAN, and can be taken back exactly.

The agreed definition: Apply is the only action that changes the loan's structured data rather than
the finding's state. The target follows the nature of the finding — a debt goes to liabilities, a
value goes to the property — and the calculators recompute from whichever moved.

Three properties are tested here because each one, if wrong, is silent:

1. an apply that changed NOTHING must not close the finding;
2. an ambiguous target must decline rather than edit the wrong row;
3. every apply must be exactly reversible from `applied_record`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.finding import Finding, FindingCategory, FindingResolutionStatus, FindingStatus
from app.models.property import Property
from app.models.stated_financials import StatedLiability
from app.services.finding_resolution import CannotApplyError, apply_finding, undo_finding
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file(db: AsyncSession):
    """A minimal file plus an actor. The apply path records WHO applied, and that FK is enforced —
    a fabricated user id fails at the database, not in the code under test."""
    from app.models import User, UserRole
    from app.services.loan_files import create_loan_file

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"p-{uuid4().hex[:8]}@example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return loan_file, user.id


async def _finding(db: AsyncSession, loan_file, apply_spec: dict) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="DT-6",
        message="the application understates this payment",
        subject_key="lia1",
        load_bearing_tags=[],
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        confidence=1.0,
        details={"apply": apply_spec},
    )
    db.add(finding)
    await db.flush()
    return finding


# --------------------------------------------------------------------------------------------- #
# 1. AN APPLY THAT CHANGED NOTHING MUST NOT CLOSE THE FINDING
# --------------------------------------------------------------------------------------------- #
async def test_an_unknown_action_refuses_instead_of_marking_the_finding_resolved(
    db_session: AsyncSession,
) -> None:
    """THE DEFECT THIS TICKET FOUND. An unrecognised action returned `applied: False` and the
    finding was marked APPLIED anyway — a processor saw "resolved" over a loan file nothing had been
    written to, and a DTI they were trusting that had not moved. One typo in a spec was enough."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(
        db_session, loan_file, {"action": "corect_income"}
    )  # pragma: allowlist secret

    with pytest.raises(CannotApplyError):
        await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert finding.resolution_status is FindingResolutionStatus.OPEN


async def test_a_missing_target_refuses(db_session: AsyncSession) -> None:
    """The liability named is not on this file — decline rather than write nothing and claim success."""
    loan_file, actor = await _loan_file(db_session)
    finding = await _finding(
        db_session,
        loan_file,
        {"action": "correct_liability_payment", "holder_name": "NOBODY", "monthly_payment": "10"},
    )

    with pytest.raises(CannotApplyError):
        await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)


async def test_an_ambiguous_target_refuses_rather_than_editing_the_wrong_debt(
    db_session: AsyncSession,
) -> None:
    """TWO DEBTS FROM ONE HOLDER IS REAL — a card and a HELOC with the same bank. The snapshot
    identifies a liability by holder name, so the two are indistinguishable here. Picking either would
    silently edit the wrong debt and move the DTI by the wrong amount."""
    loan_file, actor = await _loan_file(db_session)
    for _ in range(2):
        db_session.add(
            StatedLiability(
                loan_file_id=loan_file.id,
                liability_type="Revolving",
                holder_name="SAME BANK",
                monthly_payment=Decimal("100.00"),
            )
        )
    await db_session.flush()
    finding = await _finding(
        db_session,
        loan_file,
        {
            "action": "correct_liability_payment",
            "holder_name": "SAME BANK",
            "monthly_payment": "500",
        },
    )

    with pytest.raises(CannotApplyError):
        await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)


# --------------------------------------------------------------------------------------------- #
# 2. THE CHANGE LANDS, AND MOVES THE RATIO THE CONSERVATIVE WAY
# --------------------------------------------------------------------------------------------- #
async def test_correcting_a_liability_payment_raises_the_debt(db_session: AsyncSession) -> None:
    """DT-6's shape: the servicer bills more than the application states, so the DTI must go UP.
    Every apply moves a ratio the conservative way — one that could LOWER a DTI is a different risk
    class and must not share this path."""
    loan_file, actor = await _loan_file(db_session)
    liability = StatedLiability(
        loan_file_id=loan_file.id,
        liability_type="MortgageLoan",
        holder_name="UNITED WHSLE MORT",
        monthly_payment=Decimal("3186.00"),
    )
    db_session.add(liability)
    await db_session.flush()
    finding = await _finding(
        db_session,
        loan_file,
        {
            "action": "correct_liability_payment",
            "holder_name": "UNITED WHSLE MORT",
            "monthly_payment": "4148.28",
        },
    )

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert liability.monthly_payment == Decimal("4148.28")
    assert finding.applied_record["from"] == "3186.00"


async def test_correcting_the_purchase_price_needs_no_targeting(db_session: AsyncSession) -> None:
    """A loan file has ONE subject property, so unlike a liability there is nothing to disambiguate."""
    loan_file, actor = await _loan_file(db_session)
    prop = Property(loan_file_id=loan_file.id, purchase_price=Decimal("500000.00"))
    db_session.add(prop)
    await db_session.flush()
    finding = await _finding(
        db_session, loan_file, {"action": "correct_purchase_price", "value": "525000.00"}
    )

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert prop.purchase_price == Decimal("525000.00")


# --------------------------------------------------------------------------------------------- #
# 3. EXACTLY REVERSIBLE
# --------------------------------------------------------------------------------------------- #
async def test_undo_restores_the_exact_prior_payment(db_session: AsyncSession) -> None:
    """Undo restores from `applied_record`, never an approximation. Without a reverser for a new
    action, Undo would flip the finding open and leave the loan permanently edited."""
    loan_file, actor = await _loan_file(db_session)
    liability = StatedLiability(
        loan_file_id=loan_file.id,
        liability_type="MortgageLoan",
        holder_name="UNITED WHSLE MORT",
        monthly_payment=Decimal("3186.00"),
    )
    db_session.add(liability)
    await db_session.flush()
    finding = await _finding(
        db_session,
        loan_file,
        {
            "action": "correct_liability_payment",
            "holder_name": "UNITED WHSLE MORT",
            "monthly_payment": "4148.28",
        },
    )
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert liability.monthly_payment == Decimal("3186.00")
    assert finding.resolution_status is FindingResolutionStatus.OPEN


# --------------------------------------------------------------------------------------------- #
# LP-560 — Ratify: the act ratification_pending promises and nothing could perform
# --------------------------------------------------------------------------------------------- #
async def _judgment_finding(db: AsyncSession, loan_file, *, pending: bool = True) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="DT-6",
        message="the application understates this payment",
        subject_key="lia1",
        load_bearing_tags=[],
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        confidence=1.0,
        details={"ratification_pending": pending},
    )
    db.add(finding)
    await db.flush()
    return finding


async def test_ratifying_records_who_agreed_without_touching_the_loan(
    db_session: AsyncSession,
) -> None:
    """The gap this closes. Nine findings on the real file say "a human must confirm" — the sentence
    that lets an uncalibrated judgment rule run at all — and the only way to clear one was OVERRIDE,
    which records a dismissal. Every agreement was being filed as a rejection.

    Ratify changes NO structured data. What changes is that the verdict carries a person's name."""
    from app.services.finding_resolution import ratify_finding

    loan_file, actor = await _loan_file(db_session)
    finding = await _judgment_finding(db_session, loan_file)

    await ratify_finding(db_session, finding=finding, actor_user_id=actor)

    assert finding.resolution_status is FindingResolutionStatus.RATIFIED
    assert finding.resolved_by_user_id == actor
    assert finding.applied_record is None  # nothing was written to the loan


async def test_a_deterministic_finding_cannot_be_ratified(db_session: AsyncSession) -> None:
    """Ratification means "I reviewed the AI's judgment and agree". A deterministic verdict was never
    a judgment, so signing it would record a review that did not happen — an audit trail claiming more
    than it can support. Override is the right verb for disagreeing with one of those."""
    from app.services.finding_resolution import CannotRatifyError, ratify_finding

    loan_file, actor = await _loan_file(db_session)
    finding = await _judgment_finding(db_session, loan_file, pending=False)

    with pytest.raises(CannotRatifyError):
        await ratify_finding(db_session, finding=finding, actor_user_id=actor)

    assert finding.resolution_status is FindingResolutionStatus.OPEN


async def test_a_ratification_can_be_taken_back(db_session: AsyncSession) -> None:
    """A signature given in error has to be retractable. It made no data change, so Undo is the
    Override path — flip back to OPEN — and the finding returns to the queue."""
    from app.services.finding_resolution import ratify_finding

    loan_file, actor = await _loan_file(db_session)
    finding = await _judgment_finding(db_session, loan_file)
    await ratify_finding(db_session, finding=finding, actor_user_id=actor)

    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert finding.resolution_status is FindingResolutionStatus.OPEN


async def test_the_note_is_optional_where_an_override_reason_is_required(
    db_session: AsyncSession,
) -> None:
    """Overriding contradicts the system and must say why. Ratifying agrees with what the finding
    already states, and demanding a second explanation is friction on the path we want taken."""
    from app.services.finding_resolution import ratify_finding

    loan_file, actor = await _loan_file(db_session)
    finding = await _judgment_finding(db_session, loan_file)

    await ratify_finding(db_session, finding=finding, actor_user_id=actor, note=None)

    assert finding.resolution_status is FindingResolutionStatus.RATIFIED
    assert finding.resolution_note is None
