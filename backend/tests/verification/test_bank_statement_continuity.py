"""LP-123R — AS-8 bank-statement continuity (NEW rule, self-defined spec).

No live rule to match; certified against the SPEC (group by account → per-account continuity → honest
rollup). Applicability is tested against ``documents`` (the trigger); the evaluator is tested against the
TYPED ``bank_statements`` facts (review FIX 8 — no eval-time coercion). Grouping/dedup/period-end are the
review-fix false-verdict cases.
"""

from datetime import date
from decimal import Decimal

from app.models.verification_rule import VerificationRule
from app.verification.applicability import ApplicabilityState, classify_from_json
from app.verification.evaluators import Verdict, evaluate_rule
from app.verification.evaluators.bank_statement_continuity import RULE_ID
from app.verification.fact_namespace.snapshot import (
    BankStatementFacts,
    ComputedFacts,
    DocumentedFacts,
    DocumentRef,
    Fact,
    FactNamespace,
    FactSource,
    FileFacts,
)
from app.verification.runner import run_rule_engine
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import (
    make_company,
    make_document,
    make_extraction,
    make_loan_file,
)

_AS8_APPLICABILITY = {
    "scope": {},
    "triggers": {
        "all": [
            {
                "kind": "entity_exists",
                "collection": "documents",
                "field": "document_type",
                "op": "eq",
                "value": "bank_statement",
            }
        ]
    },
    "required_inputs": [{"kind": "document", "document_type": "bank_statement"}],
}


def _empty() -> Fact[Decimal]:
    return Fact[Decimal](value=None)


def _fdate(iso: str | None) -> Fact[date]:
    return (
        Fact.present(date.fromisoformat(iso), source=FactSource.EXTRACTION)
        if iso
        else Fact[date](value=None)
    )


def _fdec(value: str | None) -> Fact[Decimal]:
    return (
        Fact.present(Decimal(value), source=FactSource.EXTRACTION)
        if value is not None
        else Fact[Decimal](value=None)
    )


def _bs(
    doc_id: str,
    *,
    bank: str | None = "First Bank",
    acct_type: str | None = "checking",
    masked: str | None = None,
    holder: str | None = None,
    start: str | None = None,
    end: str | None = None,
    beginning: str | None = None,
    ending: str | None = None,
) -> BankStatementFacts:
    return BankStatementFacts(
        source_document_id=doc_id,
        bank_name=bank,
        account_number_masked=masked,
        account_type=acct_type,
        account_holder_name=holder,
        period_start=_fdate(start),
        period_end=_fdate(end),
        beginning_balance=_fdec(beginning),
        ending_balance=_fdec(ending),
    )


def _doc(document_type: str = "bank_statement", *, present: bool = True) -> DocumentRef:
    return DocumentRef(
        document_id="d",
        document_type=document_type,
        present=present,
        current_extraction_id="x" if present else None,
        fields={},
    )


def _snapshot(
    *,
    documents: list[DocumentRef] | None = None,
    bank_statements: list[BankStatementFacts] | None = None,
) -> FactNamespace:
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
        borrowers=[],
        property=None,
        liabilities=[],
        assets=[],
        documents=documents or [],
        transactions=[],
        bank_statements=bank_statements or [],
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


def _evaluate(bank_statements: list[BankStatementFacts]):
    result = evaluate_rule(RULE_ID, _snapshot(bank_statements=bank_statements))
    assert result is not None
    return result


def _observed(result) -> str:
    return " ".join(p.observed for p in result.provenance)


# --------------------------------------------------------------------------- #
# Applicability (documents-entity_exists trigger) — incl. FIX 5
# --------------------------------------------------------------------------- #


def test_no_bank_statement_among_docs_doesnt_apply() -> None:
    assert (
        classify_from_json(_AS8_APPLICABILITY, _snapshot(documents=[_doc("drivers_license")])).state
        is ApplicabilityState.DOESNT_APPLY
    )


def test_fix5_zero_documents_doesnt_apply() -> None:
    # Review FIX 5: documents is reliably loaded, so an EMPTY collection → doesn't-apply (not couldn't-check).
    assert (
        classify_from_json(_AS8_APPLICABILITY, _snapshot(documents=[])).state
        is ApplicabilityState.DOESNT_APPLY
    )


