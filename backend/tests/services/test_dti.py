"""The DTI calculator service (LP-76) — auto-populate, override, findings-couple.

Covers auto-population from the structured data, override (precedence + audit),
the effective-limit resolution (program default + overlay-tightened), the
unresolved-findings alert, and recompute-on-applied-finding (LP-76 is a recompute
consumer of LP-75's hook). Uses the transaction-rollback ``db_session`` fixture.
"""

from decimal import Decimal

from app.models import (
    ActivityLog,
    ActivityType,
    Borrower,
    Company,
    Document,
    DocumentStatus,
    Extraction,
    ExtractionStatus,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    Lender,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    UploadSource,
    User,
    UserRole,
)
from app.schemas.dti import DtiOverrideInput
from app.services.dti import (
    HOUSING_MORTGAGE_INSURANCE,
    UnknownDtiFieldError,
    build_dti_calculation,
    clear_dti_override,
    gate_display_ratios,
    set_dti_override,
)
from app.services.finding_resolution import apply_finding
from app.services.loan_files import create_loan_file
from app.verification.overlays.samples import SAMPLE_OVERLAY_LENDER_SLUG
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _seed_housing(
    db: AsyncSession,
    loan_file,
    *,
    annual_tax: str = "3600",  # → 300/mo
    annual_premium: str = "1200",  # → 100/mo
) -> None:
    """Seed the REQUIRED housing extraction inputs (a property-tax bill + a homeowners binder) so the DTI
    is computable, not gated. LP-375: absent taxes/insurance now fail-closes the DTI (absent≠0), so a math
    test must provide them. Documents are created directly (the DTI reads the extraction, not the bytes)."""
    for doc_type, field, value in (
        ("property_tax_bill", "annual_tax_amount", annual_tax),
        ("homeowners_insurance", "annual_premium", annual_premium),
    ):
        doc = Document(
            loan_file_id=loan_file.id,
            original_filename=f"{doc_type}.pdf",
            mime_type="application/pdf",
            file_size_bytes=1,
            storage_path=f"seed/{doc_type}",
            document_type=doc_type,
            status=DocumentStatus.COMPLETED,
            upload_source=UploadSource.USER_UPLOAD,
        )
        db.add(doc)
        await db.flush()
        db.add(
            Extraction(
                document_id=doc.id,
                version=1,
                is_current=True,
                extracted_data={field: {"value": value}},
                extraction_status=ExtractionStatus.SUCCEEDED,
            )
        )
    await db.flush()


async def _file_with_financials(
    db: AsyncSession,
    company: Company,
    *,
    lender_id=None,
    income: Decimal = Decimal("10000"),
    debt: Decimal = Decimal("2000"),
    with_housing: bool = True,
):
    """A Conventional file: $10k income, a $2k debt, $100k @ 0% / 360mo (P&I = 277.78). With
    ``with_housing`` (default), also seeds taxes ($300/mo) + insurance ($100/mo) so the DTI computes;
    pass ``with_housing=False`` to exercise the LP-375 fail-closed gate (a required input unknown)."""
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL, lender_id=lender_id
    )
    loan_file.note_amount = Decimal("100000")
    loan_file.note_rate_percent = Decimal("0")
    loan_file.amortization_months = 360
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Pat", last_name="B", is_primary=True)
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
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=debt
        )
    )
    await db.flush()
    if with_housing:
        await _seed_housing(db, loan_file)
    return loan_file


