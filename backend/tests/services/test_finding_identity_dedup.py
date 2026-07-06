"""LP-93 — normalized-substance finding identity + dedup.

The live bug: the same discrepancy worded two ways (case + dash/quote/whitespace) showed as
TWO Open findings — the Thermofisher employer-name case ("Thermofisher Life Science – PPD
Development LP." vs "THERMOFISHER LIFE SCIENCE — PPD DEVELOPMENT LP."). These tests prove the
fix: the identity normalizes the subject values (deterministic textual only — NO fuzzy), so
same-substance-different-wording collapses to one, genuinely-different subjects stay separate,
and a re-detected resolved finding keeps its resolution.
"""
# The test data deliberately uses ambiguous-unicode variants (en/em dash, smart quotes).
# ruff: noqa: RUF001, RUF002

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from app.ai.cross_source import CrossSourceRawFinding, CrossSourceResult
from app.models import (
    Borrower,
    Company,
    Finding,
    FindingOrigin,
    FindingResolutionStatus,
    LoanFile,
    LoanProgram,
    User,
    UserRole,
)
from app.models.verification import VerificationTrigger
from app.services.cross_source import run_cross_source
from app.services.cross_source_deterministic import run_cross_source_deterministic
from app.services.finding_identity import finding_identity, normalize_text
from app.services.finding_resolution import override_finding
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from app.verification.cross_source import CrossSourceFacts
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# The two documented-employer strings differ ONLY in case + dash type (en vs em).
_EMP_A = "Thermofisher Life Science – PPD Development LP."  # en-dash
_EMP_B = "THERMOFISHER LIFE SCIENCE — PPD DEVELOPMENT LP."  # em-dash
_EMP_DIFFERENT = "Swad Mania LLC"
_EMP_FUZZY = "Thermo Fisher Scientific"  # a REAL textual difference (spacing/words)


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
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


async def _file(db: AsyncSession, company: Company) -> LoanFile:
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(Borrower(loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True))
    await db.flush()
    return loan_file


async def _run_employers(
    db: AsyncSession, loan_file: LoanFile, documented: tuple[str, ...]
) -> None:
    """Run the deterministic pass with the given documented employers (none stated → all fire)."""
    facts = CrossSourceFacts(
        stated_employers=("Acme Payroll Co",),  # a DIFFERENT stated employer → the docs don't match
        documented_employers=documented,
        stated_employer_count=1,
    )
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    await run_cross_source_deterministic(db, loan_file=loan_file, run=run, facts=facts)


