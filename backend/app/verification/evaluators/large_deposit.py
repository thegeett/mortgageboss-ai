"""AS-1 large-deposit sourcing evaluator (LP-125R) — build-to-spec (AS-1 is dormant, no live anchor).

A single large deposit into a bank account that isn't sourced (documented/explained) may be undisclosed
borrowed funds or an undocumented gift. AS-1 (``xsrc.asset.large_deposit_unsourced``) is wired +
validated but DORMANT on the live path (its fact is never populated) — so this is a build-to-spec, not a
reproduction (STEP 0a).

STEP 0 spec (verified against the code + the recorded Priya decision):

* **Threshold (Priya-confirmed, decisions.md:7697 + seed ``large_deposit_pct=50``):** a single deposit
  exceeding **50%** of monthly income. Read from ``params["large_deposit_pct"]`` (tunable). → validated=true.
* **Income basis:** summed STATED ``borrowers[].income_items[].monthly_amount`` (there is no computed
  qualifying-income fact yet). Absent/zero → COULDN'T-CHECK (can't compute "large") — never a silent pass.
* **Deposit:** a transaction whose ``transaction_type`` normalizes to ``"deposit"``. Sub-threshold → fine.
* **Payroll exclusion:** a large deposit whose description matches a payroll signal (keyword or a
  documented employer name) is already income → EXCLUDED. A large deposit with NO description → can't tell
  payroll → COULDN'T-CHECK for that deposit (P2, never flag a possible paycheck / never silently pass).
* **Sourced:** the only sourcing signal in the data is FILE-LEVEL documents (gift letter / donor
  statement / sale-of-asset / VOD / EMD receipt) — a specific deposit CANNOT be matched to a specific doc.
  So (P1/P2, no false-green): a large non-payroll deposit with **no sourcing doc anywhere on the file** →
  FINDING (determinately unsourced); with **sourcing docs present** → COULDN'T-CHECK (indeterminate — can't
  confirm THIS deposit is the sourced one; verify). *This departs from a literal "sourced→satisfied": file-
  level presence is not per-deposit proof — flagged for Priya (see LP-125R.md).*
* **Per account (P6):** deposits are grouped by account via the SHARED AS-8 grouping token (bank + masked#,
  account_type fallback) — a deposit's account is its statement's account. Indeterminate account →
  COULDN'T-CHECK for that deposit; never sourced/compared across accounts.

Deterministic classification → full confidence. Reuses the AS-8 grouping token, the shared
``normalize_text``, the Verdict enum, and typed transactions/bank-statement facts (P4). Amounts + ordinal
account labels only in the outcome — no masked account / holder / raw description (ADR-150).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.verification.evaluators.bank_statement_continuity import _grouping_token
from app.verification.evaluators.contract import (
    ConfidenceMode,
    EvaluationResult,
    Provenance,
    deterministic_couldnt_check,
    deterministic_finding,
    deterministic_satisfied,
)
from app.verification.fact_namespace.canonicalize import normalize_text
from app.verification.fact_namespace.projection import GIFT_LETTER_DOCUMENT_TYPES
from app.verification.fact_namespace.snapshot import FactNamespace

RULE_ID = "xsrc.asset.large_deposit_unsourced"
_DEFAULT_LARGE_DEPOSIT_PCT = Decimal("50")

# A deposit already accounted for as income (excluded — not something to "source").
_PAYROLL_KEYWORDS = ("payroll", "direct deposit", "dir dep", "salary", "wages")

# File-level documents that could source a deposit (per-deposit matching is not in the data).
_SOURCING_DOC_TYPES = frozenset(GIFT_LETTER_DOCUMENT_TYPES) | {
    "gift_donor_bank_statement",
    "sale_of_asset_proof",
    "verification_of_deposit",
    "earnest_money_receipt",
}


def _is_payroll(description: str | None, employer_tokens: set[str]) -> bool | None:
    """True = payroll (exclude), False = not payroll, None = indeterminate (no description → couldn't-check)."""
    text = normalize_text(description)
    if not text:
        return None
    if any(keyword in text for keyword in _PAYROLL_KEYWORDS):
        return True
    return any(employer and employer in text for employer in employer_tokens)


class LargeDepositEvaluator:
    """AS-1 — a large deposit (>50% of monthly income) must be sourced (LP-125R, build-to-spec)."""

    rule_id = RULE_ID
    confidence_mode = (
        ConfidenceMode.DETERMINISTIC
    )  # threshold arithmetic — the seed's source of truth

    def evaluate(self, snapshot: FactNamespace, params: dict[str, Any]) -> EvaluationResult:
        # Income basis: summed STATED monthly income (no qualifying-income fact yet). Absent → couldn't-check.
        amounts = [
            item.monthly_amount.value
            for borrower in snapshot.borrowers
            for item in borrower.income_items
            if item.monthly_amount.value is not None
        ]
        monthly_income = sum(amounts, Decimal(0))
        if not amounts or monthly_income <= 0:
            return deterministic_couldnt_check(
                self.rule_id,
                "No stated monthly income — cannot compute the large-deposit threshold.",
                provenance=[
                    Provenance(path="borrowers[].income_items[].monthly_amount", observed="absent")
                ],
            )
        pct = Decimal(str(params.get("large_deposit_pct", _DEFAULT_LARGE_DEPOSIT_PCT)))
        threshold = monthly_income * pct / Decimal(100)

        # Per-account identity (reuse the AS-8 grouping token) + PII-free ordinal labels (ADR-150).
        token_by_doc = {
            bs.source_document_id: _grouping_token(bs) for bs in snapshot.bank_statements
        }
        labels = {
            token: f"account {i + 1}"
            for i, token in enumerate(sorted({t for t in token_by_doc.values() if t}))
        }
        employer_tokens = {
            normalize_text(employer.name)
            for borrower in snapshot.borrowers
            for employer in borrower.employers
            if employer.name
        } | {
            normalize_text(name) for name in (snapshot.documented.documented_employers.value or [])
        }
        employer_tokens.discard("")
        sourcing_present = any(
            doc.document_type in _SOURCING_DOC_TYPES and doc.present for doc in snapshot.documents
        )

        findings: list[Provenance] = []
        couldnt: list[Provenance] = []
        large_seen = False

        for txn in snapshot.transactions:
            if normalize_text(txn.transaction_type) != "deposit":
                continue
            amount = txn.amount.value
            if amount is None:
                couldnt.append(
                    Provenance(
                        path="transactions[].amount",
                        observed="a deposit with no amount — cannot assess",
                    )
                )
                continue
            if amount <= threshold:
                continue  # sub-threshold — not a large deposit
            large_seen = True
            token = token_by_doc.get(txn.source_document_id)
            if token is None:  # P6 — can't tie the deposit to an account
                couldnt.append(
                    Provenance(
                        path="transactions[]",
                        observed=f"a large deposit ({amount}) whose account can't be determined",
                    )
                )
                continue
            account = labels[token]
            payroll = _is_payroll(txn.description, employer_tokens)
            if payroll is True:
                continue  # already income — excluded, not a deposit to source
            if payroll is None:  # P2 — no description, can't tell payroll-vs-not
                couldnt.append(
                    Provenance(
                        path=account,
                        observed=f"a large deposit ({amount}) with no description — cannot tell if it is payroll",
                    )
                )
                continue
            if (
                sourcing_present
            ):  # P2 — indeterminate: docs exist but can't be matched to this deposit
                couldnt.append(
                    Provenance(
                        path=account,
                        observed=f"a large deposit ({amount}) — sourcing documents exist but cannot be matched to it; verify",
                    )
                )
            else:
                findings.append(
                    Provenance(
                        path=account,
                        observed=f"a large deposit ({amount}) with no sourcing documentation on file",
                    )
                )

        # Roll up honestly: any unsourced → finding; else any indeterminate → couldn't-check; else satisfied.
        if findings:
            return deterministic_finding(
                self.rule_id,
                "A large deposit is not sourced (no gift letter / transfer / explanation on file).",
                provenance=findings + couldnt,
            )
        if couldnt:
            return deterministic_couldnt_check(
                self.rule_id,
                "A large deposit could not be sourced from the available data — needs review.",
                provenance=couldnt,
            )
        return deterministic_satisfied(
            self.rule_id,
            "No unsourced large deposits — every large deposit is payroll/income or there are none.",
            provenance=[
                Provenance(
                    path="transactions[]",
                    observed=f"threshold {threshold} (>{pct}% of {monthly_income}); {'large deposits all accounted for' if large_seen else 'no large deposits'}",
                )
            ],
        )
