# LP-323-AS-B — Author the ASSETS family (specs + tag declarations + derived recipes; DATA ONLY)

Wave 3's authoring ticket. LP-323-AS-A planned it; LP-336 landed the `per_account` primitive. Income
(Wave 2) held the zero-engine-Python criterion — **Assets held it too.**

## THE SUCCESS CRITERION — HELD ✅

Git-verified: the evaluators (`deterministic/consistency/judgment`), the gate, and the producer core
(`producer/declarations/subjects`) are **UNTOUCHED**. What changed: 10 rule SPECS, the tag DECLARATIONS
(`tag_production.yaml`), 4 recipe **registry entries** + helpers (`derived.py` — the sanctioned extension
point), 4 vocabulary tags (`vocabulary_extra.yaml`), count-test updates, and the smoke tests. No rule-id/
family branch anywhere.

## Rules authored (10; AS-1 live, AS-8 deferred)

| Rule | Shape | Reads |
|---|---|---|
| **AS-4** reserves adequacy | deterministic, loan | **calc `[reserves, months_available]`** (wired calculator — case 12 REAL) vs derived `reserves.required_months` |
| **AS-3** cash-to-close | deterministic, loan | derived `calc.cash_to_close` (BUCKET C — see D3) |
| **AS-10** statement recency | deterministic, loan | derived `stmt.min_account_months` (groups per account via `resolve_accounts`, fire-if-any) |
| **AS-7** NSF/overdraft | deterministic, loan | derived `stmt.nsf_count` vs tolerance |
| **AS-6** account ownership | deterministic, per_document (bank_statement) | `stmt.owner_matches_borrower` (D2) |
| **AS-9** missing pages | deterministic, per_document (bank_statement) | `stmt.page_count_declared/present` (BUCKET C) |
| **AS-11** liquidation terms | deterministic, per_document (retirement_account) | `asset.liquidation_terms` |
| **AS-5** gift-fund chain | deterministic, per_document (gift_letter) | `txn.apparent_category` (LP-330 scoping) |
| **AS-2** EMD sourcing | deterministic, per_deposit | `txn.*` (an approximation — see below) |
| **AS-12** borrowed funds | judgment, per_deposit | `txn.*` → `as.borrowed_funds`, ratification-pending |

**AS-8 DEFERRED** (LP-323-AS-A: pairwise-sequential chaining is a NEW SHAPE — the IN-6 precedent; LP-336
gave it its enumerator + `resolve_accounts`, not its shape). Asserts `RuleSpecNotFound`, not authored.

## THE DECISIONS

### D1 — the reserve-matrix threshold: a DERIVED TAG (ADR-278)
`reference_values.values` is a flat `dict[str,str]` and an operand reads ONE key — it cannot do a
conditional matrix lookup. So `reserves.required_months` is a **derived tag** whose recipe selects the
cell from `property.occupancy` (which exists in MISMO, along with property.type/units/program). It encodes
the agency-standard occupancy cells (investment 6 / second-home 2 / 1-unit primary 0, Fannie B3-4.1-01)
and **ABSTAINS (→ couldnt_check) for every un-encoded cell** — the full matrix is Priya's; a guessed
reserve requirement is a silent, permanent error. No engine change, no schema addition. **ADR-278.**

### D2 — AS-6: deterministic-over-enum
`stmt.owner_matches_borrower` is an AI enum that already resolves the holder↔borrower match, so a
consistency gather would be redundant (the ID-7 precedent — it read the verdict tag, not a re-gather).
AS-6 fires deterministically when the enum `== "no"`, scoped to bank statements.

### D3 — AS-3: cash-to-close is BUCKET C
There is NO cash-to-close calculator (§3B), and `closing_costs` is not a fact today (no Loan-Estimate /
Closing-Disclosure extraction). The recipe can derive down-payment (`purchase_price − loan_amount`) but
not the need, so it **abstains** → AS-3 couldnt_checks. Authored + reported, not invented — the upstream
ask is a Loan-Estimate/CD extraction producing `closing_costs`.

### D4 — thresholds: NO Assets threshold is Priya-validated
AS-A's correction confirmed: AS-1's 50% is `priya_validated:false` — there is no validated precedent row.
Everything authored `priya_validated:false`. Encoded agency-defaults (cited) where standard; **UNSURE
values left un-encoded or abstaining** (never guessed).

## Tag declarations + recipes (reuse; the income pattern repeated)