async def _employer_findings(db: AsyncSession, loan_file_id: UUID) -> list[Finding]:
    rows = (
        (
            await db.execute(
                select(Finding).where(
                    Finding.loan_file_id == loan_file_id,
                    Finding.rule_id == "xsrc.income.employer_name_consistency",
                    Finding.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# --- normalize_text: deterministic textual normalization ----------------------


def test_normalize_text_folds_case_dash_quote_whitespace() -> None:
    assert normalize_text("THERMOFISHER") == normalize_text("Thermofisher")
    # en-dash / em-dash / hyphen all canonicalize to the same.
    assert normalize_text("A – B") == normalize_text("A — B") == normalize_text("A - B")
    # smart quotes → straight.
    assert normalize_text("O’Brien") == normalize_text("O'Brien")
    # collapsed whitespace + trim.
    assert normalize_text("  a   b  ") == "a b"


def test_normalize_text_keeps_real_textual_differences() -> None:
    # NOT fuzzy: a genuine spacing/word difference stays distinct.
    assert normalize_text("Thermofisher") != normalize_text("Thermo Fisher Scientific")
    assert normalize_text("Acme LLC") != normalize_text("Acme Inc")


# --- finding_identity: same substance → same identity -------------------------


def test_identity_collapses_case_and_dash_variants() -> None:
    a = Finding(
        rule_id="xsrc.income.employer_name_consistency",
        details={"type": "employer_mismatch", "subject_key": f"employer_name:{_EMP_A.lower()}"},
    )
    b = Finding(
        rule_id="xsrc.income.employer_name_consistency",
        details={"type": "employer_mismatch", "subject_key": f"employer_name:{_EMP_B.lower()}"},
    )
    assert finding_identity(a) == finding_identity(b)


def test_identity_separates_different_subjects() -> None:
    a = Finding(
        rule_id="xsrc.income.employer_name_consistency",
        details={"type": "employer_mismatch", "subject_key": "employer_name:thermofisher"},
    )
    b = Finding(
        rule_id="xsrc.income.employer_name_consistency",
        details={"type": "employer_mismatch", "subject_key": "employer_name:swad mania llc"},
    )
    assert finding_identity(a) != finding_identity(b)


# --- The live repro: two Thermofisher findings collapse to one ----------------


async def test_case_punctuation_duplicate_collapses_to_one(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run_employers(db_session, loan_file, (_EMP_A, _EMP_B))

    findings = await _employer_findings(db_session, loan_file.id)
    assert len(findings) == 1  # the two casings/dashes are ONE finding
    # The FIRST wording is kept (not overwritten by the second casing).
    assert findings[0].message == f"Documented employer not among the stated employers: {_EMP_A}."


async def test_genuinely_different_employers_stay_separate(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run_employers(db_session, loan_file, (_EMP_A, _EMP_DIFFERENT))

    findings = await _employer_findings(db_session, loan_file.id)
    assert len(findings) == 2  # two different employers → two findings (no over-collapse)


async def test_no_fuzzy_merge(db_session: AsyncSession) -> None:
    """ "Thermofisher" vs "Thermo Fisher Scientific" is a REAL textual difference — stays separate."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run_employers(db_session, loan_file, ("Thermofisher", _EMP_FUZZY))

    findings = await _employer_findings(db_session, loan_file.id)
    assert len(findings) == 2  # deterministic normalization only — no fuzzy similarity


# --- Resolved finding re-detected preserves its resolution --------------------


async def test_resolved_finding_re_detected_keeps_resolution(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)

    # Run 1: the employer fires as an Open finding.
    await _run_employers(db_session, loan_file, (_EMP_A,))
    findings = await _employer_findings(db_session, loan_file.id)
    assert len(findings) == 1
    # The processor overrides (dismisses) it.
    await override_finding(
        db_session, finding=findings[0], actor_user_id=user.id, reason="Legal name / DBA confirmed"
    )

    # Run 2: the SAME employer re-detects, worded differently (case/dash).
    await _run_employers(db_session, loan_file, (_EMP_B,))

    findings = await _employer_findings(db_session, loan_file.id)
    assert len(findings) == 1  # not duplicated
    # The resolution is preserved — not reopened.
    assert findings[0].resolution_status is FindingResolutionStatus.OVERRIDDEN
    assert findings[0].resolution_note == "Legal name / DBA confirmed"


# --- Uniform: the dedup applies to AI findings too ----------------------------


def _raw(**kw: Any) -> CrossSourceRawFinding:
    base: dict[str, Any] = {
        "type": "asset_discrepancy",
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


async def test_ai_findings_dedup_on_normalized_substance(db_session: AsyncSession) -> None:
    """Two AI findings of the same substance (case/dash only) collapse to one (uniform)."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )

    # Same type + same document_value differing only in case/dash → same identity.
    ai = [
        _raw(
            type="asset_discrepancy", description="Large deposit – unsourced", document_value=_EMP_A
        ),
        _raw(
            type="asset_discrepancy", description="LARGE DEPOSIT — UNSOURCED", document_value=_EMP_B
        ),
        _raw(
            type="asset_discrepancy", description="A different asset", document_value=_EMP_DIFFERENT
        ),
    ]
    await run_cross_source(db_session, loan_file=loan_file, run=run, reason_fn=_stub(ai))

    ai_findings = (
        (
            await db_session.execute(
                select(Finding).where(
                    Finding.loan_file_id == loan_file.id,
                    Finding.origin == FindingOrigin.AI_CROSS_SOURCE,
                    Finding.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    # The two same-substance AI findings collapse; the genuinely-different one stays → 2 total.
    assert len(ai_findings) == 2


# --- Tenant scoping -----------------------------------------------------------


async def test_dedup_is_tenant_scoped(db_session: AsyncSession) -> None:
    """Two companies with the same employer discrepancy each get their own finding."""
    company_a = await _company(db_session, "company-a")
    company_b = await _company(db_session, "company-b")
    file_a = await _file(db_session, company_a)
    file_b = await _file(db_session, company_b)

    await _run_employers(db_session, file_a, (_EMP_A,))
    await _run_employers(db_session, file_b, (_EMP_A,))

    assert len(await _employer_findings(db_session, file_a.id)) == 1
    assert len(await _employer_findings(db_session, file_b.id)) == 1  # not deduped across files
