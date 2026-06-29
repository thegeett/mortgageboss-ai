"""Deterministic cross-source service (LP-86) — DB-backed evaluation + the de-dup.

Covers: building the cross-source facts from the assembled context + the subject property;
the GRADUATION end-to-end (the driver's-license-equals-subject finding fires as a
DETERMINISTIC_RULE finding on a real file, stably across re-runs); the DE-DUPLICATION (the
AI cross-source layer DEFERS on a canonical type a deterministic rule fired this run — no
double-reporting — while it keeps the novel "other" bucket); and the undisclosed-debt
APPLY→recompute cross-link (the deterministic finding carries an add_liability apply spec).
"""

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.ai.cross_source import CrossSourceRawFinding, CrossSourceResult
from app.models import (
    Borrower,
    Company,
    Finding,
    FindingOrigin,
    LoanFile,
    LoanProgram,
    StatedLiability,
    User,
    UserRole,
)
from app.models.verification import VerificationTrigger
from app.services.cross_source import assemble_cross_source_context, run_cross_source
from app.services.cross_source_deterministic import (
    build_cross_source_facts,
    run_cross_source_deterministic,
)
from app.services.finding_resolution import apply_finding
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from app.verification.confidence import DETERMINISTIC_CONFIDENCE
from app.verification.cross_source import CrossSourceFacts, ObligationRef
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import make_document, make_extraction, make_property

_SUBJECT = "123 Main St, Springfield, IL, 62704"