**The asset vocabulary EXISTED in `fact_tags.csv` but ZERO were declared** (AS-A's finding). Declared:
parsed `stmt.beginning_balance/ending_balance/period_start/period_end/account_masked/page_count_declared`
(document); AI groups `stmt_facts` (owner_matches_borrower + is_reserve_eligible) and `asset_facts`
(liquidation_terms + usable_value); derived `reserves.required_months`, `stmt.nsf_count`,
`stmt.min_account_months`, `calc.cash_to_close`. `txn.*` reused from AS-1. New vocab tags (4):
`reserves.required_months`, `stmt.nsf_count`, `stmt.min_account_months`, `as.borrowed_funds`. **Keying:**
`stmt.*`/`asset.*` under **document** (a statement IS a document — no `account` SubjectType). **LP-335
FINDING-1 heeded:** the AI prompts report what the document STATES, encoding no downstream-rule caution.

## Which rules ACTIVATED vs INERT — NONE activated (the LP-333 discipline)

- **AS-9 (the hoped-for early activation) is BUCKET C** — the bank-statement extractor has NO page-count
  field (`bank_statement.py`: holder/bank/account/type/period/balances/totals — no pages). So AS-9
  couldnt_checks. AS-3 is bucket C (closing_costs).
- **Every AI-fed rule (AS-2/4/5/6/7/11/12) is bucket D** — reads uncalibrated AI tags
  (`stmt.owner_matches_borrower`, `stmt.is_reserve_eligible`, `asset.*`, `txn.*`) → gated on LP-334
  calibration + Priya's bars.
- **AS-10** reads PARSED period fields + a derived recipe — no AI — so it is the closest to activatable,
  BUT its threshold (2 months) is Priya-pending and the recipe depends on the parsed `stmt.period_*` fields
  materializing (they exist in the extractor). A candidate for the first AS activation once its threshold
  is confirmed. Left inert here (activation is a separate decision with the numbers in hand).

**Nothing added to `ACTIVE_RULE_IDS`.** The correct state (LP-333), not a failure.

## PIN #1's cousin (AS-A) — addressed, not papered over

AS-4 (reserves) and AS-3 (cash-to-close) aggregate. **AS-10's recency recipe takes the per-account
MINIMUM** (via `resolve_accounts`) so a single short account is never masked by a well-documented one
(fire-if-any). AS-4's masking (an ineligible account counted) is gated per-statement by
`stmt.is_reserve_eligible` / `asset.usable_value` feeding the reserves calc — a case for AS-C to pin.

## Was any engine Python needed? — NO

Only recipe *registry entries* in `derived.py` (the LP-326 extension point). The Assets wave held the
criterion, like Income.

## Guideline text drafted needing human verification

Every `guideline_text`/`guideline_reference` (Fannie B3-4.1-01 reserves, B3-4.2-01 statements, B3-4.3-03
retirement, B3-4.3-04 gifts, B3-4.2-02 EMD) is transcribed at authoring — HUMAN-VERIFY, never AI-recalled.

## PRIYA / HUMAN-VERIFY list

| # | Item | Rule | Encoded | Confirm |
|---|---|---|---|---|
| 1 | **Reserve MONTHS matrix** (headline) | AS-4 | investment 6 / second-home 2 / primary 0 (1-unit); rest abstain | the full matrix (units × LTV × program) |
| 2 | **Retirement discount 60 vs 70%** (headline) | AS-11 | UNSURE — not encoded | the factor |
| 3 | Statement months required | AS-10 | 2 (agency-default) | confirm |
| 4 | NSF tolerance | AS-7 | 3 (overlay default) | the lender's threshold |
| 5 | Gift-fund chain | AS-5 | presence (B3-4.3-04) | the required links |
| 6 | EMD sourcing | AS-2 | approximation | the true cross-doc-match rule |

## New gaps (reported, not patched)

1. **AS-9 page-count extraction** — `bank_statement.py` has no page count → AS-9 bucket C (an extraction ask).
2. **AS-3 closing_costs** — no Loan-Estimate/CD extraction → AS-3 bucket C (an extraction ask).
3. **AS-2's true shape** — an EMD cross-document MATCH (contract amount ↔ a debit) isn't cleanly
   expressible; the authored rule approximates it via `txn.*` sourcing — reported for AS-C / a follow-on.

## What AS-C must cover

The full 13-point matrix per rule; **case 12 (AS-4's gated reserves calc → couldnt_check) is REAL** and
asserted here; the derived-tag abstention; the AS-12 armor; AS-4's PIN #1-cousin masking test (a single
ineligible account); the bucket-C rules (AS-3/AS-9) documented-inert; and the D1/D2 domain edges (an
investment property needing 6 months; a restricted 401(k); a short account not masked by a full one).

## ADR

**ADR-278** — the conditional (matrix) threshold as a derived tag (recurs for LTV/MI/DTI matrices). D3
folds into ADR-273 (arithmetic as recipes). D2/D4 are routine / a Priya list. AS-8's deferral is
LP-323-AS-A's decision.

## Cross-refs

LP-323-AS-A (the recon this executes), LP-336 (per_account + resolve_accounts — used in AS-10),
LP-323-IN-B (the authoring precedent + ADR-273), LP-333 (activation buckets + discipline), LP-334/335
(the calibration gate keeping AI-fed rules inert; FINDING-1's prompt-exemplar caution). Evidence:
`rule_kinds.csv`, `fact_tags.csv`, `bank_statement.py`, `mismo_section.py`, `calculations_section.py`,
`classification_prompt.py`.
