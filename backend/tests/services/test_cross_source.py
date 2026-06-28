"""The AI cross-source layer (LP-78) — the general capability + the APPLY loop.

The AI is mocked (a deterministic stub reasoner — no real key): the tests cover
emitting structured findings into LP-75's model (origin=ai_cross_source, the
category derived from the canonical type, confidence, source-location), canonical
types plus the open "other" bucket preserving a novel discrepancy, AI fallibility
(findings land OPEN — not auto-applied), the APPLY→recompute loop closing
end-to-end (income variance → DTI higher; liability discrepancy → liabilities →
DTI HIGHER), re-run replacing prior open findings, the manual trigger + staleness,
tenant scoping, and that PII is never logged.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.ai.cross_source import CrossSourceRawFinding, CrossSourceResult
from app.models import (
    Borrower,
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    User,
    UserRole,
)
from app.models.verification import VerificationStatus, VerificationTrigger
from app.services.cross_source import assemble_cross_source_context, run_cross_source
from app.services.dti import build_dti_calculation
from app.services.finding_resolution import apply_finding, override_finding
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run, mark_verification_stale
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs


def _raw(**kw) -> CrossSourceRawFinding:
    base: dict = {
        "type": "income_variance",
        "description": "A discrepancy",
        "stated_value": None,
        "document_value": None,
        "source_document": None,
        "page": None,
        "snippet": None,
        "confidence": 0.8,
        "reasoning": "because",
    }
    base.update(kw)
    return CrossSourceRawFinding(**base)


def _stub(findings: Sequence[CrossSourceRawFinding]):
    captured: dict[str, str] = {}

    async def _fn(context_json: str) -> CrossSourceResult:
        captured["context"] = context_json
        return CrossSourceResult(
            findings=list(findings), input_tokens=120, output_tokens=60, model="claude-sonnet-4-5"
        )

    _fn.captured = captured  # type: ignore[attr-defined]
    return _fn


async def _company(db: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company) -> User:
    user = User(
        company_id=company.id,
        email=f"u@{company.slug}.test",
        hashed_password="h",  # pragma: allowlist secret
        first_name="Pro",
        last_name="Cessor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return user


async def _file(db: AsyncSession, company: Company, *, income=Decimal("16400")):
    """A Conventional file: one borrower with stated income + a $2k liability."""
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    loan_file.note_amount = Decimal("100000")
    loan_file.note_rate_percent = Decimal("0")
    loan_file.amortization_months = 360
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Dana", last_name="Sample", is_primary=True
    )
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=income,
            income_type="Base",
            employment_income=True,
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=Decimal("2000")
        )
    )
    await db.flush()
    return loan_file


async def _run(db, loan_file, findings, *, actor=None):
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    return await run_cross_source(
        db, loan_file=loan_file, run=run, actor_user_id=actor, reason_fn=_stub(findings)
    )


async def _findings(db, loan_file_id) -> list[Finding]:
    rows = (
        (await db.execute(select(Finding).where(Finding.loan_file_id == loan_file_id)))
        .scalars()
        .all()
    )
    return list(rows)


# --- The general capability → structured findings into LP-75's model ---------


async def test_emits_structured_findings_into_shared_model(db_session: AsyncSession) -> None:
    """A discrepancy → a Finding with origin=ai_cross_source, confidence, source-loc."""
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)

    run = await _run(
        db_session,
        loan_file,
        [
            _raw(
                type="income_variance",
                description="Stated income exceeds documents by 8%",
                stated_value="16400",
                document_value="15100",
                source_document="pay_stub",
                page=1,
                snippet="Gross pay 3,775.00 biweekly",
                confidence=0.82,
            )
        ],
    )

    assert run.status is VerificationStatus.COMPLETED
    findings = await _findings(db_session, loan_file.id)
    assert len(findings) == 1
    f = findings[0]
    assert f.origin is FindingOrigin.AI_CROSS_SOURCE
    assert f.rule_id == "cross_source.income_variance"
    assert f.category is FindingCategory.INCOME  # derived from the type
    assert f.confidence == 0.82
    assert f.source_page == 1
    assert f.source_snippet == "Gross pay 3,775.00 biweekly"
    assert f.resolution_status is FindingResolutionStatus.OPEN  # for human review
    assert f.details["document_value"] == "15100"
    assert f.details["source_document"] == "pay_stub"


async def test_starter_comparisons_and_an_unanticipated_discrepancy(
    db_session: AsyncSession,
) -> None:
    """The starter set surfaces, AND a novel discrepancy surfaces (general capability)."""
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)

    await _run(
        db_session,
        loan_file,
        [
            _raw(type="income_variance", description="income off"),
            _raw(type="employer_mismatch", description="employer differs"),
            _raw(type="gift_discrepancy", description="gift differs"),
            # A novel discrepancy with no canonical type → the "other" bucket survives:
            _raw(
                type="other",
                description="Driver's license lists the subject property as the address",
            ),
        ],
    )

    rule_ids = {f.rule_id for f in await _findings(db_session, loan_file.id)}
    assert rule_ids == {
        "cross_source.income_variance",
        "cross_source.employer_mismatch",
        "cross_source.gift_discrepancy",
        "cross_source.other",  # the novel one — preserved, not suppressed
    }


async def test_findings_are_for_review_not_auto_applied(db_session: AsyncSession) -> None:
    """AI fallibility acceptable: findings land OPEN, never authoritative/auto-applied."""
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)
    await _run(db_session, loan_file, [_raw(type="liability_discrepancy", document_value="800")])

    findings = await _findings(db_session, loan_file.id)
    assert all(f.resolution_status is FindingResolutionStatus.OPEN for f in findings)
    # Nothing was incorporated into the structured data yet (no liability added).
    liabilities = (
        (
            await db_session.execute(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(liabilities) == 1  # only the seeded one — the finding was NOT auto-applied


# --- The APPLY → recompute loop closes end-to-end ----------------------------


async def test_apply_liability_discrepancy_raises_dti(db_session: AsyncSession) -> None:
    """The classic case: AI finds a documented obligation → apply → liabilities → DTI HIGHER."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)
    before = (await build_dti_calculation(db_session, loan_file=loan_file)).back_end_dti

    await _run(
        db_session,
        loan_file,
        [
            _raw(
                type="liability_discrepancy",
                description="$800/mo support obligation in the decree, not in stated debts",
                document_value="$800/month",  # the amount is parsed out of the free text
                source_document="divorce_decree",
                confidence=0.7,
            )
        ],
    )
    finding = (await _findings(db_session, loan_file.id))[0]
    assert finding.details["apply"]["action"] == "add_liability"
    assert finding.details["apply"]["monthly_payment"] == "800"  # parsed from "$800/month"

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    after = (await build_dti_calculation(db_session, loan_file=loan_file)).back_end_dti
    assert after is not None and before is not None
    assert after > before  # the obligation was added → the DTI recomputed higher


