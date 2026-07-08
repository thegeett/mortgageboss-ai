"""LP-125R — AS-1 large-deposit sourcing (build-to-spec; AS-1 is dormant, no live anchor).

The PINNING FIXTURE SET (P7) — all edge cases up front so this fiddly rule (threshold + per-account +
payroll-exclusion + sourcing) does not need a second pass: unsourced→finding, sourcing-docs-present→
couldn't-check (P2, no false-green), sub-threshold & payroll→not-flagged, missing-income & no-description→
couldn't-check, per-account (ungroupable account)→couldn't-check, empty-docs→doesn't-apply, end-to-end.
"""

from datetime import date
from decimal import Decimal

from app.models.verification_rule import VerificationRule
from app.verification.applicability import ApplicabilityState, classify_from_json
from app.verification.evaluators import Verdict, evaluate_rule
from app.verification.evaluators.large_deposit import RULE_ID
from app.verification.fact_namespace.snapshot import (
    BankStatementFacts,
    BorrowerFacts,
    ComputedFacts,
    DocumentedFacts,
    DocumentRef,
    Fact,
    FactNamespace,
    FactSource,
    FileFacts,
    IncomeItemFacts,
    TransactionFacts,
)
from app.verification.runner import run_rule_engine
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import make_borrower, make_company, make_loan_file

_APPLICABILITY = {
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
    "required_inputs": [
        {"kind": "data_field", "path": "transactions[].amount"},
        {"kind": "data_field", "path": "borrowers[].income_items[].monthly_amount"},
    ],
}


def _empty() -> Fact[Decimal]:
    return Fact[Decimal](value=None)


def _income(amount: str = "5000") -> IncomeItemFacts:
    return IncomeItemFacts(
        monthly_amount=Fact.present(Decimal(amount), source=FactSource.STATED),
        income_type_raw="Base",
        income_type_canonical=Fact[str](value=None),
        employment_income=True,
    )


def _borrower(incomes: list[IncomeItemFacts]) -> BorrowerFacts:
    return BorrowerFacts(
        borrower_id="b1",
        position=1,
        is_primary=True,
        first_name="A",
        last_name="B",
        full_name="A B",
        ssn_masked=Fact[str](value=None),
        date_of_birth=Fact(value=None),
        current_address=Fact.missing(source=FactSource.ABSENT_NOT_PERSISTED),
        income_items=incomes,
        employers=[],
        documents=[],
    )


def _bank_stmt(
    doc_id: str = "bs1", *, bank: str | None = "Chase", masked: str | None = "****1"
) -> BankStatementFacts:
    return BankStatementFacts(
        source_document_id=doc_id,
        bank_name=bank,
        account_number_masked=masked,
        account_type="checking",
        account_holder_name=None,
        period_start=Fact[date](value=None),
        period_end=Fact[date](value=None),
        beginning_balance=_empty(),
        ending_balance=_empty(),
    )


def _txn(
    amount: str, *, ttype: str = "deposit", desc: str | None = "Check deposit", doc_id: str = "bs1"
) -> TransactionFacts:
    return TransactionFacts(
        source_document_id=doc_id,
        date=Fact[date](value=None),
        amount=Fact.present(Decimal(amount), source=FactSource.EXTRACTION),
        description=desc,
        transaction_type=ttype,
    )


def _doc(document_type: str, *, present: bool = True) -> DocumentRef:
    return DocumentRef(
        document_id=f"d-{document_type}",
        document_type=document_type,
        present=present,
        current_extraction_id="x",
        fields={},
    )


