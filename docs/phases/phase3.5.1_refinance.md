LP-99 — Parse refinance_type from MISMO
Small-medium · backend · correctness-critical · do first

refinance_type (cash-out vs. rate/term) exists on the model but is NOT parsed from MISMO — only settable manually
A cash-out refi imported via MISMO lands refinance_type=NULL → LTV silently defaults to rate/term → the looser limit
Same dangerous class as the appraised-value + MI binding gaps: a field the calculator needs that the import doesn't populate, defaulting in the permissive direction (a cash-out that should fail could pass)
Find the MISMO element for refinance purpose / cash-out (LoanPurposeType / cash-out indicator) → parse it → populate refinance_type
So a cash-out refi imported via MISMO gets the correct stricter cash-out LTV limit automatically
Grounded-starter where the MISMO field mapping is uncertain (flag validate-with-Priya)
Tests: a cash-out refi MISMO import → refinance_type=CASH_OUT → the stricter cash-out LTV limit applies (not the looser default)
Doc: docs/tickets/LP-99.md + ADR


LP-100 — Purpose-gating in the rules framework
Medium · backend · the framework gap

The rules framework has no PURPOSE gate — ApplicabilityScope is ALL_LOANS / PROGRAM / LENDER only; RuleGate keys typed facts, not loan_purpose
Consequence: the purchase-agreement doc rule (conv.docs.purchase_agreement_present) fires on refinances → spurious YELLOW finding (a refi legitimately has no purchase agreement)
Add a PURPOSE dimension to the applicability framework (scope rules purchase-only / refi-only / cash-out-only)
Gate the purchase-agreement rule (+ any other purchase-specific rules) to purchases → no spurious refi findings
Confirm/add refi-specific needs (existing mortgage statement, payoff statement) — or flag for Priya
DTI stays correctly not purpose-gated (refinance doesn't change DTI limits — those are program-based)
Tests: a refi does NOT get the purchase-agreement finding; purchase-specific rules gated by purpose; refi-specific needs present
Doc: docs/tickets/LP-100.md + ADR


LP-101 — Refi MISMO fixture + end-to-end refinance test — DONE
Medium · testing · depends on LP-99 + LP-100

No refi MISMO fixture exists (only Mahesh — a Conventional purchase); refi is only unit-tested, never through an actual import
The whole refi path (import → LTV → rules → findings) is unverified as a flow
Create a refi MISMO fixture — both rate/term and cash-out (synthetic or de-identified)
End-to-end test: import → LTV (appraised-only basis, correct limit) → rules (no spurious purchase findings; refi rules fire) → findings
Asserts the LP-99 fix (cash-out → stricter limit) and the LP-100 fix (no purchase-agreement finding on refi)
Surfaces whatever else the refi path breaks that LP-99/100 didn't cover
Doc: docs/tickets/LP-101.md + ADR

OUTCOME (2026-07-01): two synthetic/de-identified fixtures (rate_term 80% LTV, cash_out 85% LTV) + a
correctness sweep (tests/integration/test_refinance_e2e.py). Asserted LP-99 (cash-out → stricter 80%
cash-out limit binds; appraised-only basis) + LP-100 (purchase-agreement skipped on refi; refi
need-set). Probed all calculators. TWO seams surfaced, both CONSERVATIVE direction:
  - GAP-2 (reserves) FIXED inline: a refi has no down payment (was value − loan / home equity).
  - GAP-1 (DTI) documented + xfail(strict), follow-up LP-102: the existing mortgage being paid off
    is double-counted in the back-end DTI (no MISMO payoff-indicator parsing). Not baked in as correct.
The refinance epic (LP-99/100/101) is COMPLETE — refi proven e2e for what the fixtures exercise; the
one remaining gap is tracked, not hidden. See docs/tickets/LP-101.md + ADR-227.

PROPOSED FOLLOW-UP — LP-102: parse the MISMO payoff indicator + exclude the paid-off subject mortgage
from the refi back-end DTI (fixes GAP-1; the xfail flips to a hard pass).