async def test_apply_income_variance_corrects_income_and_raises_dti(
    db_session: AsyncSession,
) -> None:
    """Apply an income-variance finding → income corrected (lower) → DTI HIGHER."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company, income=Decimal("16400"))
    before = (await build_dti_calculation(db_session, loan_file=loan_file)).back_end_dti

    await _run(
        db_session,
        loan_file,
        [
            _raw(
                type="income_variance",
                description="Documents support 15,100/mo, not the stated 16,400",
                stated_value="16400",
                document_value="15100",
                confidence=0.8,
            )
        ],
    )
    finding = (await _findings(db_session, loan_file.id))[0]
    assert finding.details["apply"]["action"] == "correct_income"

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    # The stated income item was corrected to the verified figure.
    item = (await db_session.execute(select(StatedIncomeItem))).scalars().one()
    assert item.monthly_amount == Decimal("15100")
    after = (await build_dti_calculation(db_session, loan_file=loan_file)).back_end_dti
    assert after is not None and before is not None
    assert after > before  # lower income → higher DTI


# --- Manual trigger + staleness ----------------------------------------------


async def test_running_the_pass_clears_staleness(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)
    await mark_verification_stale(db_session, loan_file_id=loan_file.id)
    await db_session.refresh(loan_file)
    assert loan_file.verification_stale is True

    await _run(db_session, loan_file, [_raw(type="income_variance")])
    await db_session.refresh(loan_file)
    assert loan_file.verification_stale is False  # the pass ran → current


async def test_applying_a_finding_marks_verification_stale(db_session: AsyncSession) -> None:
    """The loop's other half: applying changes data → verification goes stale."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)
    await _run(db_session, loan_file, [_raw(type="liability_discrepancy", document_value="800")])
    await db_session.refresh(loan_file)
    assert loan_file.verification_stale is False  # the pass cleared it

    finding = (await _findings(db_session, loan_file.id))[0]
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    await db_session.refresh(loan_file)
    assert loan_file.verification_stale is True  # applying changed data → stale