def _snapshot(
    *,
    incomes: list[IncomeItemFacts] | None = None,
    transactions: list[TransactionFacts] | None = None,
    bank_statements: list[BankStatementFacts] | None = None,
    documents: list[DocumentRef] | None = None,
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
        borrowers=[_borrower(incomes if incomes is not None else [_income()])],
        property=None,
        liabilities=[],
        assets=[],
        documents=documents if documents is not None else [_doc("bank_statement")],
        transactions=transactions or [],
        bank_statements=bank_statements if bank_statements is not None else [_bank_stmt()],
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


def _evaluate(**kw):
    result = evaluate_rule(RULE_ID, _snapshot(**kw), {"large_deposit_pct": 50})
    assert result is not None
    return result


def _obs(result) -> str:
    return " ".join(p.observed for p in result.provenance)


# income 5000 → threshold 2500 (50%). >2500 = large; <=2500 = sub-threshold.


# --------------------------------------------------------------------------- #
# Applicability
# --------------------------------------------------------------------------- #


def test_empty_documents_doesnt_apply() -> None:  # P3
    assert (
        classify_from_json(_APPLICABILITY, _snapshot(documents=[])).state
        is ApplicabilityState.DOESNT_APPLY
    )


def test_bank_statement_with_txn_and_income_ready() -> None:
    assert (
        classify_from_json(_APPLICABILITY, _snapshot(transactions=[_txn("3000")])).state
        is ApplicabilityState.READY_TO_RUN
    )


# --------------------------------------------------------------------------- #
# Evaluator — the pinning fixture set
# --------------------------------------------------------------------------- #


def test_large_unsourced_deposit_is_finding() -> None:
    # 3000 > 2500, non-payroll, NO sourcing docs → FINDING.
    result = _evaluate(transactions=[_txn("3000")], documents=[_doc("bank_statement")])
    assert result.verdict is Verdict.FINDING and "3000" in _obs(result)


def test_large_deposit_with_sourcing_docs_is_couldnt_check() -> None:  # P2 (no false-green)
    # 3000 > 2500, non-payroll, gift letter present on file → indeterminate (can't match) → couldn't-check.
    result = _evaluate(
        transactions=[_txn("3000")],
        documents=[_doc("bank_statement"), _doc("gift_letter")],
    )
    assert result.verdict is Verdict.COULDNT_CHECK and "verify" in _obs(result)


def test_sub_threshold_deposit_not_flagged() -> None:
    assert _evaluate(transactions=[_txn("2000")]).verdict is Verdict.SATISFIED


def test_large_payroll_deposit_not_flagged() -> None:  # P2 exclusion
    result = _evaluate(transactions=[_txn("3000", desc="PAYROLL DIRECT DEPOSIT")])
    assert result.verdict is Verdict.SATISFIED


def test_missing_income_basis_is_couldnt_check() -> None:  # P1/P2
    result = _evaluate(incomes=[], transactions=[_txn("3000")])
    assert result.verdict is Verdict.COULDNT_CHECK and "income" in result.message.lower()


def test_large_deposit_no_description_is_couldnt_check() -> None:  # P2 (can't tell payroll)
    result = _evaluate(transactions=[_txn("3000", desc=None)])
    assert result.verdict is Verdict.COULDNT_CHECK and "payroll" in _obs(result)


def test_ungroupable_account_is_couldnt_check() -> None:  # P6
    # The deposit's statement can't be grouped to an account (no bank/masked) → couldn't-check, never blind.
    result = _evaluate(
        transactions=[_txn("3000", doc_id="bs1")],
        bank_statements=[_bank_stmt("bs1", bank=None, masked=None)],
    )
    assert result.verdict is Verdict.COULDNT_CHECK and "account can't be determined" in _obs(result)


def test_no_deposits_is_satisfied() -> None:
    assert _evaluate(transactions=[]).verdict is Verdict.SATISFIED


def test_outcome_carries_no_masked_account() -> None:  # ADR-150
    result = _evaluate(transactions=[_txn("3000")], bank_statements=[_bank_stmt(masked="****9876")])
    blob = _obs(result) + " " + " ".join(p.path for p in result.provenance)
    assert "****9876" not in blob and any(p.path.startswith("account ") for p in result.provenance)


# --------------------------------------------------------------------------- #
# End-to-end through the runner
# --------------------------------------------------------------------------- #


async def test_end_to_end_finding_not_provisional(db_session: AsyncSession) -> None:
    from app.models.stated_financials import StatedIncomeItem
    from tests.integration.factories import make_document, make_extraction

    company = await make_company(db_session, slug="as1-e2e")
    lf = await make_loan_file(db_session, company=company)
    borrower = await make_borrower(db_session, loan_file=lf, first_name="Pat", last_name="Q")
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=Decimal("5000"),
            income_type="Base",
            employment_income=True,
        )
    )
    doc = await make_document(
        db_session, loan_file=lf, company=company, document_type="bank_statement"
    )
    await make_extraction(
        db_session,
        document=doc,
        data={
            "bank_name": {"value": "Chase", "source": {}},
            "account_number_masked": {"value": "****1", "source": {}},
            "account_type": {"value": "checking", "source": {}},
            "transactions": [
                {
                    "amount": "8000",
                    "transaction_type": "deposit",
                    "description": "Wire in",
                    "date": "2026-01-10",
                }
            ],
        },
    )
    db_session.add(
        VerificationRule(
            rule_id=RULE_ID,
            name="Large-deposit sourcing",
            applicability=_APPLICABILITY,
            params={"large_deposit_pct": 50},
            enabled=True,
            validated=True,
        )
    )
    await db_session.flush()

    result = await run_rule_engine(db_session, lf)
    outcome = next(o for o in result.findings if o.rule_id == RULE_ID)
    assert outcome.provisional is False  # validated=true
    assert outcome.provenance