async def test_auto_populates_from_structured_data(db_session: AsyncSession) -> None:
    """The calculator opens already filled from the file's stated data."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.gross_monthly_income == Decimal("10000")
    # Income itemized (one stated item).
    assert len(calc.income_items) == 1
    assert calc.income_items[0].auto_amount == Decimal("10000")
    assert calc.income_items[0].source == "stated"
    # Housing itemized: P&I computed ($100k / 360 @ 0% = 277.78) + the 4 placeholders.
    pi = next(i for i in calc.housing_items if i.key == "housing.principal_interest")
    assert pi.auto_amount == Decimal("277.78")
    assert pi.source == "computed"
    # Debt itemized.
    assert len(calc.debt_items) == 1
    assert calc.debt_items[0].auto_amount == Decimal("2000")
    # Ratios: housing (277.78 P&I + 300 taxes + 100 insurance) = 677.78 / 10000 = 6.78;
    # back (677.78 + 2000)/10000 = 26.78. Not gated — the required housing inputs are present.
    assert calc.gated is False and calc.gate_reason is None
    assert calc.front_end_dti == Decimal("6.78")
    assert calc.back_end_dti == Decimal("26.78")
    # The explicit formula is present.
    assert "Back-end DTI" in calc.back_end_formula


async def test_gated_when_required_housing_input_unknown(db_session: AsyncSession) -> None:
    """LP-375 — the $0.00 fix: with no insurance binder / no tax bill, the DTI is GATED (the display path
    catching up to the honest snapshot path), NOT a confident ratio resting on a fabricated 0."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company, with_housing=False)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    # The service marks it GATED with a reason naming the unknown inputs. (The ratios stay computed here so
    # the snapshot path can re-gate from the lines; the DISPLAY view nulls them — asserted below.)
    assert calc.gated is True
    assert calc.gate_reason is not None
    assert "Homeowners insurance is unknown" in calc.gate_reason
    assert "Property taxes is unknown" in calc.gate_reason
    # The required inputs surface as UNKNOWN — never a fabricated $0.00 "Extracted".
    insurance = next(i for i in calc.housing_items if i.key == "housing.insurance")
    taxes = next(i for i in calc.housing_items if i.key == "housing.taxes")
    assert insurance.unknown is True and insurance.auto_amount is None
    assert taxes.unknown is True and taxes.auto_amount is None

    # The DISPLAY view nulls the ratios (no confident number on a fabricated 0) + marks the limit unknown.
    display = gate_display_ratios(calc)
    assert display.front_end_dti is None and display.back_end_dti is None
    assert display.limit.status == "unknown"
    # And it never fabricates a 0 for the unknown inputs (the line stays unknown, not "$0.00").
    assert next(i for i in display.housing_items if i.key == "housing.insurance").unknown is True


