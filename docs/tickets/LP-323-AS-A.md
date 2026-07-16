# LP-323-AS-A — Assets wave (Wave 3) recon + plan (READ-ONLY)

Wave 1 (Identity) cost 7 tickets; Wave 2 (Income) cost 3 — the first wave the zero-engine-Python criterion
held. This ticket plans the Assets family (AS-2..AS-12; AS-1 is already LIVE) against the now-complete
primitive set and tests whether ~3/wave is a trend. No code written — the only deliverable is this file.
All findings are file:line-grounded; **rule_kinds.csv / the code is the gate of record** (it already caught
one ticket-text error — see below).

---

## PHASE 0 — THE GATE VERDICT + THE ACCOUNT-GRANULARITY VERDICT (blocking, reported first)

### (a) The generalization gate: MOSTLY YES, with ONE new enumerator + ONE new shape

Most AS rules run from a spec through the existing generic evaluators:
- **deterministic** (LP-324): AS-3, AS-4, AS-7, AS-9, AS-11 — read tags / a calc / a derived tag, compare.
- **consistency** (LP-325 fuzzy): AS-6 (holder-vs-borrower) — though it may be deterministic-over-an-enum
  (see Phase 1). AS-2/AS-5 are cross-document sourcing (fuzzy/judgment).
- **judgment** (LP-327): AS-12 (borrowed-funds pattern).

**Two things do NOT fit the existing shapes** (name them; do not plan around with per-rule Python):
1. **`per_account` enumeration is MISSING.** `enumerators.py` has `per_deposit / loan / per_borrower /
   per_document` (verified) — no `per_account`. AS-6/AS-8/AS-10 operate per ACCOUNT (grouping the
   bank-statement documents of one account). This is a **registry entry, like `per_borrower` was** — the
   LP-332 pattern (option (i) below), NOT a per-rule branch.
2. **AS-8 (statement chaining) is a NEW SHAPE.** `rule_kinds.csv`: *"ending == next beginning — equality
   check per PAIR (not a ratio)."* This is a PAIRWISE SEQUENTIAL comparison across a sorted sequence of
   statements — it fits neither the single-subject deterministic compare, nor all-agree consistency
   (LP-325), nor judgment. This is **income's IN-6 case again** (set-coverage fit nothing → correctly
   DEFERRED). **Recommendation: DEFER AS-8** to its own ticket (a `sequential_pairwise` evaluator or a
   derived per-account "chain-breaks" tag), exactly as IN-6 was deferred rather than forced.

### (b) THE ACCOUNT-GRANULARITY PREDICTION — CONFIRMED for enumeration, REFUTED for materialization

LP-323-IN-C forecast *"the same per-borrower/per-account aggregation granularity if any asset rule is
per-account."* The evidence splits the prediction cleanly:

- **Materialization: REFUTED (no new subject type).** The asset tags carry logical entity `statement` /
  `asset`, but a bank statement IS a `document` and a retirement/brokerage statement IS a `document`. So
  `stmt.*` / `asset.*` tags key under the existing **document** subject (each statement/asset doc) — the
  materialization registry needs **no `account`/`statement` SubjectType**. (This differs from LP-332's
  borrower case, where MISMO facts had no document to key under.)