# --- Tenant scoping + PII discipline -----------------------------------------


async def test_context_carries_pii_for_the_call(db_session: AsyncSession) -> None:
    """The two sides are assembled (with PII) for the AI call (the perception input)."""
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)
    context = await assemble_cross_source_context(db_session, loan_file)
    assert context["stated"]["borrowers"][0]["name"] == "Dana Sample"
    assert context["stated"]["liabilities"][0]["monthly_payment"] == "2000.00"


async def test_pii_is_never_logged(db_session: AsyncSession) -> None:
    """The assembled PII (the borrower name) appears in NO log event (counts only)."""
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)

    with capture_logs() as logs:
        await _run(
            db_session,
            loan_file,
            [_raw(type="income_variance", description="off", snippet="Dana Sample paystub")],
        )

    serialized = repr(logs)
    assert "Dana" not in serialized  # no borrower name in any log event
    assert "paystub" not in serialized  # no snippet content either


async def test_document_change_marks_verification_stale(db_session: AsyncSession) -> None:
    """Uploading a document marks the cross-source verification stale (re-run)."""
    from uuid import uuid4

    from app.services.documents import create_document

    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)
    await db_session.refresh(loan_file)
    assert loan_file.verification_stale is False

    await create_document(
        db_session,
        loan_file=loan_file,
        document_id=uuid4(),
        filename="paystub.pdf",
        mime_type="application/pdf",
        size=1000,
        storage_path="some/path.pdf",
        uploaded_by_user_id=None,
    )
    await db_session.refresh(loan_file)
    assert loan_file.verification_stale is True  # a document changed → stale


async def test_pass_is_per_file(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    a = await _file(db_session, company)
    b = await _file(db_session, company)
    await _run(db_session, a, [_raw(type="income_variance")])

    assert len(await _findings(db_session, a.id)) == 1
    assert len(await _findings(db_session, b.id)) == 0  # only file A got findings


# --- Re-run replaces the prior open findings (no duplication) -----------------


async def _active_findings(db: AsyncSession, loan_file_id) -> list[Finding]:
    return [f for f in await _findings(db, loan_file_id) if f.deleted_at is None]


async def test_rerun_replaces_open_findings(db_session: AsyncSession) -> None:
    """Re-running supersedes the prior pass's open findings — no accumulation."""
    company = await _company(db_session, "acme")
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, [_raw(type="income_variance"), _raw(type="gift_discrepancy")])
    assert len(await _active_findings(db_session, loan_file.id)) == 2

    # A second pass returns a different set — the first run's open findings are gone.
    await _run(
        db_session, loan_file, [_raw(type="income_variance"), _raw(type="employer_mismatch")]
    )
    active = await _active_findings(db_session, loan_file.id)
    assert len(active) == 2  # not 4 — the prior open findings were superseded
    assert {f.rule_id for f in active} == {
        "cross_source.income_variance",
        "cross_source.employer_mismatch",
    }


async def test_rerun_preserves_resolved_findings(db_session: AsyncSession) -> None:
    """A resolved (overridden) finding survives a re-run; open ones are replaced."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)

    await _run(
        db_session,
        loan_file,
        [_raw(type="liability_discrepancy", document_value="800"), _raw(type="gift_discrepancy")],
    )
    obligation = next(
        f
        for f in await _active_findings(db_session, loan_file.id)
        if f.rule_id == "cross_source.liability_discrepancy"
    )
    await override_finding(
        db_session, finding=obligation, actor_user_id=user.id, reason="Already disclosed elsewhere."
    )

    # Re-run: the resolved obligation is preserved; the open gift_discrepancy is gone.
    await _run(db_session, loan_file, [_raw(type="income_variance")])
    rule_ids = {f.rule_id for f in await _active_findings(db_session, loan_file.id)}
    assert "cross_source.liability_discrepancy" in rule_ids  # resolved → preserved
    assert "cross_source.income_variance" in rule_ids  # the fresh pass
    assert "cross_source.gift_discrepancy" not in rule_ids  # open → superseded
