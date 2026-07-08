"""AS-8 bank-statement continuity evaluator (LP-123R) — a NEW rule, self-defined spec.

AS-8 is NOT a live rule (see ``docs/audits/live-rule-inventory-corrected.md``); there is no live verdict
to reproduce. This implements a spec WE define, so the rule seeds ``validated=false`` (provisional) and
the domain choices are flagged for Priya.

THE SPEC (as implemented, with the review fixes):

* **Group by ACCOUNT first (the core constraint).** Continuity is only meaningful WITHIN one account —
  two different accounts must NEVER chain together. The grouping key uniquely identifies an account:
  ``bank + masked#`` (a sufficient identity; so ``****6789`` at Chase ≠ at Wells), else ``bank +
  account_type + holder`` when the masked number is absent. ``account_type`` is a best-effort AI field, so
  it is a FALLBACK DISAMBIGUATOR (splits two statements that share bank+masked# but have different
  populated types), NOT a hard requirement — a blank type never blocks grouping (round-5 FIX 1). Missing
  the bank (or, in the fallback, the holder) → **ungroupable** → couldn't-check (never a blind comparison).
  The grouping key is an OPAQUE, PII-free token (ADR-150); the outcome labels accounts ordinally
  ("account 1"), never leaking the real name / masked number.
* **Dedup by period within an account.** A re-uploaded statement (same account + period + balances) is
  the SAME statement — collapsed, never chained against itself (which would be a false "break"). Two
  statements claiming the same period with DIFFERENT balances are a genuine conflict → couldn't-check.
* **Per account** (distinct statements ordered by period): 2+ whose ending balance chains EXACTLY into
  the next beginning balance AND with no missing-period gap → SATISFIED; a balance break or a period gap
  → FINDING; exactly one statement → COULDN'T-CHECK; period/balances not extracted for 2+ →
  COULDN'T-CHECK. A statement without ``period_end`` can't support the gap check, so it is not usable
  (never silently skipped → never a false SATISFIED across a hole).
* **Roll up honestly:** ANY account with a break/gap → overall FINDING; else ANY account couldn't-check →
  overall COULDN'T-CHECK (never satisfied when something wasn't verified); ALL accounts continuous →
  SATISFIED. Every outcome carries reasons + provenance, surfacing partial results.

Deterministic (exact balance arithmetic) → full confidence. Reads the frozen, TYPED
``snapshot.bank_statements`` (materialized + coerced once by the builder — the document-field pattern);
NO eval-time coercion.

PRIYA-FLAGGED (validated=false until confirmed): (a) exact balance match (no tolerance) in v1;
(b) one-statement-per-account → couldn't-check (not satisfied); (c) the monthly-cadence gap heuristic
(:data:`_MAX_ADJACENCY_GAP_DAYS`).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Any, NamedTuple

from app.verification.evaluators.contract import (
    ConfidenceMode,
    EvaluationResult,
    Provenance,
    Verdict,
    deterministic_couldnt_check,
    deterministic_finding,
    deterministic_satisfied,
)
from app.verification.evaluators.grouping import account_grouping_token, label_accounts
from app.verification.fact_namespace.snapshot import BankStatementFacts, FactNamespace

RULE_ID = "pb.as-8"

# PRIYA-FLAG: with monthly statements the gap between one statement's period end and the next's period
# start is ~a few days; a missing month shows a ~29-day gap. 20 days cleanly separates the two while
# tolerating cadence variance. A quarterly/irregular cadence would need a different value — confirm.
_MAX_ADJACENCY_GAP_DAYS = 20


class _Row(NamedTuple):
    """A fully-extracted statement (all fields present) — the typed, non-optional row the chain uses."""

    period_start: date
    period_end: date
    beginning: Decimal
    ending: Decimal


def _row(statement: BankStatementFacts) -> _Row | None:
    """Narrow a statement to a fully-usable typed row, or ``None`` if any field is missing. period_end
    is REQUIRED (a missing end can't support the gap check → not usable, so a missing-month hole never
    silently passes as satisfied)."""
    period_start = statement.period_start.value
    period_end = statement.period_end.value
    beginning = statement.beginning_balance.value
    ending = statement.ending_balance.value
    if period_start is None or period_end is None or beginning is None or ending is None:
        return None
    return _Row(period_start, period_end, beginning, ending)


def _assess_account(group: list[BankStatementFacts]) -> tuple[Verdict, str]:
    """One account group → (verdict, human-readable detail). Never looks outside the group."""
    if len(group) == 1:
        return (
            Verdict.COULDNT_CHECK,
            "only one statement for this account — need consecutive statements to verify continuity",
        )
    usable = [row for row in (_row(s) for s in group) if row is not None]
    if len(usable) < 2:
        return (
            Verdict.COULDNT_CHECK,
            f"{len(group)} statements but period/balances not extracted for 2+ — cannot verify continuity",
        )

    # Dedup by the FULL period (start, end) — round-5 FIX 3. Two rows are the "same statement" only when
    # BOTH match; a shared start with a different end is a DISTINCT statement (both retained). Same
    # (start,end) with different balances = a genuine conflict.
    balances_by_period: dict[tuple[date, date], set[tuple[Decimal, Decimal]]] = defaultdict(set)
    representative: dict[tuple[date, date], _Row] = {}
    for row in usable:
        key = (row.period_start, row.period_end)
        balances_by_period[key].add((row.beginning, row.ending))
        representative.setdefault(key, row)

    conflicts = sorted(k for k, balances in balances_by_period.items() if len(balances) > 1)
    if conflicts:
        return (
            Verdict.COULDNT_CHECK,
            f"conflicting statements for the same period ({conflicts[0][0]}-{conflicts[0][1]}) with "
            "different balances — cannot verify continuity",
        )

    ordered = [representative[key] for key in sorted(representative)]
    if len(ordered) < 2:
        return (
            Verdict.COULDNT_CHECK,
            "only one distinct statement (the rest are duplicates) — need consecutive statements",
        )

    breaks: list[str] = []
    for prev, nxt in pairwise(ordered):
        # Round-5 FIX 2 — an overlapping/backwards pair (nested quarterly+monthly, or an out-of-order
        # period) is NOT a continuity chain; the balance chain across it is meaningless → never SATISFIED.
        if nxt.period_start < prev.period_end:
            breaks.append(
                f"overlapping/nested statement periods ({prev.period_start}-{prev.period_end} and "
                f"{nxt.period_start}-{nxt.period_end}) — not a continuity chain"
            )
        elif prev.ending != nxt.beginning:
            breaks.append(
                f"ending {prev.ending} (period ending {prev.period_end}) != next "
                f"beginning {nxt.beginning} (period starting {nxt.period_start})"
            )
        elif (nxt.period_start - prev.period_end).days > _MAX_ADJACENCY_GAP_DAYS:
            breaks.append(
                f"gap between {prev.period_end} and {nxt.period_start} — a statement appears missing"
            )

    if breaks:
        return Verdict.FINDING, "; ".join(breaks)
    return (
        Verdict.SATISFIED,
        f"{len(ordered)} statements chain continuously "
        f"({ordered[0].period_start} … {ordered[-1].period_end})",
    )


class BankStatementContinuityEvaluator:
    """AS-8 — bank-statement continuity, grouped by account (LP-123R)."""

    rule_id = RULE_ID
    confidence_mode = (
        ConfidenceMode.DETERMINISTIC
    )  # exact arithmetic — the seed's source of truth (FIX 7)

    def evaluate(self, snapshot: FactNamespace, params: dict[str, Any]) -> EvaluationResult:
        statements = list(snapshot.bank_statements)
        if not statements:
            # Applicability guarantees a present bank statement; defensive if nothing materialized.
            return deterministic_couldnt_check(
                self.rule_id,
                "Bank statements are present but nothing readable was extracted to assess continuity.",
                provenance=[
                    Provenance(path="bank statements", observed="no readable statement fields")
                ],
            )

        grouped: dict[str, list[BankStatementFacts]] = defaultdict(list)
        ungroupable = 0
        for statement in statements:
            token = account_grouping_token(statement)
            if token is None:
                ungroupable += 1
            else:
                grouped[token].append(statement)

        # Ordinal, PII-free labels for the outcome (ADR-150) — the SHARED scheme (FIX 9), so "account N"
        # matches AS-1's labels for the same accounts.
        label_by_token = label_accounts(statements)

        finding_prov: list[Provenance] = []
        couldnt_prov: list[Provenance] = []
        satisfied_prov: list[Provenance] = []

        if ungroupable:
            couldnt_prov.append(
                Provenance(
                    path="bank statements",
                    observed=(
                        f"{ungroupable} statement(s) could not be matched to an account "
                        "(bank + account type required to group) — cannot verify continuity"
                    ),
                )
            )

        for token in sorted(grouped):
            verdict, detail = _assess_account(grouped[token])
            prov = Provenance(path=label_by_token[token], observed=detail)
            if verdict is Verdict.FINDING:
                finding_prov.append(prov)
            elif verdict is Verdict.SATISFIED:
                satisfied_prov.append(prov)
            else:
                couldnt_prov.append(prov)

        # Roll up honestly: any break → finding; else any couldn't-check → couldn't-check; else satisfied.
        # Findings/couldn't-checks carry the other accounts' context too, so a partial result isn't lost.
        if finding_prov:
            return deterministic_finding(
                self.rule_id,
                "Bank-statement continuity is broken for one or more accounts.",
                provenance=finding_prov + couldnt_prov + satisfied_prov,
            )
        if couldnt_prov:
            return deterministic_couldnt_check(
                self.rule_id,
                "Bank-statement continuity could not be fully verified (some accounts need more statements or data).",
                provenance=couldnt_prov + satisfied_prov,
            )
        return deterministic_satisfied(
            self.rule_id,
            "Bank-statement continuity verified: every account's statements chain without a break or gap.",
            provenance=satisfied_prov,
        )