- **Rule enumeration: CONFIRMED (a `per_account` enumerator is needed).** AS-6/AS-8/AS-10 group a
  borrower's bank-statement DOCUMENTS by account. There is no `per_account` enumerator. The account
  identity is `stmt.account_masked` (`fact_tags.csv`: *"Masked account number (display only,
  **non-matchable**)"*). **THE RESOLUTION HAS A FAIL-CLOSED PROBLEM (flag it loudly, echoing LP-332's
  borrower_id resolution):** the masked number alone is unsafe — `****1234` at Bank A vs Bank B collides,
  and there is no `stmt.institution` tag today. So `per_account` needs an account-identity resolution
  (masked-number + institution), and an ambiguous/absent identity must fail-closed → couldnt_check, **never
  a mis-grouped account** (mis-grouping would fabricate or hide a chaining/reserve error — PIN #1's cousin).

**The options weighed:** (i) a `per_account` enumerator (+ the identity resolution) — a registry entry,
the LP-332 pattern, REUSABLE. **RECOMMENDED.** (ii) key account facts under document + aggregate via a
derived recipe — works for loan-level aggregates (AS-4) but NOT for AS-8/AS-10 which need per-account
grouping to enumerate. (iii) refuted — `per_deposit`/`per_document` do not express per-account grouping.
**No fact needs to key under BOTH document and account** (the divergence risk LP-331/332 rejected): the
raw `stmt.*` facts key under document; per-account grouping is an ENUMERATION concern, not a second keying.

### PIN #1's COUSIN — the masking false-green to hunt

**AS-4 (reserves adequacy)** is the candidate: it aggregates reserve-eligible funds across all accounts vs
required months. The mitigation already exists per-account: `stmt.is_reserve_eligible` (per statement) +
`asset.usable_value` (per asset, after haircut) gate eligibility BEFORE the reserves calc sums them — so a
restricted/retirement account is discounted per-account, not masked. **The residual risk:** an UNSOURCED
large deposit inflates an account's balance → counted in `asset.usable_value` → the reserves total passes
on funds that AS-1 flags as unsourced. This is **cross-rule** (AS-1 fires on the deposit; AS-4 counts the
balance) — the processor sees both, so it is not a silent mask AS LONG AS AS-1 is trusted (and AS-1's AI
feed is itself uncalibrated — LP-334). **Name AS-4 as the rule to watch** and require -C to test a
single-account-ineligible-but-aggregate-passes case. **AS-3 (cash-to-close)** has the same aggregate shape
(available funds vs need) — same watch.

---

## PHASE 1 — AS-2..AS-12 by kind / shape / evaluator

From `rule_kinds.csv` (the gate of record) + the tag vocabulary. **Only AS-1.yaml exists** — AS-2..12 need
authoring (-B).

| Rule | Name | kind | Evaluator | Enumerator | Reads |
|---|---|---|---|---|---|
| **AS-2** | Earnest-money deposit sourcing | structural (fuzzy) | consistency / judgment | per_deposit | `txn.apparent_category`, `txn.has_identified_source`, `txn.counterparty` vs the contract EMD |
| **AS-3** | Cash-to-close sufficiency | calculative | deterministic | loan | derived `calc.cash_to_close` (down + costs − credits + reserves vs available) |
| **AS-4** | Reserves adequacy | calculative | deterministic | loan | **calc `[reserves, months]`** (a wired calculator — case 12 REAL) vs required-months (matrix) |
| **AS-5** | Gift-fund documentation chain | structural (fuzzy) | judgment / presence | per_deposit / per_document | `txn.apparent_category==gift`, `txn.source_reference`; gift_letter present |
| **AS-6** | Account ownership | structural (fuzzy) | deterministic-over-enum OR consistency | per_document (per statement) | `stmt.owner_matches_borrower` (AI already resolves the match) |
| **AS-7** | NSF / overdraft flag | structural (fuzzy) | deterministic | per_account (or loan) | `txn.is_nsf_or_overdraft` count vs tolerance |
| **AS-8** | Statement chaining (continuity) | structural (exact) | **⚠ NEW SHAPE — pairwise sequential** | per_account | `stmt.ending_balance[n] == stmt.beginning_balance[n+1]` |
| **AS-9** | Missing pages | structural (exact) | deterministic | per_document | `stmt.page_count_declared` vs `stmt.page_count_present` (derived) |
| **AS-10** | Statement recency completeness | structural (exact) | deterministic + per-account count | per_account | `stmt.period_start/end` — N consecutive months vs required |
| **AS-11** | Retirement/stock liquidation terms | calculative | deterministic + judgment | per_document (per asset) | `asset.liquidation_terms`, `asset.usable_value` (discount) |
| **AS-12** | Borrowed-funds detection | judgmental | judgment | per_deposit | `txn.apparent_category`, `txn.counterparty`, `txn.is_recurring` |

**What AS-1 proves (the exemplar):** `per_deposit` enumeration with `subject_key_fields: [account, date,
amount]` (`AS-1.yaml:95`), a `calc` operand `[dti, gross_monthly_income]` (proven generic), the LP-314a
source-strength ladder as ordered OutcomeRules, and a threshold in `reference_values`. **AS-2/AS-5/AS-12
share AS-1's per-deposit + `txn.*` shape** (reuse). AS-3/AS-4 are loan-level calc/derived. AS-6/8/9/10/11
are per-statement/per-account. **Rules fitting NO shape: AS-8 (deferred).**

---

## PHASE 2 — Tags: exist vs new + declarations + activation buckets

**BIG FINDING (the income pattern repeats): the asset vocabulary ALREADY EXISTS** in `fact_tags.csv` — a
full `stmt.*` + `asset.*` set + reused `txn.*` — but **ZERO are declared in `tag_production.yaml`** (grep
count = 0). -B authors DECLARATIONS + producers, not new vocabulary.

**EXISTS (reuse):** `txn.is_money_in / amount / date / apparent_category / has_identified_source /
source_reference / counterparty / is_recurring / is_nsf_or_overdraft` (transaction); `stmt.account_masked /
beginning_balance / ending_balance / period_start / period_end / page_count_declared / page_count_present
(derived) / owner_matches_borrower / is_reserve_eligible` (statement→document); `asset.liquidation_terms /
usable_value` (asset→document); `calc.reserves / calc.cash_to_close` (loan, derived).

**Declarations to AUTHOR (per rule):** parsed (`stmt.beginning_balance`, `ending_balance`, `period_start/
end`, `page_count_declared`, `account_masked`) keyed under **document**; AI (`stmt.owner_matches_borrower`,
`stmt.is_reserve_eligible`, `asset.liquidation_terms`, `asset.usable_value`) — grouped AI passes on the
bank_statement / asset document; derived (`stmt.page_count_present`, `calc.reserves` [already a
calculator], `calc.cash_to_close` — a recipe over down/costs/credits). **No re-mint** — every tag above is
in the vocabulary.

**THE LP-325 GATHER CONTRACT:** AS-6's owner-match and AS-8's balances are per-statement facts keyed under
the statement's document — co-located, contract preserved. No cross-subject gather filter is needed (AS-6
reads a pre-resolved enum).

