"""LP-124R — employer-count-matches-income-items: REPRODUCE the live rule (rule #3).

The live ``xsrc.income.employer_count_matches_items`` is the parity anchor. Evaluator unit tests pin the
reproduced spec (file-level counts, the None-guard → couldn't-check); DB-backed tests assert the new
engine's verdict MATCHES the live rule (finding vs no-finding) on a match, a mismatch, and an edge case.
"""

from decimal import Decimal

from app.models.stated_financials import StatedEmployer, StatedIncomeItem
from app.services.cross_source import assemble_cross_source_context
from app.services.cross_source_deterministic import build_cross_source_facts
from app.verification.applicability import ApplicabilityState, classify_from_json
from app.verification.cross_source.engine import evaluate_cross_source
from app.verification.evaluators import Verdict, evaluate_rule
from app.verification.evaluators.employer_count import RULE_ID
from app.verification.fact_namespace.snapshot import (
    BorrowerFacts,
    ComputedFacts,
    DocumentedFacts,
    EmployerFacts,
    Fact,
    FactNamespace,
    FactSource,
    FileFacts,
    IncomeItemFacts,
)
from app.verification.runner import run_rule_engine
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import make_borrower, make_company, make_loan_file

_APPLICABILITY = {"scope": {}, "triggers": {}, "required_inputs": []}


def _empty() -> Fact[Decimal]:
    return Fact[Decimal](value=None)


def _income(*, employment: bool | None = True) -> IncomeItemFacts:
    return IncomeItemFacts(
        monthly_amount=Fact.present(Decimal("5000"), source=FactSource.STATED),
        income_type_raw="Base",
        income_type_canonical=Fact[str](value=None),
        employment_income=employment,
    )


def _employer(name: str | None = "Acme Corp") -> EmployerFacts:
    return EmployerFacts(name=name, is_current=True)


def _borrower(
    bid: str,
    *,
    employers: list[EmployerFacts],
    incomes: list[IncomeItemFacts],
) -> BorrowerFacts:
    return BorrowerFacts(
        borrower_id=bid,
        position=1,
        is_primary=True,
        first_name="A",
        last_name="B",
        full_name="A B",
        ssn_masked=Fact[str](value=None),
        date_of_birth=Fact(value=None),
        current_address=Fact.missing(source=FactSource.ABSENT_NOT_PERSISTED),
        income_items=incomes,
        employers=employers,
        documents=[],
    )


def _snapshot(borrowers: list[BorrowerFacts]) -> FactNamespace:
    return FactNamespace(
        loan_file_id="LF",
        file=FileFacts(
            program=Fact[str](value=None),
            loan_purpose=Fact[str](value=None),
            refinance_type=Fact[str](value=None),
            loan_amount=_empty(),
            note_amount=_empty(),
            note_rate_percent=_empty(),
        ),
        borrowers=borrowers,
        property=None,
        liabilities=[],
        assets=[],
        documents=[],
        transactions=[],
        bank_statements=[],
        computed=ComputedFacts(
            ltv=_empty(),
            cltv=_empty(),
            hcltv=_empty(),
            front_end_dti=_empty(),
            back_end_dti=_empty(),
            mi_monthly=_empty(),
            reserves_months=_empty(),
        ),
        documented=DocumentedFacts(
            documented_employers=Fact(value=[], source=FactSource.EXTRACTION),
            documented_income_monthly=_empty(),
            credit_tradelines=_empty(),
            documented_loan_amount=_empty(),
            occupancy_evidence=_empty(),
        ),
    )


def _evaluate(borrowers: list[BorrowerFacts]):
    result = evaluate_rule(RULE_ID, _snapshot(borrowers))
    assert result is not None
    return result


# --------------------------------------------------------------------------- #
# Applicability — the live rule always runs (scope {}, triggers {}, no required inputs)
# --------------------------------------------------------------------------- #


def test_applicability_is_always_ready() -> None:
    assert (
        classify_from_json(_APPLICABILITY, _snapshot([])).state is ApplicabilityState.READY_TO_RUN
    )


# --------------------------------------------------------------------------- #
# Evaluator — the reproduced spec (file-level counts, None-guard)
# --------------------------------------------------------------------------- #


def test_equal_counts_satisfied() -> None:
    b = _borrower(
        "b1", employers=[_employer("Acme"), _employer("Beta")], incomes=[_income(), _income()]
    )
    assert _evaluate([b]).verdict is Verdict.SATISFIED


def test_unequal_counts_finding() -> None:
    b = _borrower("b1", employers=[_employer("Acme")], incomes=[_income(), _income()])
    result = _evaluate([b])
    assert result.verdict is Verdict.FINDING
    obs = " ".join(p.observed for p in result.provenance)
    assert "1 named employer" in obs and "2 employment income item" in obs


def test_zero_on_one_side_is_finding() -> None:
    # Round-5 FIX 9 (intentional, stricter than live): employment income but NO employers → discrepancy.
    assert (
        _evaluate([_borrower("b1", employers=[], incomes=[_income(), _income()])]).verdict
        is Verdict.FINDING
    )
    # and the reverse — employers but NO employment income → also a discrepancy.
    assert (
        _evaluate([_borrower("b2", employers=[_employer("Acme")], incomes=[])]).verdict
        is Verdict.FINDING
    )


def test_no_employment_at_all_is_satisfied() -> None:
    # Both sides zero (a genuinely no-employment file: only non-employment income, no employers) → NOT a
    # discrepancy → satisfied (0 reconciles with 0).
    b = _borrower("b1", employers=[], incomes=[_income(employment=False)])
    assert _evaluate([b]).verdict is Verdict.SATISFIED


