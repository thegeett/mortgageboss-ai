# LP-323-AS-C — ASSETS family eval (the full case matrix + calibration)

Wave 3's eval ticket. The rules are authored (LP-323-AS-B: 10 specs AS-2..AS-12 minus the deferred AS-8, as
pure DATA). This is the **first real evaluation** of the Assets family: every rule exercised through its
real evaluator, the full 13-point matrix, calibration for the AS AI tags, and the four PINS. **EVALUATE,
DON'T FIX** — every gap becomes a failing-in-the-real-world scenario or a pin, never an edit to a
rule/tag/spec/engine.

## THE SUCCESS CRITERION — HELD ✅ (eval side)

Two test modules + this doc + one calibration-**registry** line. **No engine/evaluator/gate/producer code
touched.** The only `app/` edit is registering the 5 new AS AI tags in `calibration.py`'s
`_ABSTAINING_DIMENSIONS` — the calibration registry (data), exactly as ID-C and IN-C registered their
families, NOT engine logic. `mypy app/` clean (281 files); the whole verification suite green
(713 passed, 4 live-skips).

## NONE of the 10 is activated (verified)

`ACTIVE_RULE_IDS` unchanged = (AS-1, OC-2, ID-1..4/6..9, IN-2) — no AS-2..AS-12. Each is exercised by
calling its evaluator **directly** (activation gates the orchestrator, not the evaluator), exactly as ID-C/
IN-C did. `test_none_of_the_10_is_activated` asserts this — evaluated, not shipped (the LP-333 discipline:
no rule ships uncalibrated AI or an uncalibrated threshold into a trusted verdict).

## PER-RULE CASE TABLE (the 13-point matrix, per rule)

The matrix: 1 fire · 2 satisfied · 3/4 boundaries · 5 absent→couldnt_check · 6 unknown→couldnt_check ·
7 low-conf→needs_review · 8 label-variance · 9 provenance/reasoning · 10 tag-level · 11 judgment-armor ·
12 gated-calc→couldnt_check · 13 domain edge. N/A cells are noted (a numeric/derived tag has no low-conf
needs_review; a deterministic rule has no armor; etc.).