**ACTIVATION BUCKETS (LP-333 model; document types VERIFIED against `classification_prompt.py`):**

| Rule | Bucket | Reason |
|---|---|---|
| AS-3, AS-4 | **B** (wiring) | loan-level derived/calc; need the `stmt.*`/`asset.*` feeds materialized. AS-4 reads the wired `reserves` calc (already in `snapshot.calculations`). No uncalibrated free-text; but `stmt.is_reserve_eligible`/`asset.usable_value` are **AI + UNCALIBRATED** → activation gated on LP-334 calibration. |
| AS-9 | **B** (wiring, parsed/derived only) | `stmt.page_count_declared` (parsed) + `page_count_present` (derived) — **no AI**, the safest activation candidate (IN-2's analogue) IF the page-count extraction fields exist (verify → possibly **C**). |
| AS-2, AS-5, AS-6, AS-7, AS-11, AS-12 | **D** (uncalibrated AI feed) | read AI enums (`txn.apparent_category`, `stmt.owner_matches_borrower`, `asset.liquidation_terms`, `stmt.is_nsf_or_overdraft`) — all **uncalibrated** (LP-334); several free-text-adjacent. Gated on calibration + Priya bars. |
| AS-8, AS-10 | **A→D** (need `per_account`) | need the `per_account` enumerator (+ identity resolution); AS-8 also needs its new shape. |
| doc types | — | **all present** — `bank_statement`, `investment_account`, `retirement_account`, `gift_letter`, `earnest_money_receipt`, `purchase_agreement` (`classification_prompt.py`). **No silent-not_applicable** (unlike IN-8/9). |

**Calibration note (LP-334):** the AS AI tags are mostly **enum** (`is_money_in`, `apparent_category`,
`owner_matches_borrower`, `is_reserve_eligible`, `liquidation_terms`, `is_nsf_or_overdraft`) → honestly
scorable (FINDING-2: enums score, free-text doesn't). `txn.source_reference` / `txn.counterparty` are
FREE-TEXT → not string-scorable. **Any AS prompt exemplar is unaudited** (FINDING-1 was a wrong exemplar in
`id_address`) — the `txn_stage_a` prompt already ships live and is uncalibrated.

---

## PHASE 3 — Thresholds (agency-default | overlay-pending | UNSURE)

**⚠ TICKET-TEXT CORRECTION (the code is the gate of record):** the ticket says *"AS-1's 50% is
Priya-VALIDATED."* `rule_kinds.csv` shows **AS-1 `priya_validated=false, threshold_needs_signoff=true`** —
it is NOT validated; it is overlay-pending, same as every other threshold. There is **no Priya-validated
precedent row in Assets** (IN-A's IN-1/IN-3 mislabel and IN-C's IN-12 armor error, again).

| Rule | Threshold | Agency default (confirm) | Status |
|---|---|---|---|
| AS-4 | **reserve MONTHS** | a MATRIX: occupancy × property-type × units × program (e.g. 0 primary SFR / 2 second-home / 6 investment; more for 2-4 units) | **UNSURE + a SHAPE question** (below) |
| AS-2/AS-5 | seasoning / sourcing window | large deposits sourced; gift funds fully documented (B3-4.3-04) | AGENCY-DEFAULT — confirm |
| AS-7 | NSF tolerance | no hard agency count; a lender overlay | **OVERLAY-PENDING / UNSURE** |
| AS-10 | statement months | typically **2 months** most-recent (B3-4.1) | AGENCY-DEFAULT — confirm 2 |
| AS-11 | retirement discount | commonly **60%** of vested (or 70%); varies by liquidity/employment | **UNSURE** — do not guess 60 vs 70 |
| AS-3 | cash-to-close | available ≥ down + costs + reserves − credits (definitional, not a %) | AGENCY-DEFAULT (structure) |
| AS-8/AS-9 | equality / count | exact (no numeric threshold) | N/A |

**THE RESERVE-MONTHS MATRIX SHAPE QUESTION (a real -B decision).** `reference_values.values` is a **flat
`dict[str, str]`** (`specs.py`), and the operand system reads ONE `reference` key — it cannot do a
CONDITIONAL matrix lookup (pick the cell by occupancy/property/LTV). So AS-4's required-months is best a
**derived tag `reserves.required_months`** whose recipe selects the cell from the loan's attributes
(occupancy/property/units/program) — the ADR-273 pattern (derived, no engine change). The matrix VALUES are
**Priya's** (UNSURE — do not guess). Alternatively a structured matrix reference is a schema addition —
report as a -B decision, NOT an engine gap forced here. **If UNSURE of a cell value, leave it un-encoded
(couldnt_check-safe) — a wrong reserve requirement mis-evaluates silently and permanently.**

---

## PHASE 4 — The eval plan (the 13-point matrix per rule)

Cases 3/4 are REAL (reserve months, statement counts, NSF tolerance). **Case 12 is REAL** (AS-4's gated
`reserves` calc → couldnt_check — the family's first genuine calc-gate test, IN could not do it well). Case
8 (label variance) is **AS-1's origin story** (the `direction=="credit"` bug) — real for the `txn.*` tags.
Case 11 (armor) applies to AS-12 (judgment) only. N/As stated explicitly.

**Representative must-fire + domain edge (case 13) per rule:**
- **AS-2:** an EMD with no matching debit → fire · edge: EMD already paid outside the statements (in-file
  vs still-needed) — do not double-count.
- **AS-3:** available < need → fire · 3/4 at the shortfall boundary · edge: an earnest-money already paid
  counted as both an asset and a credit (double-count).
- **AS-4:** months_available < required → fire · **12: gated `reserves` calc → couldnt_check** · **PIN #1
  cousin: one account ineligible but the aggregate passes** (the masking test) · edge: retirement funds
  needing a discount AND distribution eligibility.
- **AS-5:** gift with a missing link (no letter / no donor trace / no transfer) → fire · edge: a documented
  gift that IS the large deposit AS-1 flagged (the gift-letter loop — §7/LP-320's canonical cross-rule).
- **AS-6:** holder ≠ borrower → fire · edge: a joint account with a non-borrower co-owner.
- **AS-7:** NSF count > tolerance → fire · 3/4 boundary · edge: a single returned item vs a pattern.
- **AS-8:** ending ≠ next beginning → fire (**DEFERRED** — assert nothing until the shape lands) · edge: a
  missing middle month breaks the chain.
- **AS-9:** declared pages > present → fire · edge: an account statement missing a page (absent≠empty).
- **AS-10:** < N consecutive months → fire · 3/4 boundary · edge: a gap month (Feb missing between Jan/Mar).
- **AS-11:** restricted funds counted at full value → fire · edge: a 401(k) loan-eligible-only balance; a
  vested-but-not-distributable stock plan.
- **AS-12 (judgment):** a deposit pattern implying a loan → needs_review · 11 armor · edge: a wire from an
  unverified/foreign source; a crypto liquidation.
- **AS-6/AS-8 couldnt_check when `<2` / account-identity ambiguous** (the fail-closed resolution).

**Every rule has a credible must-fire case** — none looks mis-specified. **N/A:** case 11 (armor) for the
deterministic/structural rules; case 3/4 for AS-8/AS-9 (equality/count, no numeric threshold); case 12 for
the non-calc rules.

---

## RISKS / OPEN QUESTIONS / PRIYA

| # | Item | Rule(s) | Status |
|---|---|---|---|
| 1 | **Reserve-months MATRIX** (values + shape) | AS-4 | **Priya (values) + -B shape decision** (derived tag vs structured reference) |
| 2 | Retirement discount factor (60 vs 70%) | AS-11 | **UNSURE — Priya** |
| 3 | Statement months required (2?) | AS-10 | AGENCY-DEFAULT — confirm |
| 4 | NSF tolerance | AS-7 | OVERLAY-PENDING — Priya |
| 5 | Gift-fund documentation rules | AS-5 | AGENCY-DEFAULT (B3-4.3-04) — confirm |
| 6 | `per_account` identity resolution (masked# + institution) | AS-6/8/10 | a fail-closed resolution (LP-332 pattern) — a follow-on |
| 7 | AS-8 pairwise-sequential shape | AS-8 | a new evaluator/shape — DEFER (like IN-6) |
| 8 | Uncalibrated AI feeds | AS-2/4/5/6/7/11/12 | LP-334 calibration gate — none activate until scored |
| 9 | AS page-count extraction fields | AS-9 | verify they exist (else bucket C) |

---

## RECOMMENDATION

**PROCEED to LP-323-AS-B** — the family is authorable as DATA + declarations + recipes, reusing the
existing vocabulary and the AS-1 exemplar, with two carve-outs handled the way the wave-1/2 discipline
prescribes:
- **The `per_account` enumerator** (+ its fail-closed account-identity resolution) is a small reusable
  primitive — a registry entry like `per_borrower` (LP-332). It can land in -B or a tiny pre-ticket; it is
  NOT a blocker for authoring the non-account rules.
- **DEFER AS-8** (the pairwise-sequential chaining shape) to its own ticket — do NOT force it into an
  existing evaluator (the IN-6 precedent).
- Author against `priya_validated:false` everywhere (no validated Assets threshold exists — the ticket's
  AS-1 claim is wrong per the CSV); leave UNSURE matrix cells un-encoded (couldnt_check-safe).
- **Activate nothing until calibrated** (LP-333/334): AS-9 (parsed/derived, no AI) is the one plausible
  early activation IF its page-count fields exist; every AI-fed AS rule waits on LP-334's calibration + a
  larger labeled set + Priya's bars.

## THE COST CHECK — is ~3/wave a trend?

**Largely yes, with one predicted-and-confirmed new primitive.** Wave 3 ≈:
- **AS-A** (this recon) · **AS-B** (authoring ~9 rules + declarations + recipes) · **AS-C** (eval) — the
  **3**.
- **+ the `per_account` enumerator + account-identity resolution** — a shared reusable primitive (the
  LP-332 borrower pattern applied to accounts; ~1 small ticket, reused by every future per-account rule).
- **+ AS-8 deferred** (its own shape ticket — like IN-6's gather leg; not counted against Assets).

So Wave 3 is **~3 authoring/eval tickets + 1 shared primitive (per_account) + 1 deferred shape (AS-8)** —
essentially the Income shape (3 + a shared paydown), NOT a regression to Wave 1's 7. **The trend holds:**
Wave 1 front-loaded 5 primitives; Wave 2 spent them for free; Wave 3 spends them AND adds exactly ONE new
granularity primitive (`per_account`) that the IN-C forecast predicted — then every later per-account
family (there are few) reuses it. **Predicted gaps for -B/-C:** (1) the `per_account` identity resolution's
fail-closed correctness (the masking cousin — AS-4/AS-3); (2) AS-4's reserve-matrix threshold shape; (3)
the calibration gate keeping most AS rules inert (bucket D) — the same honest inertness LP-333 documented,
not a failure.

## ADR

**None** — recon only, no architecture changed. Decisions surfaced for their own tickets: the `per_account`
SubjectType/enumerator + identity resolution; AS-8's pairwise-sequential shape; AS-4's reserve-matrix
threshold shape (derived tag vs structured reference). Named here, not decided.

## Cross-refs

verification-architecture-v2 §3D/§8; LP-323-IN-A (the recon template + the refuted-prediction method),
LP-323-IN-B/-C (authoring/eval precedent + ADR-273 + the PINs + the wave-cost forecast), LP-333 (activation
buckets + discipline), LP-334/335 (calibration gate + FINDING-1/2); LP-324/325/326/327/328/329/330/331/332
(the primitive set). Evidence: `rule_kinds.csv`, `fact_tags.csv`, `specs/AS-1.yaml`,
`tag_materialization/subjects.py`, `rule_engine/enumerators.py`, `snapshot/model.py` (the 4 calculators),
`calculations_section.py` (reserves), `classification_prompt.py` (document types), `specs.py`
(ReferenceValues).
