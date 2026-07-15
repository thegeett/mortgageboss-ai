# LP-323-IN-A — Income wave (Wave 2) recon + plan (READ-ONLY)

The first sub-ticket of Wave 2. Wave 1 (Identity) cost 7 tickets; 5 were one-time shape-space discovery
now reusable. The steady-state claim is **~3 tickets/wave**. This ticket tests that claim by planning the
Income family against the now-generic engine, and settles the ONE gap LP-323-ID-C predicted (the
calculator-operand seam) **with evidence from the real IN rules**. No code written — the only deliverable
is this file. All findings are file:line-grounded against the current repo.

---

## PHASE 0 — THE CALCULATOR-OPERAND GATE (the blocking verdict, reported first)

### Verdict: the predicted "calculator-operand primitive" (LP-332) is **REFUTED as stated**. A DIFFERENT, smaller gap is confirmed.

**The `calc` Operand already exists and generalizes.** `app/verification/rules/specs.py:190` — an
`Operand` may set `calc: tuple[str, str]` = `[calculator_name, value_key]`. `deterministic.py:103`
`_calc_operand` does `getattr(snapshot.calculations, calc_name)` and, per LP-318,
**a gated calc → `None` → couldnt_check** (`deterministic.py:109`: `if ... entry.gated: return None`).
AS-1 already reads `{calc: [dti, gross_monthly_income]}` (`specs/AS-1.yaml`). A new calc/key needs **zero
new operand code** — the operand is fully generic. So the ID-C prediction ("Income needs a
calculator-operand primitive") is **wrong, and that is good news: the engine is more general than feared.**

**BUT** the calculative IN rules do not chiefly read calculators at all — and where they need a computed
figure, the blocker is elsewhere. Two concrete sub-findings:

**(1) The income computations the rules need are NOT expressible with the current operand algebra, and NOT
produced by any wired calculator.** The `Operand` sources are exactly `tag | reference | calc | product`
(`specs.py:188-191`). `product` MULTIPLIES factors — there is **no `difference`, `ratio`, or `abs`**. The
three genuinely-arithmetic IN rules need exactly those:
- **IN-1** stated-vs-documented variance = `abs(income.documented_monthly − income.stated_monthly) /
  income.stated_monthly` vs a % — a difference-over-base ratio. Not expressible.
- **IN-3** YTD consistency = `income.ytd_gross` annualized over elapsed periods vs `income.documented_monthly`
  — division by elapsed time. Not expressible.
- **IN-4** employment gap = `next.income.employment_start − prior.income.employment_end` in days vs a window
  — a date **duration** (the date operand only compares with `< > ==`, `deterministic.py`/LP-328 — no
  subtraction). Not expressible.

And the only calculators wired into `snapshot.calculations` are **dti / ltv / mi / reserves**
(`snapshot/model.py:322-325`) — there is **no income/variance/YTD calculator**, and DTI's income is
**STATED by construction** (`calculations_section.py:20`: *"DTI uses STATED (MISMO) income … Reconciling
stated-vs-extracted income is a [separate] concern"*), so it cannot supply the *documented* side.

**(2) The clean fix is a DERIVED TAG, not a new operand and not a calculator.** LP-326 `derived` mode runs
a named Python recipe `(snapshot) → (value, reasoning)` (`tag_materialization/derived.py:3-6`,
`_app_required_fields_present` at `:34`), so a recipe **can do arithmetic** and abstain to `"unknown"`
when it cannot compute. So IN-1/IN-3/IN-4 become: a **derived tag** carrying the computed figure
(`income.stated_vs_documented_variance_pct`, `income.ytd_annualized_vs_documented`,
`income.employment_gap_days`), read by a plain `tag`-operand vs a `reference` threshold — **all existing
mechanisms.** No new operand kind, no new calculator, no engine change. This is **authoring, not
shape-space discovery.**

### What LP-332 actually is (evidence-based scope — NOT the predicted primitive)
LP-332 as predicted (a calculator-operand primitive) is **not needed and should be closed/withdrawn.**
What Income actually needs, in order:
- **(a) Three derived-income recipes** (variance %, annualized-YTD, employment-gap-days) — LP-326
  `derived` producers. Authoring; the mechanism exists. Belongs in **IN-B**, not a separate primitive.
- **(b) Per-borrower derived-tag keying** = the `borrower_id ↔ MISMO-index` resolution LP-331 already
  flagged as open (no code maps `borrower_id` in `tag_materialization/`; confirmed absent). This is the
  **ACTIVATION** blocker (evaluate ≠ activate), **shared with ID-8**, and is the one genuinely-new infra
  ticket the wave needs. Call it **LP-332 (reframed): borrower-keyed materialization + MISMO-index
  resolution** — it activates ID-8 AND the per-borrower income rules.

### LP-318 Caveat A — stays DEFERRED (contingent on the derived-tag choice)
Caveat A: gating fires on ABSENT calc inputs (via the gate over `gated_tags`), not on
**present-but-low-confidence** ones — `_calc_operand` reads `entry.value` and checks only `entry.gated`,
**ignoring `entry.confidence`** (`deterministic.py:103-110`; `CalculationEntry.confidence` exists at
`model.py:289` but no reader consults it). Does any IN rule need present-but-low-confidence gating? **No —
if the income computations are DERIVED TAGS** (recommended), their confidence flows through the ordinary
**tag gate** (`evaluate_gate` over `gated_tags` → below-floor → needs_review), which already handles
present-but-low-confidence. Caveat A only bites if LP-332 chose to implement the income math as a
**calculator** instead — then a low-confidence-but-not-gated income calc would be read at face value.
**Recommendation: derived tags, so Caveat A stays cosmetic and deferred.** Flag it as a design constraint
on LP-332, not a ticket.

---

## PHASE 1 — IN-1..IN-14 by kind / shape / evaluator

From `rule_kinds.csv` (the gate of record) + the tag vocabulary. All 14 are in-scope (none
`out_of_scope`). Shapes map to existing enumerators (`per_borrower` / `per_document` / `loan` all exist,
`enumerators.py`).

| Rule | Name | kind (CSV) | Evaluator / block | Shape | Reads |
|---|---|---|---|---|---|
| IN-1 | Stated vs documented income variance | calculative | **deterministic** (bookend) | per_borrower | `income.stated_monthly`, `income.documented_monthly` → **derived** variance% vs 5% ref |
| IN-2 | Pay-stub recency | structural | deterministic (date) | per_borrower (most-recent) | `income.pay_date` vs recency window (date ref) |
| IN-3 | YTD income consistency | calculative | deterministic (bookend) | per_borrower | `income.ytd_gross`, `income.pay_date`, `income.documented_monthly` → **derived** annualized |
| IN-4 | Employment gap | structural | deterministic (date) | per_borrower | `income.employment_start/end` → **derived** gap-days vs window |
| IN-5 | Employer name consistency | structural | **consistency** (LP-325 fuzzy) | per_borrower | `income.employer_normalized` gathered across docs |
| IN-6 | Pay-stub ↔ W-2 coverage | structural | **⚠ set-coverage** (see Phase 6) | per_borrower cross-doc-type | `income.employer_normalized` sets from paystub vs W-2 |
| IN-7 | Same line of work (job change) | judgmental | **judgment** (LP-327/331) | per_borrower | `income.same_line_of_work` (+ context) |
| IN-8 | VOE present | structural | deterministic (presence) | per_borrower | `income.voe_present` (yes/no) |
| IN-9 | Future employment (offer letter) | structural | deterministic (presence) | per_borrower | `income.future_employment`, `income.offer_letter_present` |
| IN-10 | Declining income | calculative | deterministic (over AI tag) | per_borrower | `income.is_declining` (the AI already computed the decline) |
| IN-11 | Variable-income averaging / history | calculative | deterministic or judgment | per_borrower | `income.type`, `income.has_2yr_history` |
| IN-12 | Self-employment income analysis | calculative | judgment | per_borrower | `income.type==self_employment`, `income.qualifying_monthly` |
| IN-13 | Other-income continuance | judgmental | **judgment** | per_borrower / per income-source | `income.continuance_3yr`, `income.type` |
| IN-14 | Rental-income support | judgmental | **judgment** | per_borrower / loan | `income.continuance_3yr`, `occupancy.rental_support` |

**Shape summary:** consistency ×1 (IN-5) · deterministic ×7 (IN-1/2/3/4/8/9/10) · judgment ×5
(IN-7/11/12/13/14) · **one shape that fits none cleanly: IN-6** (bidirectional set coverage — Phase 6).
**Nuance:** several "calculative" rows are deterministic-over-an-AI-tag — the AI does the structuring
(`income.is_declining`, `income.has_2yr_history`, `income.same_line_of_work`), and the RULE is a plain
predicate. Only IN-1/IN-3/IN-4 need real arithmetic (→ derived tags, Phase 0).

---

## PHASE 2 — Tags: exist vs new + declarations + gather contract + activation blocker

**Big finding: the income vocabulary already EXISTS** — `fact_tags.csv` carries **18 `income.*` tags +
`dti.qualifying_income_monthly`**, each with `used_by_rules` naming the IN rules. **But NONE are declared
in `tag_production.yaml`** (grep: no `income.*` there) — the vocabulary exists, the *materialization*
does not. So IN-B authors **declarations + producers**, not new vocabulary (mostly).

### EXISTS in `fact_tags.csv` — reuse (name → producer mode per the CSV)
`income.type` (AI), `income.stated_monthly` (parsed), `income.documented_monthly` (AI),
`income.qualifying_monthly` (AI), `income.has_2yr_history` (AI), `income.is_declining` (AI),
`income.employer_normalized` (AI), `income.employment_start/end` (parsed), `income.pay_date` (parsed),
`income.ytd_gross` (parsed), `income.same_line_of_work` (AI), `income.continuance_3yr` (AI),
`income.voe_present` (AI), `income.future_employment` (AI), `income.offer_letter_present` (AI),
`dti.qualifying_income_monthly` (derived, loan), `occupancy.rental_support` (AI, reused by IN-14).

### NEW tags to AUTHOR (the three derived computations — Phase 0)
| Tag | mode | subject | recipe | value_type / allowed |
|---|---|---|---|---|
| `income.stated_vs_documented_variance_pct` | derived | borrower | `abs(documented−stated)/stated` | number \| unknown |
| `income.ytd_annualized_vs_documented` | derived | borrower | YTD annualized ÷ elapsed vs documented | number \| unknown |
| `income.employment_gap_days` | derived | borrower | `next.start − prior.end` in days | number \| unknown |

Each returns `"unknown"` + reason when a feeding tag is absent/unknown (honest, `derived.py` contract).
These are **near-nothing engine-wise** — recipes registered like `_app_required_fields_present`.

**REUSE DISCIPLINE — no fragmentation:** IN rules must read `income.documented_monthly` /
`income.qualifying_monthly` as the vocabulary defines them (documented = what docs support; qualifying =
usable after averaging) — do NOT mint a second "computed income" tag. `dti.qualifying_income_monthly`
(loan-level sum) already exists and is used by AS-1/AS-3/DT-1 — the per-borrower income rules read the
per-borrower `income.*`, the loan-level DTI reads the sum; keep that split (they are genuinely distinct:
per-borrower vs loan aggregate).

### THE LP-325 GATHER CONTRACT (cross-source income facts key under the DOCUMENT subject)
IN-5 (and IN-6) gather `income.employer_normalized` across a borrower's documents — so, exactly like the
id.* facts (`tag_production.yaml:19-21` "keyed under the DOCUMENT subject … even when logically about the
borrower"), `income.employer_normalized` must key under **document**, co-located with any filter tag (e.g.
`income.type` if a rule filters to base-employment docs). IN-1/IN-3's inputs (`income.documented_monthly`,
`income.ytd_gross`, `income.pay_date`) are per-document facts the derived recipe aggregates per borrower —
they key under **document**, and the derived variance tag keys under **borrower**.

### THE `borrower_id ↔ MISMO-index` ACTIVATION BLOCKER (LP-331, still open)
Confirmed still open: no code in `tag_materialization/` maps `borrower_id`, and `income.stated_monthly`
is a MISMO fact keyed by borrower INDEX (`borrower.N.*`) while `per_borrower` enumerates `belongs_to`
UUIDs. So **every per-borrower income rule (IN-1/2/3/4/7/10/11/12/13, ~9 of 14) can be EVALUATED against
fixtures but NOT ACTIVATED** until this resolution lands — identical to ID-8's status. This is **LP-332
(reframed)** and it activates ID-8 too. **-B and -C proceed regardless** (author + eval with fixtures,
activate later — the LP-325/326/331 restraint).

---

## PHASE 3 — Thresholds: agency-default vs overlay-pending vs UNSURE

The model: the AGENCY value is the DEFAULT and AUTHORITATIVE (encode with citation);
`priya_validated:false` / `threshold_needs_signoff:true` applies only where a lender OVERLAY / deviation /
genuine ambiguity exists. **No IN threshold is encoded in the repo yet** (grep of `specs/` for income
thresholds → none; no `reference_values` for income). Below is the plan, with honest UNSURE flags.

| Rule | Threshold | Agency default (needs Priya/guideline confirm) | Reference | Status |
|---|---|---|---|---|
| **IN-1** | stated-vs-documented variance | **see discrepancy below** | Fannie B3-3.1 | **OVERLAY-PENDING → priya_validated when set** |
| IN-2 | pay-stub recency | most recent within ~30 days of application (Fannie B3-3.1-02) | B3-3.1-02 | AGENCY-DEFAULT (confirm 30d) |
| IN-3 | YTD tolerance | UNSURE of a numeric YTD tolerance % | B3-3.1 | **UNSURE — do not guess** |
| IN-4 | employment gap | a gap > ~30 days needs a letter of explanation; > 6 months breaks 2-yr history | B3-3.1-01/02 | AGENCY-DEFAULT (confirm windows) |
| IN-10 | declining income | a decline is a flag; no single numeric cutoff — treatment is Priya-validated (per CSV rationale) | B3-3.1 | OVERLAY-PENDING |
| IN-11 | averaging period | 24-month avg for variable income; 12-month if trending — method Priya-validated | B3-3.1-01 | OVERLAY-PENDING |
| IN-12 | self-employment | 2-yr returns, Form 1084 add-backs — method Priya-validated (CSV rationale) | B3-3.2 | OVERLAY-PENDING |
| IN-13 | continuance | income must continue ≥ 3 years | B3-3.1-09 | AGENCY-DEFAULT (confirm 3yr) |

### ⚠ THE IN-3 / IN-1 DISCREPANCY (a correction the ticket asked me to confirm)
The ticket says *"IN-3 is the known exception: Priya HAS validated the stated-vs-documented income
variance at 5%."* **That rule id is IN-1, not IN-3.** `rule_kinds.csv`: **IN-1** = "Stated vs documented
income variance" (`used_by` for `income.documented_monthly` = IN-1); **IN-3** = "YTD income consistency".
Also: **neither is `priya_validated:true` in the CSV today** — both show `priya_validated=false,
threshold_needs_signoff=true`, and **no 5% value is encoded anywhere** (grep → none). So: the
Priya-validated-5% stated-vs-documented variance is **IN-1**; when it ships, IN-1's `rule_kinds.csv` row
flips to `priya_validated:true` and its `reference_values.values` carries `income_variance_threshold_pct:
"5%"` with the citation. **Confirm with Priya that 5% (not the 10% default assumption) is the validated
IN-1 value before -B encodes it.** (If Priya truly validated it, this is the rare `priya_validated:true`
row — but the CSV needs updating; do not assume the ticket's "IN-3" label.)

**UNSURE (do NOT guess in -B):** the IN-3 YTD numeric tolerance; the exact IN-2/IN-4 day windows; the
IN-11 averaging trigger. Encode only with a citation Priya/guideline confirms.

---

## PHASE 4 — The eval plan (the 13-point matrix, per rule)

Cases 3/4 (boundaries) are **FINALLY REAL** for this family (IN-1's 5% variance has genuine over/under
boundaries, unlike ID's string compares). **Case 12 (gated calc/derived → couldnt_check) is FINALLY IN
PLAY** — the derived income tags gate to `unknown`/absent, so a rule reading them degrades to
couldnt_check (the path ID could never test). Case 11 (armor) applies to the judgment rules
(IN-7/11/12/13/14). N/As stated explicitly.

**Representative per-rule cases (the -C ticket writes these):**
- **IN-1** (variance, boundaries real): 1 documented 20% off stated → fire · 2 within 5% → satisfied ·
  **3 at 5.01% → fire** · **4 at 4.99% → satisfied** · 5 `income.documented_monthly` absent → couldnt_check
  · 6 documented `"unknown"` → couldnt_check (distinct, at the gate) · 7 low-conf documented → needs_review
  · 8 variance: stated annual vs documented monthly unit mismatch (the direction=="credit" class) ·
  9 provenance · 10 tag-level golden on `income.documented_monthly` + the derived variance% ·
  **12 the derived variance tag is `unknown` (a feeding tag gated) → couldnt_check** ·
  **13 DOMAIN: a raise between the paystub and the VOE** (documented > stated is not a defect — higher
  documented income should not fire; only a SHORTFALL past tolerance fires).
- **IN-2** recency: 1 newest paystub 45d old → fire · 2 within window → satisfied · **3/4 at the day
  boundary** · 5 `income.pay_date` absent → couldnt_check · 13 DOMAIN: a **partial-period paystub** (a
  mid-cycle stub is not "stale").
- **IN-3** YTD: 1 YTD annualized 30% below documented → fire · 2 consistent → satisfied · 3/4 tolerance
  boundary (**UNSURE tolerance — placeholder until Priya**) · 12 derived annualized `unknown` →
  couldnt_check · 13 DOMAIN: **YTD vs annualized mismatch from a mid-year start** (short YTD is expected,
  not a discrepancy).
- **IN-4** gap: 1 > window gap → fire · 2 continuous → satisfied · 3/4 day boundary · 13 DOMAIN: **a job
  change with a short, explained gap** vs an unexplained multi-month gap.
- **IN-5** employer consistency (LP-325): 1 genuinely different employers → fire · 2 exact match → satisfied
  (+ NO-AI cost) · 5 <2 sources → couldnt_check · 8 legal-vs-DBA name variance → AI agrees · 11 N/A
  (consistency) · 13 DOMAIN: **a legal name ("Acme Corp") vs common ("Acme")** is benign.
- **IN-6** coverage: 1 a W-2 employer with no matching paystub → fire · 2 sets cover both ways → satisfied
  · 13 DOMAIN: **a second job on a paystub but not yet on a W-2** (new job — expected, judged not fired).
  **(Shape open — Phase 6.)**
- **IN-7** (judgment, armor): 1 unrelated field change → needs_review · 2 same field → satisfied-pending ·
  **11 every verdict ratification-pending** · 5 `income.same_line_of_work` absent → couldnt_check · 13
  DOMAIN: **teacher → school administrator** (same field, stable) vs **nurse → day-trader**.
- **IN-8** VOE: 1 absent VOE → fire · 2 present → satisfied · 13 DOMAIN: a **verbal** VOE where written
  is required.
- **IN-9** offer letter: 1 future job, no offer letter → fire · 2 offer + start date → satisfied · 13
  DOMAIN: **start date after the note date** (needs first-paystub condition).
- **IN-10** declining: 1 `income.is_declining==yes` → fire · 2 `no` → satisfied · 13 DOMAIN: **a decline
  that still "passes" DTI is a red flag** (fires on the decline, not the ratio).
- **IN-11** averaging: 1 variable income < 2-yr history → fire · 2 ≥ 2-yr → satisfied · 13 DOMAIN:
  **bonus/commission 24-mo vs 12-mo averaging**.
- **IN-12** self-employment (judgment): 1 net + add-backs unsupported → needs_review · 11 armor · 13
  DOMAIN: **K-1 / 1099 / P&L** with declining net.
- **IN-13** continuance (judgment): 1 income ending < 3yr → needs_review · 11 armor · 13 DOMAIN: **child
  support ending in 18 months**.
- **IN-14** rental (judgment): 1 `occupancy.rental_support==inadequate` → needs_review · 11 armor · 13
  DOMAIN: **vacancy/expense adjustment** on gross rent.

**Every rule has a credible MUST-FIRE case** — no rule looks mis-specified. **N/A (explicit):** case 11
(armor) N/A for the deterministic/consistency rules IN-1/2/3/4/5/8/9/10; case 3/4 (boundary) N/A for the
presence rules IN-8/9 and the enum rules IN-7/10/13 (no numeric threshold — the enum tag IS the verdict).

---

## PHASE 5 — The multi-value gather-into-judgment question (ID-C predicted gap #3)

LP-331 deferred the leg where a judgment reasons over a MULTI-VALUED gathered fact. **Does Income need
it?** — **Yes, for at most two rules, and it can be avoided:**
- **IN-6** (paystub↔W-2 coverage) is the clearest candidate: it reasons over the SET of employers from
  paystubs vs the SET from W-2s. Two honest options: (a) a **new consistency shape** (set-coverage,
  bidirectional containment — genuinely different from LP-325's all-agree/fuzzy-residue), or (b) a
  **judgment over the two gathered sets** (needs the multi-value gather leg). **Recommendation:** model
  IN-6 as a **judgment over the gathered employer sets** (the AI sees both sets and judges coverage,
  flagging a new/second job as benign) — this is more forgiving of the legitimate multi-employer case
  than a rigid set-diff, and it reuses the judgment path once the gather leg exists.
- **IN-11** (averaging over several paystubs) reads pre-structured tags (`income.has_2yr_history`,
  `income.qualifying_monthly`) — the AI already did the multi-paystub averaging into a tag, so IN-11
  does **not** need the raw multi-value set. Avoided.

So the multi-value gather-into-judgment leg is needed for **IN-6 only** (if we choose option b). Reason
over the SET with the disagreement visible to the AI (a borrower legitimately has 2 employers →
"resolving them" is not a consistency rule's job here — there is nothing to reconcile, the sets SHOULD
differ across a new-job boundary). **Recommend, do not build** — decide IN-6's shape in -B's design.

---

## PHASE 6 — New shape / blocking gap

**IN-6 (pay-stub ↔ W-2 coverage) is the one rule whose shape fits none of the four cleanly.** It is a
**bidirectional set-coverage** check, not "all instances agree" (LP-325) — a borrower with two jobs SHOULD
show two distinct employers; the check is that the *sets* cover each other across document types.
- **Not a blocking gap for the wave** — it can be authored as a **judgment over the gathered sets** (Phase
  5 option b), which needs the multi-value gather leg but no new evaluator family.
- **Decision to make in -B:** set-coverage-as-a-new-consistency-shape vs judgment-over-sets. Named here,
  not decided (recon only). Everything else (IN-1..5, 7..14) fits an existing evaluator + enumerator.

---

## RISKS / OPEN QUESTIONS / PRIYA

| # | Item | Rule(s) | Status |
|---|---|---|---|
| 1 | **IN-1 5% variance** — confirm the value AND that the rule is IN-1 (not IN-3) | IN-1 | **Priya — the one that ships `priya_validated:true`; the CSV/label needs correcting** |
| 2 | YTD numeric tolerance | IN-3 | **UNSURE — Priya/guideline; do not guess** |
| 3 | Pay-stub recency window (30d?) | IN-2 | AGENCY-DEFAULT — confirm |
| 4 | Employment-gap windows (30d LOE / 6-mo history) | IN-4 | AGENCY-DEFAULT — confirm |
| 5 | Variable-income averaging method (24 vs 12 mo) | IN-11 | Priya (CSV: method-validated) |
| 6 | Self-employment method (1084 add-backs) | IN-12 | Priya (CSV: method-validated) |
| 7 | Declining-income treatment | IN-10 | Priya (CSV rationale) |
| 8 | Continuance horizon (3yr) | IN-13/14 | AGENCY-DEFAULT — confirm |
| 9 | Non-taxable income gross-up | IN-1/3 | Priya — affects the documented figure |
| 10 | IN-6 shape decision | IN-6 | -B design decision |
| 11 | `borrower_id ↔ MISMO-index` | IN-1/2/3/4/7/10/11/12/13, ID-8 | Activation blocker (LP-332 reframed) |

**A wrong encoded guideline value mis-evaluates silently and permanently** — every UNSURE row ships
`threshold_needs_signoff:true` and is left un-encoded (couldnt_check-safe) until confirmed.

---

## RECOMMENDATION

**PROCEED to LP-323-IN-B** (author the 14 specs + ~18 tag declarations + 3 derived-income recipes +
thresholds). **LP-332 as originally predicted (a calculator-operand primitive) is NOT needed and should
be withdrawn** — the calc operand already generalizes and the income math is best done as derived tags.
- **-B and -C do NOT depend on LP-332** landing first: the rules are authored and evaluated against
  fixtures now; ACTIVATION waits on the borrower-keyed materialization (LP-332 reframed), exactly as ID-8
  waits today. No blocking gap forces a pause.
- **-B must decide IN-6's shape** (set-coverage vs judgment-over-sets) and must **confirm the IN-1 5%
  value + rule-id correction with Priya** before encoding it.

## COST CHECK — does Wave 2 look like the predicted ~3 tickets?

**Yes, essentially — and the predicted expensive gap evaporated.** Wave 2:
- **IN-A** (this recon) · **IN-B** (authoring) · **IN-C** (eval) — the predicted **3**.
- **+ LP-332 (reframed):** borrower-keyed materialization + `borrower_id↔MISMO-index` — **but this is
  shared infra that also activates ID-8** (a Wave-1 debt), and is an ACTIVATION ticket, not a per-wave
  authoring cost. Count it once, across waves.
- The predicted **calculator-operand primitive did NOT materialize** — refuted with evidence. The engine
  the ID wave generalized already covers Income's arithmetic via derived tags. **This is the steady-state
  claim holding up:** Wave 2 is ~3 authoring/eval tickets + one shared activation ticket that pays down an
  existing debt. No new *evaluator family*, no new *operand*, no new *calculator wiring* required.
- **The one genuinely-new shape (IN-6 set-coverage)** is absorbable as a judgment — a design decision, not
  a ticket. If -B finds it needs a distinct set-coverage evaluator, that is a small +1 (the multi-value
  gather leg), still far below Wave 1's five-gap discovery cost.

**Forecast for Waves 3–10:** ~3 tickets/wave holds, plus the occasional shared-infra paydown
(borrower-keyed materialization here) and at most one small shape/leg per wave. The front-loaded Identity
discovery is paying off.

## ADR

**None** — recon only, no architecture changed. Two decisions are *surfaced* for their own tickets, not
decided here: (1) the income-computation mechanism (derived tags — recommended — vs a calculator, which
would revive Caveat A); (2) IN-6's shape (judgment-over-sets vs a new set-coverage consistency evaluator).

## Cross-refs

verification-architecture-v2 §3A/§3D/§8/§9; LP-323-ID-A (wave template), LP-323-ID-C (wave-cost
assessment + the predicted gaps); LP-324 (generic evaluators + the `calc` operand), LP-325 (consistency +
gather contract), LP-326 (tag declarations + derived recipes), LP-327/331 (judgment + borrower-keyed
facts), LP-328 (typed operands + reference%), LP-318 (calculators + Caveat A). Evidence: `rule_kinds.csv`,
`fact_tags.csv`, `specs.py`, `deterministic.py`, `tag_materialization/derived.py`, `calculations_section.py`,
`snapshot/model.py`.