def test_bank_statement_present_is_ready_to_run() -> None:
    assert (
        classify_from_json(_AS8_APPLICABILITY, _snapshot(documents=[_doc()])).state
        is ApplicabilityState.READY_TO_RUN
    )


def test_bank_statement_uploaded_but_not_extracted_is_couldnt_check() -> None:
    assert (
        classify_from_json(_AS8_APPLICABILITY, _snapshot(documents=[_doc(present=False)])).state
        is ApplicabilityState.COULDNT_CHECK
    )


# --------------------------------------------------------------------------- #
# Per-account continuity (evaluator, reads typed bank_statements)
# --------------------------------------------------------------------------- #


def test_one_account_continuous_is_satisfied() -> None:
    stmts = [
        _bs(
            "d1",
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1500",
        ),
        _bs(
            "d2",
            masked="****1",
            start="2026-02-01",
            end="2026-02-28",
            beginning="1500",
            ending="1800",
        ),
        _bs(
            "d3",
            masked="****1",
            start="2026-03-01",
            end="2026-03-31",
            beginning="1800",
            ending="2100",
        ),
    ]
    result = _evaluate(stmts)
    assert result.verdict is Verdict.SATISFIED and result.provenance


def test_one_account_balance_break_is_finding() -> None:
    stmts = [
        _bs(
            "d1",
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1500",
        ),
        _bs(
            "d2",
            masked="****1",
            start="2026-02-01",
            end="2026-02-28",
            beginning="1400",
            ending="1800",
        ),
    ]
    result = _evaluate(stmts)
    assert result.verdict is Verdict.FINDING
    assert "1500" in _observed(result) and "1400" in _observed(result)


def test_one_account_single_statement_is_couldnt_check() -> None:
    stmts = [
        _bs(
            "d1",
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1500",
        )
    ]
    result = _evaluate(stmts)
    assert result.verdict is Verdict.COULDNT_CHECK
    assert "one statement" in _observed(result)


def test_balances_not_extracted_is_couldnt_check() -> None:
    stmts = [_bs("d1", masked="****1"), _bs("d2", masked="****1")]
    assert _evaluate(stmts).verdict is Verdict.COULDNT_CHECK


def test_missing_month_gap_is_finding() -> None:
    # Balances coincidentally chain (Feb net-zero) but Feb is missing → the period-gap check catches it.
    stmts = [
        _bs(
            "d1",
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1500",
        ),
        _bs(
            "d3",
            masked="****1",
            start="2026-03-01",
            end="2026-03-31",
            beginning="1500",
            ending="2000",
        ),
    ]
    result = _evaluate(stmts)
    assert result.verdict is Verdict.FINDING and "gap" in _observed(result)


# --------------------------------------------------------------------------- #
# FIX 1 — dedup / conflict
# --------------------------------------------------------------------------- #


def test_fix1_duplicate_upload_is_not_a_false_finding() -> None:
    # The SAME statement uploaded twice (same account + period + balances) → deduped → one distinct
    # statement → couldn't-check, NOT a false "continuity broken" finding.
    dup = {
        "masked": "****1",
        "start": "2026-01-01",
        "end": "2026-01-31",
        "beginning": "1000",
        "ending": "1500",
    }
    result = _evaluate([_bs("d1", **dup), _bs("d2", **dup)])
    assert result.verdict is Verdict.COULDNT_CHECK
    assert "duplicate" in _observed(result)


def test_fix1_same_period_different_balances_is_conflict_not_break() -> None:
    stmts = [
        _bs(
            "d1",
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1500",
        ),
        _bs(
            "d2",
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="9999",
        ),
    ]
    result = _evaluate(stmts)
    assert result.verdict is Verdict.COULDNT_CHECK and "conflicting" in _observed(result)


# --------------------------------------------------------------------------- #
# FIX 2+3 — complete unique grouping key (never merge different accounts)
# --------------------------------------------------------------------------- #


def test_fix2_same_last4_different_banks_are_separate_accounts() -> None:
    # Chase ****6789 and Wells ****6789 must NOT merge (last-4 collision). Each internally continuous;
    # Chase.ending != Wells.beginning — a merge would be a false finding. Separate → satisfied.
    stmts = [
        _bs(
            "c1",
            bank="Chase",
            masked="****6789",
            start="2026-01-01",
            end="2026-01-31",
            beginning="100",
            ending="200",
        ),
        _bs(
            "c2",
            bank="Chase",
            masked="****6789",
            start="2026-02-01",
            end="2026-02-28",
            beginning="200",
            ending="300",
        ),
        _bs(
            "w1",
            bank="Wells",
            masked="****6789",
            start="2026-01-01",
            end="2026-01-31",
            beginning="9000",
            ending="9100",
        ),
        _bs(
            "w2",
            bank="Wells",
            masked="****6789",
            start="2026-02-01",
            end="2026-02-28",
            beginning="9100",
            ending="9200",
        ),
    ]
    assert _evaluate(stmts).verdict is Verdict.SATISFIED