def _raw(**kw: Any) -> CrossSourceRawFinding:
    base: dict[str, Any] = {
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


def _stub(
    findings: Sequence[CrossSourceRawFinding],
) -> Callable[[str], Awaitable[CrossSourceResult]]:
    async def _fn(_context_json: str) -> CrossSourceResult:
        return CrossSourceResult(
            findings=list(findings), input_tokens=10, output_tokens=5, model="claude-sonnet-4-5"
        )

    return _fn


async def _company(db: AsyncSession) -> Company:
    company = Company(name="Acme", slug="acme")
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company) -> User:
    user = User(
        company_id=company.id,
        email="u@acme.test",
        hashed_password="h",  # pragma: allowlist secret
        first_name="Pro",
        last_name="Cessor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return user


async def _file_with_dl_at_subject(
    db: AsyncSession, company: Company, *, program: LoanProgram = LoanProgram.CONVENTIONAL
) -> LoanFile:
    """A file whose driver's-license address equals the subject property (the red flag)."""
    loan_file = await create_loan_file(db, company_id=company.id, loan_program=program)
    db.add(
        Borrower(loan_file_id=loan_file.id, first_name="Dana", last_name="Sample", is_primary=True)
    )
    await make_property(db, loan_file=loan_file)  # 123 Main St, Springfield, IL 62704
    doc = await make_document(
        db, loan_file=loan_file, company=company, document_type="drivers_license"
    )
    await make_extraction(
        db,
        document=doc,
        data={"address": {"value": _SUBJECT, "source": {"page": 1, "snippet": "123 Main St"}}},
    )
    return loan_file


async def _findings(db: AsyncSession, loan_file_id: UUID) -> list[Finding]:
    rows = (
        (await db.execute(select(Finding).where(Finding.loan_file_id == loan_file_id)))
        .scalars()
        .all()
    )
    return list(rows)


# --- build_cross_source_facts: the DL address + subject property --------------


async def test_build_facts_populates_dl_and_subject_address(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file_with_dl_at_subject(db_session, company)
    context = await assemble_cross_source_context(db_session, loan_file)

    facts = await build_cross_source_facts(db_session, loan_file=loan_file, context=context)
    assert facts.subject_property_address == _SUBJECT
    assert facts.dl_address is not None and facts.dl_address.value == _SUBJECT


# --- THE GRADUATION: the DL finding is now deterministic + stable -------------


async def test_dl_equals_subject_fires_as_a_deterministic_finding(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file_with_dl_at_subject(db_session, company)
    context = await assemble_cross_source_context(db_session, loan_file)
    facts = await build_cross_source_facts(db_session, loan_file=loan_file, context=context)
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )

    await run_cross_source_deterministic(db_session, loan_file=loan_file, run=run, facts=facts)

    findings = await _findings(db_session, loan_file.id)
    dl = next(f for f in findings if f.rule_id == "xsrc.address.dl_equals_subject")
    assert dl.origin is FindingOrigin.DETERMINISTIC_RULE  # not AI — graduated
    assert dl.confidence == DETERMINISTIC_CONFIDENCE  # certain (exact comparison)
    assert "subject property" in dl.message


async def test_dl_finding_is_stable_across_reruns(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file_with_dl_at_subject(db_session, company)
    context = await assemble_cross_source_context(db_session, loan_file)
    facts = await build_cross_source_facts(db_session, loan_file=loan_file, context=context)

    messages = []
    for _ in range(3):
        run = await create_verification_run(
            db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
        )
        await run_cross_source_deterministic(db_session, loan_file=loan_file, run=run, facts=facts)
        live = [
            f
            for f in await _findings(db_session, loan_file.id)
            if f.rule_id == "xsrc.address.dl_equals_subject" and f.deleted_at is None
        ]
        # Exactly one live finding every run (the prior open one is superseded, re-emitted).
        assert len(live) == 1
        messages.append(live[0].message)
    assert len(set(messages)) == 1  # identical wording every run — no flicker


# --- DE-DUPLICATION: the AI defers on a fired canonical type ------------------


async def test_ai_defers_on_a_type_the_deterministic_rule_fired(db_session: AsyncSession) -> None:
    """DL fires property_address_discrepancy deterministically → the AI's duplicate is dropped,
    but the AI's novel "other" finding is kept."""
    company = await _company(db_session)
    loan_file = await _file_with_dl_at_subject(db_session, company)
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )

    ai_findings = [
        _raw(type="property_address_discrepancy", description="ID address matches the property"),
        _raw(type="other", description="A genuinely novel discrepancy the AI spotted"),
    ]
    await run_cross_source(db_session, loan_file=loan_file, run=run, reason_fn=_stub(ai_findings))

    live = [f for f in await _findings(db_session, loan_file.id) if f.deleted_at is None]
    rule_ids = {f.rule_id for f in live}
    # The deterministic DL rule owns property_address_discrepancy → the AI duplicate is deferred.
    assert "xsrc.address.dl_equals_subject" in rule_ids
    assert "cross_source.property_address_discrepancy" not in rule_ids
    # The AI keeps the novel bucket.
    assert "cross_source.other" in rule_ids


async def test_ai_keeps_a_type_no_deterministic_rule_fired(db_session: AsyncSession) -> None:
    """When the deterministic pass is silent on a type, the AI still surfaces it (no coverage loss)."""
    company = await _company(db_session)
    loan_file = await _file_with_dl_at_subject(db_session, company)
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    # The deterministic pass fires property_address (DL) but NOT income_variance → AI keeps income.
    await run_cross_source(
        db_session,
        loan_file=loan_file,
        run=run,
        reason_fn=_stub([_raw(type="income_variance", description="stated vs docs")]),
    )
    rule_ids = {
        f.rule_id for f in await _findings(db_session, loan_file.id) if f.deleted_at is None
    }
    assert "cross_source.income_variance" in rule_ids


# --- The undisclosed-debt APPLY→recompute cross-link -------------------------


async def test_undisclosed_debt_finding_carries_an_apply_spec(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db_session.add(
        Borrower(loan_file_id=loan_file.id, first_name="Dana", last_name="Sample", is_primary=True)
    )
    await db_session.flush()
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    # A credit-report obligation not on the stated application → undisclosed debt.
    facts = CrossSourceFacts(
        credit_report_liabilities=(ObligationRef("Chase Auto", Decimal("450"), "credit_report"),),
        stated_liabilities=(),
    )
    await run_cross_source_deterministic(db_session, loan_file=loan_file, run=run, facts=facts)

    finding = next(
        f
        for f in await _findings(db_session, loan_file.id)
        if f.rule_id == "xsrc.liability.undisclosed_debt"
    )
    assert finding.details["apply"]["action"] == "add_liability"
    assert finding.details["apply"]["monthly_payment"] == "450"

    # Applying it adds the liability (the APPLY→recompute interlock → the DTI recomputes).
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    liabilities = (
        (
            await db_session.execute(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(liability.monthly_payment == Decimal("450") for liability in liabilities)


# --- Program-agnostic on FHA -------------------------------------------------


async def test_deterministic_cross_source_fires_on_an_fha_file(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file_with_dl_at_subject(db_session, company, program=LoanProgram.FHA)
    context = await assemble_cross_source_context(db_session, loan_file)
    facts = await build_cross_source_facts(db_session, loan_file=loan_file, context=context)
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    _red, _yellow, fired = await run_cross_source_deterministic(
        db_session, loan_file=loan_file, run=run, facts=facts
    )
    assert "property_address_discrepancy" in fired  # program-agnostic — fires on FHA too
