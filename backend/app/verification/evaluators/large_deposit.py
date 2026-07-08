"""AS-1 large-deposit sourcing evaluator (LP-125R) — build-to-spec (AS-1 is dormant, no live anchor).

A single large deposit into a bank account that isn't sourced (documented/explained) may be undisclosed
borrowed funds or an undocumented gift. AS-1 (``xsrc.asset.large_deposit_unsourced``) is wired +
validated but DORMANT on the live path (its fact is never populated) — so this is a build-to-spec, not a
reproduction (STEP 0a).

STEP 0 spec (verified against the code + the recorded Priya decision):

* **Threshold (Priya-confirmed, decisions.md:7697 + seed ``large_deposit_pct=50``):** a single deposit
  exceeding **50%** of monthly QUALIFYING income. Read from ``params["large_deposit_pct"]`` (tunable),
  parsed DEFENSIVELY — a non-numeric/blank param falls back to the documented default, never crashes the
  run (FIX 10). → validated=true.
* **Income basis (FIX 6):** summed STATED **employment** ``monthly_amount`` only (via
  ``employment_income``), so non-qualifying income (rental/pension/dividend) doesn't inflate the threshold
  and hide deposits. Absent/zero → COULDN'T-CHECK (can't compute "large") — never a silent pass.
  PRIYA-FLAG: (a) which income types count as "qualifying" (employment only vs. + self-employment / fixed),
  and (b) whether a point-in-time deposit vs 50% of *monthly* income is the intended basis.
* **Deposit (FIX 1):** a transaction whose DETERMINISTIC ``transaction_kind`` is ``DEPOSIT`` — the shared
  builder-materialized kind, so a deposit typed "credit"/"ACH credit"/"mobile deposit"/"DEP" (or an
  unrecognized credit) is NOT silently skipped. Sub-threshold → fine.
* **Payroll exclusion (FIX 2):** a DEPOSIT-kind txn whose description matches a payroll signal
  (word-boundary keyword or a word-boundary employer-name match, min length) is already income → EXCLUDED
  (kind==PAYROLL is already excluded upstream by the kind classifier — this is the secondary guard for a
  deposit mislabeled in ``transaction_type``). A large deposit with NO description → can't tell payroll →
  COULDN'T-CHECK for that deposit (P2, never flag a possible paycheck / never silently pass).
* **Sourced (FIX 4 + FIX 5):** a sourcing signal is a VERIFIED (present AND extracted-fields) file
  document (gift letter / donor statement / sale-of-asset / VOD / EMD receipt) — the same present-AND-fields
  semantics as the AS-5 gift-letter evaluator. Sourcing is matched PER ACCOUNT: a doc that carries account
  fields sources only THAT account; a doc with no account identity is "unattributable" and conservatively
  covers any account. A large non-payroll deposit with **no sourcing that could apply to its account** →
  FINDING (determinately unsourced); with a sourcing doc that could apply → COULDN'T-CHECK (indeterminate —
  can't confirm THIS deposit is the sourced one; verify). *File-level presence is not per-deposit proof —
  flagged for Priya (see LP-125R.md).*
* **Per account (P6):** deposits are grouped by account via the SHARED grouping token (FIX 9) — a deposit's
  account is its statement's account. Indeterminate account → COULDN'T-CHECK for that deposit; never
  sourced/compared across accounts.

Deterministic classification → full confidence. Reuses the shared grouping, ``normalize_text``, the typed
``transaction_kind``, and typed transactions/bank-statement facts. Amounts + ordinal account labels only in
the outcome — no masked account / holder / raw description (ADR-150).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.verification.evaluators.contract import (
    ConfidenceMode,
    EvaluationResult,
    Provenance,
    deterministic_couldnt_check,
    deterministic_finding,
    deterministic_satisfied,
)
from app.verification.evaluators.grouping import (
    account_grouping_token,
    account_token_from_fields,
    label_accounts,
)
from app.verification.fact_namespace.canonicalize import normalize_text
from app.verification.fact_namespace.projection import GIFT_LETTER_DOCUMENT_TYPES
from app.verification.fact_namespace.snapshot import FactNamespace, TransactionKind

RULE_ID = "xsrc.asset.large_deposit_unsourced"
_DEFAULT_LARGE_DEPOSIT_PCT = Decimal("50")

# A deposit already accounted for as income (excluded — not something to "source").
_PAYROLL_KEYWORDS = ("payroll", "direct deposit", "dir dep", "salary", "wages")

# File documents that could source a deposit (per-deposit matching is not in the data).
_SOURCING_DOC_TYPES = frozenset(GIFT_LETTER_DOCUMENT_TYPES) | {
    "gift_donor_bank_statement",
    "sale_of_asset_proof",
    "verification_of_deposit",
    "earnest_money_receipt",
}


def _threshold_pct(params: dict[str, Any]) -> Decimal:
    """The large-deposit percentage — parsed DEFENSIVELY (FIX 10). A non-numeric/blank/non-positive param
    falls back to the documented default so a mis-entered param (e.g. ``"50%"`` from the admin UI) never
    raises out of ``evaluate`` and crashes the run."""
    raw = params.get("large_deposit_pct", _DEFAULT_LARGE_DEPOSIT_PCT)
    try:
        pct = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return _DEFAULT_LARGE_DEPOSIT_PCT
    return pct if pct > 0 else _DEFAULT_LARGE_DEPOSIT_PCT


def _is_payroll(description: str | None) -> bool | None:
    """True = payroll (exclude), False = not payroll, None = indeterminate (no description → couldn't-check).

    FIX 2 — the PRIMARY payroll anchor is the deterministic ``transaction_kind == PAYROLL`` (excluded
    upstream at the candidate stage). This is the SECONDARY guard for a deposit whose ``transaction_type``
    didn't say payroll but whose description does. It matches only explicit payroll KEYWORDS
    (word-boundary); it deliberately does NOT match against employer NAMES — an employer name like "Ally"
    or "Amazon" collides with ordinary descriptions ("transfer to ally savings", "amazon refund") and
    would falsely exclude a genuinely unsourced deposit (a false-green). Employer-payroll is handled by the
    ``transaction_kind`` anchor, not by name-substring guessing.
    """
    text = normalize_text(description)
    if not text:
        return None
    return any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in _PAYROLL_KEYWORDS)


class LargeDepositEvaluator:
    """AS-1 — a large deposit (>50% of monthly income) must be sourced (LP-125R, build-to-spec)."""

    rule_id = RULE_ID
    confidence_mode = (
        ConfidenceMode.DETERMINISTIC
    )  # threshold arithmetic — the seed's source of truth

    def evaluate(self, snapshot: FactNamespace, params: dict[str, Any]) -> EvaluationResult:
        # Income basis (FIX 6): summed STATED EMPLOYMENT monthly income only — non-qualifying income
        # (rental/pension/dividend) must not inflate the threshold and hide deposits. Absent → couldn't-check.
        amounts = [
            item.monthly_amount.value
            for borrower in snapshot.borrowers
            for item in borrower.income_items
            if item.employment_income and item.monthly_amount.value is not None
        ]
        monthly_income = sum(amounts, Decimal(0))
        if not amounts or monthly_income <= 0:
            return deterministic_couldnt_check(
                self.rule_id,
                "No stated employment income — cannot compute the large-deposit threshold.",
                provenance=[
                    Provenance(
                        path="borrowers[].income_items[].monthly_amount",
                        observed="no qualifying (employment) income",
                    )
                ],
            )
        pct = _threshold_pct(params)
        threshold = monthly_income * pct / Decimal(100)

        # Per-account identity (shared grouping, FIX 9) + PII-free ordinal labels (ADR-150).
        token_by_doc = {
            bs.source_document_id: account_grouping_token(bs) for bs in snapshot.bank_statements
        }
        labels = label_accounts(snapshot.bank_statements)

        # Sourcing evidence matched PER ACCOUNT (FIX 5), using VERIFIED docs only (present AND fields, FIX 4
        # — same semantics as the AS-5 gift-letter evaluator). A doc that carries account fields sources
        # only that account; a doc with no account identity is "unattributable" (conservatively covers any).
        sourced_tokens: set[str] = set()
        unattributable_sourcing = False
        for doc in snapshot.documents:
            if doc.document_type in _SOURCING_DOC_TYPES and doc.present and doc.fields:
                doc_token = account_token_from_fields(doc.fields)
                if doc_token is not None:
                    sourced_tokens.add(doc_token)
                else:
                    unattributable_sourcing = True

        findings: list[Provenance] = []
        couldnt: list[Provenance] = []
        large_seen = False

        for txn in snapshot.transactions:
            if txn.transaction_kind is not TransactionKind.DEPOSIT:
                continue  # only money-in deposits are candidates (payroll/interest/transfer/debit excluded)
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
            payroll = _is_payroll(txn.description)
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
            # FIX 5 — sourcing must apply to THIS account: an account-specific sourcing doc, or an
            # unattributable one (no account identity → can't rule it out). Otherwise → determinately unsourced.
            if token in sourced_tokens or unattributable_sourcing:
                couldnt.append(
                    Provenance(
                        path=account,
                        observed=f"a large deposit ({amount}) — a sourcing document could apply but cannot be matched to it; verify",
                    )
                )
            else:
                findings.append(
                    Provenance(
                        path=account,
                        observed=f"a large deposit ({amount}) with no sourcing documentation for this account",
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
