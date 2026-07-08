"""LP-125R — AS-1 large-deposit sourcing (build-to-spec; AS-1 is dormant, no live anchor).

The PINNING FIXTURE SET (P7) — all edge cases up front so this fiddly rule (threshold + per-account +
payroll-exclusion + sourcing) does not need a second pass: unsourced→finding, sourcing-docs-present→
couldn't-check (P2, no false-green), sub-threshold & payroll→not-flagged, missing-income & no-description→
couldn't-check, per-account (ungroupable account)→couldn't-check, empty-docs→doesn't-apply, end-to-end.
"""

from datetime import date
from decimal import Decimal

import pytest
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
    EmployerFacts,
    Fact,
    FactNamespace,
    FactSource,
    FileFacts,
    IncomeItemFacts,
    TransactionFacts,
)
from app.verification.fact_namespace.transaction_kind import classify_transaction_kind
from app.verification.runner import run_rule_engine
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import make_borrower, make_company, make_loan_file

# No required_inputs (LP-125R FIX 3+7): the evaluator self-guards; the bank-statement trigger is the gate.
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
    "required_inputs": [],
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
    amount: str | None = "3000",
    *,
    ttype: str | None = "deposit",
    desc: str | None = "Check deposit",
    doc_id: str = "bs1",
) -> TransactionFacts:
    # transaction_kind is computed by the REAL classifier (as the builder does), so tests exercise the
    # deterministic deposit-detection, not a hardcoded kind.
    amt = Decimal(amount) if amount is not None else None
    return TransactionFacts(
        source_document_id=doc_id,
        date=Fact[date](value=None),
        amount=Fact.present(amt, source=FactSource.EXTRACTION)
        if amt is not None
        else Fact[Decimal](value=None),
        description=desc,
        transaction_type=ttype,
        transaction_kind=classify_transaction_kind(ttype, amt),
    )