| Rule | Shape | Cases exercised | Headline |
|---|---|---|---|
| **AS-4** reserves | det, loan (calc) | 1,2,3,4,5/6,**12**,13 + MASKING pin | **case 12 REAL** — a GATED `reserves` calc → operand None → couldnt_check |
| **AS-10** recency | det, loan (derived) | 1,2,4,5,13 (per-account min) | the anti-masking counter-example: a 1-month account is NOT masked by a 3-month one |
| **AS-7** NSF | det, loan (derived) | 1,2,3,4,5,9 | clean numeric boundaries (4>3 fire, 3 satisfied) |
| **AS-6** ownership | det, per_document | 1,2,6,7 + scope | low-conf→needs_review real (an enum, conf 0.2); non-statement→not_applicable |
| **AS-11** liquidation | det, per_document | 1,2,13 + scope | restricted 401(k) fires; non-retirement→not_applicable |
| **AS-5** gift chain | det, per_document | 1,2,13/scope | gift letter but non-gift transfer fires; no-gift-used→not_applicable |
| **AS-2** EMD | det, per_deposit | 1,2,6 + APPROX pin | label→enum abstraction (case 8); unknown source→gate |
| **AS-3** cash-to-close | det, loan | BUCKET C pin | recipe abstains (no closing_costs)→couldnt_check |
| **AS-9** missing pages | det, per_document | BUCKET C pin | no page-count extraction→couldnt_check |
| **AS-12** borrowed funds | judgment, per_deposit | 1,5/**11**,9,12 | armor (ratification_pending); fail-closed (gated tag→no AI call) |

Plus `per_account` (LP-336): an ambiguous account identity (a statement missing bank_name) is NOT merged —
it drops to `unresolvable`, never a guessed grouping.

## THE FOUR PINS (asserted, not narrated)

1. **AS-4 aggregate MASKING** (`test_as4_case13_investment_matrix_and_the_MASKING_pin`). AS-4 reads ONE
   aggregate (`reserves.months_available`) and has NO per-account input, so a passing aggregate **satisfies
   it even if that total includes an ineligible/inflated account** — the only guard is upstream
   (`asset.usable_value` zeroing ineligible funds), which is UNCALIBRATED AI. Contrast AS-10, whose recipe
   takes the per-account MINIMUM (`resolve_accounts`, LP-336) so a single short account is never masked —
   asserted side-by-side in `test_as10_domain13_a_short_account_is_not_masked_by_a_full_one`. PINNED as a
   fix ticket: give AS-4 per-account visibility, or trust the upstream once calibrated.
2. **AS-2 APPROXIMATION** (`test_as2_fire_and_case8_and_the_approximation_pin`). The TRUE EMD check is a
   cross-document MATCH (the contract's EMD amount ↔ a debit in a verified account). The authored rule
   approximates it via txn sourcing: it does NOT match the contract amount, does NOT check direction (an
   EMD is a DEBIT), and does NOT catch an EMD paid OUTSIDE the statements. PINNED (needs the contract EMD
   extracted first).
3. **AS-3 BUCKET C** (`test_pin_as3_bucket_c_closing_costs_absent`). `closing_costs` is not a fact today
   (no Loan-Estimate/CD extraction) → the cash-to-close recipe abstains → couldnt_check. Upstream ask: an
   LE/CD extraction producing `closing_costs`.
4. **AS-9 BUCKET C** (`test_pin_as9_bucket_c_no_page_count_extraction`). `bank_statement.py` extracts no
   page count → the page tags never materialize → couldnt_check. Upstream ask: a "Page X of Y" field.

## CALIBRATION — the AS AI tags (enum-scorable; free-text deferred)

Same two numbers per dimension as ID-C/IN-C (UNKNOWN RATE / ACCURACY-WHEN-CONCRETE), reusing the LP-317
`DimensionCalibration` primitive UNCHANGED. **Registered** the 5 string-scorable AS AI tags in
`_ABSTAINING_DIMENSIONS`: `stmt.owner_matches_borrower`, `stmt.is_reserve_eligible`,
`asset.liquidation_terms`, `asset.usable_value`, `as.borrowed_funds` — else `over_abstaining` would be
silently inert for the family.

**FINDING-2 (LP-334) is load-bearing:** `txn.counterparty` is FREE TEXT ("Chase Wire Dept" vs "chase wire"
are the same counterparty; string equality scores them wrong) — it is **DEFERRED**, named explicitly in
`_DEFERRED_FREE_TEXT_TAGS`, and NOT fed to the string scorer where it would fabricate a false
under-abstention flag. `txn.apparent_category` is excluded deliberately (its "unknown" is a legitimate
value, per calibration.py's own note).

**The numbers:** keyless (labels replayed) is the trivially-perfect plumbing baseline — unknown-rate 0.20,
concrete-accuracy 1.0, no flag — a structure check, NOT a real measure of the model. **The metric is NOT
inert:** a 70%-unknown distribution on every AS tag fires `over_abstaining` (which ALSO proves each is
registered), and a 40%-wrong `asset.usable_value` fires `under_abstaining` (the dangerous direction — it
feeds the reserves calc AS-4 reads). **The meaningful LIVE measure** (the real stmt_facts/asset_facts/AS-12
reasoners over raw statements, scored vs golden) is a documented follow-on seam, SKIPPED without a key,
never fabricated.

## PRIYA / HUMAN-VERIFY list (Assets)

| # | Item | Rule | Encoded | Confirm |
|---|---|---|---|---|
| 1 | **Reserve MONTHS matrix** (headline) | AS-4 | investment 6 / second-home 2 / 1-unit primary 0; rest abstain | the full matrix (units × LTV × program) |
| 2 | **Retirement discount 60 vs 70%** (headline) | AS-11 | UNSURE — not encoded | the factor |
| 3 | Statement months required | AS-10 | 2 (agency-default) | confirm the lender's bar |
| 4 | NSF tolerance | AS-7 | 3 (overlay default) | the lender's threshold |
| 5 | Gift-fund chain links | AS-5 | presence (B3-4.3-04) | the required links |
| 6 | EMD true shape | AS-2 | approximation | the cross-doc-match rule |

Every `guideline_text`/`guideline_reference` (Fannie B3-4.1-01 / B3-4.2-01/02 / B3-4.3-03/04) is
transcribed at authoring — HUMAN-VERIFY, never AI-recalled.

## AS-8 — DEFERRED (asserted `RuleSpecNotFound`); AS-1 — LIVE (asserted unchanged)

`test_as8_deferred_and_as1_unchanged` pins both: AS-8 raises `RuleSpecNotFound` (its pairwise-sequential
chaining is a NEW SHAPE — LP-323-AS-A's decision; LP-336 gave it its enumerator, not its shape); AS-1 is
still `per_deposit` and still in `ACTIVE_RULE_IDS` (this wave changed nothing live).

## THE WAVE-COST ASSESSMENT

**What Wave 3 (Assets) actually cost — the three-wave trend:**

| Wave | Family | Tickets | Note |
|---|---|---|---|
| 1 | Identity | ~7 | front-loaded the five reusable primitives (evaluators, gate, enumerators, subjects, calibration) |
| 2 | Income | 3 | spent them; **zero** engine code |
| 3 | Assets | 3 + 1 | AS-A + AS-B + AS-C, **plus LP-336** (the `per_account` primitive) |

So the honest trend is **7 → 3 → 4**, where Wave 3's +1 is a **one-time-shared primitive** (`per_account`
+ fail-closed `resolve_accounts`), not a per-wave authoring cost — the direct analog of Wave 1's front-load.
Strip the shared primitive and the steady state is **3/wave, holding.** The eval touched no app/ engine
code (the calibration-registry line aside) — the clean two-modules-and-a-doc shape, like ID-C/IN-C.

**Did evaluating reveal engine gaps authoring didn't?** No new ones. The eval CONFIRMED AS-B's reported
gaps by turning them into failing scenarios (AS-4's masking; AS-3/AS-9 bucket C; AS-2's approximation) and
proved case-12 (the gated reserves calc) is genuinely real — the first time the `calc` operand's
gated→None→couldnt_check path is exercised end-to-end (ID had no calc; Income only approximated it via a
derived tag).

### THE HONEST LEDGER — ~23 authored-but-inert rules

34 specs authored; **11 active**; **23 authored-but-inert** — and this is the real question the trend
raises. The inert set and WHAT BLOCKS each:

- **Blocked on CALIBRATION (uncalibrated AI feed — bucket D):** AS-2/4/5/6/7/11/12, plus the income
  judgment/structuring rules (IN-1/3/4/5/7…). The gate is real: no rule ships uncalibrated AI into a
  trusted verdict. **Unblocked only by the LIVE calibration harness** (the follow-on seam this ticket
  documents) producing real numbers + Priya's bars.
- **Blocked on EXTRACTION (bucket C):** AS-3 (closing_costs / an LE-CD extractor), AS-9 (page-count field),
  and any income rule needing an un-extracted field. Each is a concrete extractor ask, not an engine gap.
- **Blocked on PRIYA THRESHOLDS:** AS-7 (NSF tolerance), AS-10 (months required), AS-4's full matrix,
  AS-11's discount factor — a validated-number sign-off, not code.
- **Blocked on DEFERRED SHAPES (not even authored):** AS-8 (pairwise-sequential), IN-6 (set-coverage) —
  each needs a new one-time-reusable evaluator leg, then every rule of that shape authors cheaply.
- **Nearly-activatable:** **AS-10** is the closest AS candidate — it reads PARSED period fields + a derived
  recipe (NO AI), so only its 2-month threshold (Priya) and the parsed `stmt.period_*` fields materializing
  stand between it and activation. A named first-AS-activation candidate once the threshold lands.

**Forecast for Waves 4–10:** DTI reads the wired calculator (the `calc` operand generalizes — proven by
AS-1 AND now AS-4's case-12) → ~3, no new primitive. Title/insurance/condo → ~2–3 each (LP-329
applicability + LP-330 expected-absence already cover the shapes). **Credit/property are BLOCKED on
blocker-document extractors** (credit-report/appraisal parsing) — authoring+eval proceed against fixtures,
activation waits; an infra dependency, not a per-wave cost. Genuinely new arithmetic (amortization, LTV
tiers) is a derived-recipe registry entry, not engine Python (ADR-273 holds).

### THE HONEST QUESTION — another wave, or unblock the 23?

The trend says another wave (Wave 4/DTI) costs ~3 tickets and adds ~5 more authored-but-inert rules —
widening the ledger to ~28. **Authoring is cheap; ACTIVATION is the value, and activation is blocked on
four non-authoring levers:** (1) the **LIVE calibration harness** (unblocks the largest bucket — every
AI-fed rule across ID/IN/AS at once), (2) the **borrower-keyed materialization** (PIN #1 / ID-8 — shared
across families), (3) a **handful of extractor asks** (closing_costs, page-count, contract-EMD), (4)
**Priya's threshold sign-offs**. Each unblocks rules *already written* across every wave — a higher
value-per-ticket than authoring a new inert family. **Recommendation:** before Wave 4, land the LIVE
calibration harness (it converts the single largest inert bucket to activatable) and AS-10's threshold (the
cheapest first-AS activation, proving the AS family can go live). Then resume authoring with a real
activation to show for it. The authoring machine is proven (3/wave, zero engine code); the constraint has
moved from *writing rules* to *trusting them*, and the next tickets should attack trust.

## ADR

No new ADR — AS-C is eval + a calibration-registry addition (the ID-C/IN-C pattern). The relevant decisions
already exist: ADR-273 (arithmetic as derived recipes), ADR-278 (the reserve matrix as a derived tag).

## Cross-refs

LP-323-AS-A (recon + domain edges), LP-323-AS-B (the authored rules + D1-D4 + the reported gaps), LP-336
(`per_account` + `resolve_accounts` — the AS-10 anti-masking + the ambiguous-identity case), LP-333
(activation buckets + the no-uncalibrated-AI discipline), LP-334/335 (the calibration gate + FINDING-2 that
defers `txn.counterparty`), LP-323-ID-C / LP-323-IN-C (the eval-module + calibration precedents this
mirrors).