def test_fix3_checking_and_savings_same_bank_are_separate_accounts() -> None:
    # No masked #, same bank + holder, different account_type → separate accounts (not merged via holder|bank).
    stmts = [
        _bs(
            "c1",
            bank="First Bank",
            acct_type="checking",
            holder="Jamie Lee",
            start="2026-01-01",
            end="2026-01-31",
            beginning="100",
            ending="200",
        ),
        _bs(
            "c2",
            bank="First Bank",
            acct_type="checking",
            holder="Jamie Lee",
            start="2026-02-01",
            end="2026-02-28",
            beginning="200",
            ending="300",
        ),
        _bs(
            "s1",
            bank="First Bank",
            acct_type="savings",
            holder="Jamie Lee",
            start="2026-01-01",
            end="2026-01-31",
            beginning="8000",
            ending="8100",
        ),
        _bs(
            "s2",
            bank="First Bank",
            acct_type="savings",
            holder="Jamie Lee",
            start="2026-02-01",
            end="2026-02-28",
            beginning="8100",
            ending="8200",
        ),
    ]
    assert _evaluate(stmts).verdict is Verdict.SATISFIED


def test_fix2_ungroupable_without_bank_or_type_is_couldnt_check() -> None:
    # Missing bank (can't tell which bank a last-4 belongs to) → ungroupable → couldn't-check, never chained.
    stmts = [
        _bs(
            "d1",
            bank=None,
            masked="****1",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1500",
        ),
        _bs(
            "d2",
            bank=None,
            masked="****1",
            start="2026-02-01",
            end="2026-02-28",
            beginning="1500",
            ending="1800",
        ),
    ]
    result = _evaluate(stmts)
    assert result.verdict is Verdict.COULDNT_CHECK and "could not be matched" in _observed(result)


# --------------------------------------------------------------------------- #
# FIX 4 — period_end required for the gap check (no false satisfied across a hole)
# --------------------------------------------------------------------------- #


def test_fix4_missing_period_end_not_silently_satisfied() -> None:
    # Two statements, but the first has no period_end → not usable → <2 usable → couldn't-check, never a
    # false satisfied that skips the gap check.
    stmts = [
        _bs("d1", masked="****1", start="2026-01-01", end=None, beginning="1000", ending="1500"),
        _bs(
            "d2",
            masked="****1",
            start="2026-03-01",
            end="2026-03-31",
            beginning="1500",
            ending="2000",
        ),
    ]
    assert _evaluate(stmts).verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# Rollup + the Bank A / Bank B case + no cross-account comparison
# --------------------------------------------------------------------------- #


def test_two_single_statement_accounts_is_couldnt_check_not_compared() -> None:
    a = _bs(
        "a",
        bank="A Bank",
        masked="****A",
        start="2026-01-01",
        end="2026-01-31",
        beginning="1000",
        ending="9999",
    )
    b = _bs(
        "b",
        bank="B Bank",
        masked="****B",
        start="2026-01-01",
        end="2026-01-31",
        beginning="0",
        ending="5",
    )
    result = _evaluate([a, b])
    assert result.verdict is Verdict.COULDNT_CHECK
    assert _observed(result).count("only one statement") == 2  # both surfaced, neither compared


def test_continuous_beside_single_rolls_up_couldnt_check_both_surfaced() -> None:
    a1 = _bs(
        "a1",
        bank="A",
        masked="****A",
        start="2026-01-01",
        end="2026-01-31",
        beginning="100",
        ending="200",
    )
    a2 = _bs(
        "a2",
        bank="A",
        masked="****A",
        start="2026-02-01",
        end="2026-02-28",
        beginning="200",
        ending="300",
    )
    b1 = _bs(
        "b1",
        bank="B",
        masked="****B",
        start="2026-03-01",
        end="2026-03-31",
        beginning="50",
        ending="60",
    )
    result = _evaluate([a1, a2, b1])
    assert result.verdict is Verdict.COULDNT_CHECK
    assert "chain continuously" in _observed(result) and "one statement" in _observed(result)