def _doc(
    document_type: str, *, present: bool = True, fields: dict[str, str] | None = None
) -> DocumentRef:
    # A sourcing doc counts only when present AND has extracted fields (FIX 4) — default a non-empty map.
    return DocumentRef(
        document_id=f"d-{document_type}",
        document_type=document_type,
        present=present,
        current_extraction_id="x",
        fields=fields if fields is not None else {"x": "1"},
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


def _snapshot_with_borrower(borrower: BorrowerFacts, **kw) -> FactNamespace:
    return _snapshot(**kw).model_copy(update={"borrowers": [borrower]})


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
# FIX 1 — deposit detection by the deterministic transaction_kind (not exact "deposit" text)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ttype", ["credit", "ACH credit", "mobile deposit", "DEP", "wire"])
def test_fix1_free_text_deposit_types_are_detected(ttype: str) -> None:
    # A large money-in typed anything-but-literal-"deposit" is still assessed → FINDING (no sourcing).
    result = _evaluate(transactions=[_txn("3000", ttype=ttype, desc="Incoming funds")])
    assert result.verdict is Verdict.FINDING, ttype


def test_fix1_unrecognized_credit_is_treated_as_deposit() -> None:
    # A novel credit phrasing with a positive amount is conservatively a deposit → assessed (FINDING).
    result = _evaluate(transactions=[_txn("3000", ttype="remote capture xyz", desc="Funds in")])
    assert result.verdict is Verdict.FINDING


@pytest.mark.parametrize("ttype", ["withdrawal", "fee", "ATM withdrawal", "service charge"])
def test_fix1_debits_are_not_deposits(ttype: str) -> None:
    result = _evaluate(transactions=[_txn("3000", ttype=ttype)])
    assert result.verdict is Verdict.SATISFIED, ttype


def test_fix1_deposit_with_no_amount_is_couldnt_check() -> None:
    result = _evaluate(transactions=[_txn(None, ttype="deposit")])
    assert result.verdict is Verdict.COULDNT_CHECK and "no amount" in _obs(result)


def test_fix1_unclassifiable_no_amount_line_is_not_a_deposit() -> None:
    # An unrecognized line with no amount (e.g. "balance forward") can't be a large deposit → not flagged.
    result = _evaluate(transactions=[_txn(None, ttype="balance forward", desc="carryover")])
    assert result.verdict is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# FIX 2 — word-boundary payroll; employer name does NOT falsely exclude
# --------------------------------------------------------------------------- #


def test_fix2_employer_name_does_not_falsely_exclude() -> None:
    # An employer named "Ally" must NOT exclude "transfer to ally savings" (that would hide a real deposit).
    borrower = _borrower([_income("5000")])
    borrower = borrower.model_copy(
        update={"employers": [EmployerFacts(name="Ally", is_current=True)]}
    )
    snap = _snapshot_with_borrower(
        borrower, transactions=[_txn("3000", desc="transfer to ally savings")]
    )
    result = evaluate_rule(RULE_ID, snap, {"large_deposit_pct": 50})
    assert result is not None and result.verdict is Verdict.FINDING


def test_fix2_real_payroll_keyword_is_excluded() -> None:
    result = _evaluate(transactions=[_txn("3000", desc="ACME PAYROLL")])
    assert result.verdict is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# FIX 4 — sourcing needs present AND fields (verified doc)
# --------------------------------------------------------------------------- #


def test_fix4_unextracted_sourcing_doc_does_not_count() -> None:
    # A gift letter present but with NO extracted fields is not verified sourcing → the deposit is a FINDING.
    result = _evaluate(
        transactions=[_txn("3000")],
        documents=[_doc("bank_statement"), _doc("gift_letter", fields={})],
    )
    assert result.verdict is Verdict.FINDING


# --------------------------------------------------------------------------- #
# FIX 3+7 — no over-gating: a missing fee-line amount still RUNS the rule
# --------------------------------------------------------------------------- #


def test_fix37_missing_fee_amount_does_not_suppress_the_rule() -> None:
    txns = [_txn(None, ttype="fee", desc="Monthly fee"), _txn("3000", ttype="deposit")]
    snap = _snapshot(transactions=txns)
    # Applicability no longer gates on transactions[].amount → still READY_TO_RUN.
    assert classify_from_json(_APPLICABILITY, snap).state is ApplicabilityState.READY_TO_RUN
    # And the real large deposit is still flagged (not suppressed to couldn't-check).
    assert _evaluate(transactions=txns).verdict is Verdict.FINDING


# --------------------------------------------------------------------------- #
# FIX 5 — sourcing matched PER ACCOUNT (one account's doc can't source another's deposit)
# --------------------------------------------------------------------------- #


def test_fix5_sourcing_is_per_account() -> None:
    acct1 = _bank_stmt("bs1", masked="****1")  # has a sourcing doc
    acct2 = _bank_stmt("bs2", masked="****2")  # the unsourced deposit lands here
    vod_for_acct1 = _doc(
        "verification_of_deposit",
        fields={"bank_name": "Chase", "account_number_masked": "****1", "account_type": "checking"},
    )
    result = _evaluate(
        transactions=[_txn("60000", doc_id="bs2", desc="Incoming funds")],
        bank_statements=[acct1, acct2],
        documents=[_doc("bank_statement"), vod_for_acct1],
    )
    # The VOD sources account 1; account 2's large deposit has no applicable sourcing → FINDING.
    assert result.verdict is Verdict.FINDING


# --------------------------------------------------------------------------- #
# FIX 8 / FIX 10 — dedup-set membership + defensive param parse
# --------------------------------------------------------------------------- #


def test_fix8_as1_in_live_path_owned_set() -> None:
    from app.verification.runner import LIVE_PATH_OWNED_RULE_IDS

    assert RULE_ID in LIVE_PATH_OWNED_RULE_IDS


@pytest.mark.parametrize("bad", ["50%", "", "abc", None])
def test_fix10_bad_threshold_param_does_not_crash(bad) -> None:
    # A mis-entered param falls back to the documented default (50%) — never an uncaught raise.
    result = evaluate_rule(
        RULE_ID, _snapshot(transactions=[_txn("3000")]), {"large_deposit_pct": bad}
    )
    assert result is not None and result.verdict is Verdict.FINDING  # 3000 > 50% of 5000


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