async def test_effective_limit_program_default(db_session: AsyncSession) -> None:
    """A Conventional file shows the 50% investor default, pass/over computed."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.limit.back_end_max == Decimal("50")
    assert calc.limit.source == "program_default"
    assert calc.limit.status == "pass"  # 22.78 <= 50


async def test_effective_limit_overlay_tightened(db_session: AsyncSession) -> None:
    """A lender overlay tightens the limit to 45 (LP-74's effective rule)."""
    company = await _company(db_session, "acme")
    lender = Lender(
        company_id=company.id,
        name="Sample Overlay Bank",
        slug=SAMPLE_OVERLAY_LENDER_SLUG,
        supported_programs=["conventional"],
    )
    db_session.add(lender)
    await db_session.flush()
    loan_file = await _file_with_financials(db_session, company, lender_id=lender.id)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.limit.back_end_max == Decimal("45")
    assert calc.limit.source == "overlay"
    assert calc.limit.lender_slug == SAMPLE_OVERLAY_LENDER_SLUG


async def test_override_takes_precedence_recomputes_and_is_audited(
    db_session: AsyncSession,
) -> None:
    """Overriding a debt changes the effective value, recomputes, and is logged."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)
    debt_key = (await build_dti_calculation(db_session, loan_file=loan_file)).debt_items[0].key

    # Override the $2000 debt down to $0 (paid at closing).
    calc = await set_dti_override(
        db_session,
        loan_file=loan_file,
        field_key=debt_key,
        data=DtiOverrideInput(amount=Decimal("0"), note="Paid at closing"),
        actor_user_id=user.id,
    )

    debt = next(i for i in calc.debt_items if i.key == debt_key)
    assert debt.override_amount == Decimal("0")
    assert debt.amount == Decimal("0")
    assert debt.overridden is True
    assert debt.source == "override"
    # Back-end recomputed without the debt: (277.78 + 300 + 100) / 10000 = 6.78.
    assert calc.back_end_dti == Decimal("6.78")

    # Audited with the prior value (2000 → 0).
    logs = (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.DTI_OVERRIDDEN,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].detail["field_key"] == debt_key
    assert logs[0].detail["from"] == "2000.00"
    assert logs[0].detail["to"] == "0"
    assert logs[0].actor_user_id == user.id


async def test_override_persists_and_clears(db_session: AsyncSession) -> None:
    """An override persists across reads; clearing reverts to the auto value."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)

    await set_dti_override(
        db_session,
        loan_file=loan_file,
        field_key=HOUSING_MORTGAGE_INSURANCE,
        data=DtiOverrideInput(amount=Decimal("150")),
        actor_user_id=user.id,
    )
    # Persists on a fresh read.
    reread = await build_dti_calculation(db_session, loan_file=loan_file)
    mi = next(i for i in reread.housing_items if i.key == HOUSING_MORTGAGE_INSURANCE)
    assert mi.amount == Decimal("150")
    assert mi.overridden is True

    # Clearing reverts to the auto value (None → 0).
    cleared = await clear_dti_override(
        db_session, loan_file=loan_file, field_key=HOUSING_MORTGAGE_INSURANCE, actor_user_id=user.id
    )
    mi2 = next(i for i in cleared.housing_items if i.key == HOUSING_MORTGAGE_INSURANCE)
    assert mi2.overridden is False
    assert mi2.amount == Decimal("0")


async def test_unknown_field_key_rejected(db_session: AsyncSession) -> None:
    """Overriding a non-existent input field is rejected."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)

    try:
        await set_dti_override(
            db_session,
            loan_file=loan_file,
            field_key="debt.does-not-exist",
            data=DtiOverrideInput(amount=Decimal("1")),
            actor_user_id=user.id,
        )
    except UnknownDtiFieldError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownDtiFieldError")


async def test_unresolved_findings_alert(db_session: AsyncSession) -> None:
    """An open in-scope finding raises the unresolved-findings alert."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company)
    assert (
        await build_dti_calculation(db_session, loan_file=loan_file)
    ).findings.unresolved is False

    db_session.add(
        Finding(
            loan_file_id=loan_file.id,
            rule_id="cross_source.income.discrepancy",
            origin=FindingOrigin.AI_CROSS_SOURCE,
            confidence=0.9,
            status=FindingStatus.YELLOW,
            category=FindingCategory.INCOME,
            message="Possible undisclosed obligation.",
        )
    )
    await db_session.flush()

    calc = await build_dti_calculation(db_session, loan_file=loan_file)
    assert calc.findings.unresolved is True
    assert calc.findings.open_in_scope_count == 1


async def test_recompute_on_applied_finding(db_session: AsyncSession) -> None:
    """Applying an obligation finding adds a liability → the DTI recomputes higher.

    LP-76 is a recompute consumer of LP-75's apply hook: the structured-data
    change (a new liability) flows straight into the next calculation.
    """
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)
    before = await build_dti_calculation(db_session, loan_file=loan_file)

    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.liabilities.undisclosed",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=0.8,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CROSS_SOURCE,
        message="Undisclosed $800 obligation on the credit report.",
        details={"apply": {"action": "add_liability", "monthly_payment": "800"}},
    )
    db_session.add(finding)
    await db_session.flush()

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    after = await build_dti_calculation(db_session, loan_file=loan_file)
    assert len(after.debt_items) == len(before.debt_items) + 1
    assert after.monthly_debts == before.monthly_debts + Decimal("800")
    assert after.back_end_dti is not None and before.back_end_dti is not None
    assert after.back_end_dti > before.back_end_dti  # the DTI rose


async def test_calculation_is_tenant_scoped(db_session: AsyncSession) -> None:
    """Auto-population reads only the file's own data (per-file)."""
    company = await _company(db_session, "acme")
    other = await _company(db_session, "other")
    mine = await _file_with_financials(db_session, company, income=Decimal("10000"))
    theirs = await _file_with_financials(db_session, other, income=Decimal("99999"))

    calc = await build_dti_calculation(db_session, loan_file=mine)
    assert calc.gross_monthly_income == Decimal("10000")  # not theirs
    assert theirs.id != mine.id


def test_display_and_snapshot_required_gates_stay_in_sync() -> None:
    # DRIFT GUARD (LP-375 review): the DISPLAY gate (_REQUIRED_HOUSING_KEYS, keyed by housing line keys)
    # and the SNAPSHOT gate (_REQUIRED_DTI_TAGS, keyed by fact-tag ids) must name the SAME required inputs
    # — they live in different modules (a one-directional dependency forbids sharing one constant), so a
    # third required input added to one and not the other would silently make the /dti card and the
    # snapshot calc disagree on gating. _DTI_FROM_TAG is the line-key → tag-id map that bridges them.
    from app.services.dti import _REQUIRED_HOUSING_KEYS
    from app.verification.snapshot.calculations_section import _DTI_FROM_TAG, _REQUIRED_DTI_TAGS

    assert {_DTI_FROM_TAG[key] for key in _REQUIRED_HOUSING_KEYS} == _REQUIRED_DTI_TAGS