def test_cross_account_is_never_compared() -> None:
    a1 = _bs(
        "a1",
        bank="A",
        masked="****A",
        start="2026-01-01",
        end="2026-01-31",
        beginning="100",
        ending="200",
    )
    a2 = _bs(
        "a2",
        bank="A",
        masked="****A",
        start="2026-02-01",
        end="2026-02-28",
        beginning="200",
        ending="300",
    )
    b1 = _bs(
        "b1",
        bank="B",
        masked="****B",
        start="2026-01-01",
        end="2026-01-31",
        beginning="9000",
        ending="9500",
    )
    b2 = _bs(
        "b2",
        bank="B",
        masked="****B",
        start="2026-02-01",
        end="2026-02-28",
        beginning="9500",
        ending="9900",
    )
    assert _evaluate([a1, a2, b1, b2]).verdict is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# FIX 10 — no PII (real name / masked account) in the outcome (ADR-149)
# --------------------------------------------------------------------------- #


def test_fix10_outcome_carries_no_pii() -> None:
    stmts = [
        _bs(
            "d1",
            bank="First Bank",
            masked="****6789",
            holder="Jamie Lee",
            start="2026-01-01",
            end="2026-01-31",
            beginning="1000",
            ending="1400",
        ),
        _bs(
            "d2",
            bank="First Bank",
            masked="****6789",
            holder="Jamie Lee",
            start="2026-02-01",
            end="2026-02-28",
            beginning="1500",
            ending="1800",
        ),
    ]
    result = _evaluate(stmts)  # a break → finding
    blob = _observed(result) + " " + " ".join(p.path for p in result.provenance)
    assert "Jamie Lee" not in blob and "****6789" not in blob  # no raw name / masked account
    assert any(p.path.startswith("account ") for p in result.provenance)  # ordinal label instead


# --------------------------------------------------------------------------- #
# End-to-end through the runner (DB-backed)
# --------------------------------------------------------------------------- #


async def _insert_as8_rule(db: AsyncSession) -> None:
    db.add(
        VerificationRule(
            rule_id=RULE_ID,
            name="Statement chaining (continuity)",
            applicability=_AS8_APPLICABILITY,
            params={},
            enabled=True,
        )
    )
    await db.flush()


async def _add_statement(db, *, loan_file, company, start, end, beginning, ending) -> None:
    doc = await make_document(
        db, loan_file=loan_file, company=company, document_type="bank_statement"
    )
    await make_extraction(
        db,
        document=doc,
        data={
            "bank_name": {"value": "First Bank", "source": {}},
            "account_type": {"value": "checking", "source": {}},
            "account_number_masked": {"value": "****1", "source": {}},
            "statement_period_start": {"value": start, "source": {}},
            "statement_period_end": {"value": end, "source": {}},
            "beginning_balance": {"value": beginning, "source": {}},
            "ending_balance": {"value": ending, "source": {}},
        },
    )


async def test_end_to_end_continuous_lands_in_satisfied(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="as8-sat")
    lf = await make_loan_file(db_session, company=company)
    await _add_statement(
        db_session,
        loan_file=lf,
        company=company,
        start="2026-01-01",
        end="2026-01-31",
        beginning="1000",
        ending="1500",
    )
    await _add_statement(
        db_session,
        loan_file=lf,
        company=company,
        start="2026-02-01",
        end="2026-02-28",
        beginning="1500",
        ending="1800",
    )
    await _insert_as8_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    assert RULE_ID in [o.rule_id for o in result.satisfied]


async def test_end_to_end_break_lands_in_findings_provisional(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="as8-find")
    lf = await make_loan_file(db_session, company=company)
    await _add_statement(
        db_session,
        loan_file=lf,
        company=company,
        start="2026-01-01",
        end="2026-01-31",
        beginning="1000",
        ending="1500",
    )
    await _add_statement(
        db_session,
        loan_file=lf,
        company=company,
        start="2026-02-01",
        end="2026-02-28",
        beginning="1400",
        ending="1800",
    )
    await _insert_as8_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    outcome = next(o for o in result.findings if o.rule_id == RULE_ID)
    assert outcome.provisional is True and outcome.provenance