def test_nonemployment_and_none_income_not_counted() -> None:
    # employment_income False/None are NOT counted (live truthiness): 1 employer + 1 real employment item
    # (+ a False + a None) → 1 == 1 → satisfied.
    b = _borrower(
        "b1",
        employers=[_employer("Acme")],
        incomes=[_income(), _income(employment=False), _income(employment=None)],
    )
    assert _evaluate([b]).verdict is Verdict.SATISFIED


def test_counts_are_file_level_not_per_borrower() -> None:
    # REPRODUCTION fidelity: the live rule is FILE-LEVEL. Borrower A (2 employers, 0 income) + borrower B
    # (0 employers, 2 employment income) → file totals 2 == 2 → SATISFIED. (Per-borrower would flag each;
    # we match the live file-level behavior, not "improve" it.)
    a = _borrower("a", employers=[_employer("Acme"), _employer("Beta")], incomes=[])
    b = _borrower("b", employers=[], incomes=[_income(), _income()])
    assert _evaluate([a, b]).verdict is Verdict.SATISFIED


def test_outcome_carries_no_employer_names() -> None:
    b = _borrower(
        "b1", employers=[_employer("Secret Employer LLC")], incomes=[_income(), _income()]
    )
    result = _evaluate([b])
    blob = " ".join(p.observed for p in result.provenance)
    assert "Secret Employer LLC" not in blob  # counts only, no PII


# --------------------------------------------------------------------------- #
# Parity with the LIVE rule (the correctness anchor) — DB-backed
# --------------------------------------------------------------------------- #


async def _borrower_with(
    db: AsyncSession, *, loan_file, company, employers: int, employment_items: int
) -> None:
    b = await make_borrower(db, loan_file=loan_file, first_name="Pat", last_name="Q")
    for i in range(employers):
        db.add(StatedEmployer(borrower_id=b.id, employer_name=f"Employer {i}", is_current=True))
    for _ in range(employment_items):
        db.add(
            StatedIncomeItem(
                borrower_id=b.id,
                monthly_amount=Decimal("5000"),
                income_type="Base",
                employment_income=True,
            )
        )
    await db.flush()


async def _live_fires(db: AsyncSession, loan_file) -> bool:
    context = await assemble_cross_source_context(db, loan_file)
    facts = await build_cross_source_facts(db, loan_file=loan_file, context=context)
    results = evaluate_cross_source(
        facts,
        program=loan_file.loan_program,
        loan_purpose=loan_file.loan_purpose,
        refinance_type=loan_file.refinance_type,
    )
    return any(r.rule.rule_id == RULE_ID for r in results)


async def _new_fires(db: AsyncSession, loan_file) -> bool:
    result = await run_rule_engine(db, loan_file)
    return RULE_ID in [o.rule_id for o in result.findings]


async def _insert_rule(db: AsyncSession) -> None:
    from app.models.verification_rule import VerificationRule

    db.add(
        VerificationRule(
            rule_id=RULE_ID,
            name="Employer count matches income items",
            applicability=_APPLICABILITY,
            params={},
            enabled=True,
            validated=True,
        )
    )
    await db.flush()


async def test_parity_mismatch_both_fire(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="ec-mismatch")
    lf = await make_loan_file(db_session, company=company)
    await _borrower_with(db_session, loan_file=lf, company=company, employers=1, employment_items=2)
    await _insert_rule(db_session)
    assert await _new_fires(db_session, lf) is True
    assert await _live_fires(db_session, lf) is True  # parity: both fire


async def test_parity_match_neither_fires(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="ec-match")
    lf = await make_loan_file(db_session, company=company)
    await _borrower_with(db_session, loan_file=lf, company=company, employers=2, employment_items=2)
    await _insert_rule(db_session)
    assert await _new_fires(db_session, lf) is False
    assert await _live_fires(db_session, lf) is False  # parity: neither fires


async def test_zero_case_is_intentional_divergence_from_live(db_session: AsyncSession) -> None:
    # Round-5 FIX 9: 0 employers + employment income → the new engine FIRES a finding (a discrepancy),
    # while the live rule's None-guard is SILENT. This is a DELIBERATE stricter-than-live divergence —
    # NOT a parity bug. (Contrast the mismatch case above, where new and live agree.)
    company = await make_company(db_session, slug="ec-zero-emp")
    lf = await make_loan_file(db_session, company=company)
    await _borrower_with(db_session, loan_file=lf, company=company, employers=0, employment_items=2)
    await _insert_rule(db_session)
    assert await _new_fires(db_session, lf) is True  # new engine: intentional finding
    assert (
        await _live_fires(db_session, lf) is False
    )  # live rule: silent on zero (the gap we close)


async def test_end_to_end_mismatch_finding_not_provisional(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="ec-e2e")
    lf = await make_loan_file(db_session, company=company)
    await _borrower_with(db_session, loan_file=lf, company=company, employers=1, employment_items=3)
    await _insert_rule(db_session)
    result = await run_rule_engine(db_session, lf)
    outcome = next(o for o in result.findings if o.rule_id == RULE_ID)
    assert outcome.provisional is False  # validated=true → authoritative
    assert outcome.provenance


def test_r5fix6_live_owned_gate_declares_reproduced_rules() -> None:
    # FIX 6 — the double-firing gate: reproduced live rules are declared so a future persist layer skips
    # them while the live path still owns them (until LP-161). Latent (runner unwired), pinned here.
    from app.verification.runner import LIVE_PATH_OWNED_RULE_IDS

    assert RULE_ID in LIVE_PATH_OWNED_RULE_IDS
    assert "xsrc.asset.gift_without_letter" in LIVE_PATH_OWNED_RULE_IDS
