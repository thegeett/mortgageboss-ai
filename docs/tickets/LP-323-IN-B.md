# LP-323-IN-B — Author the INCOME family (specs + tag declarations + derived recipes; DATA ONLY)

Wave 2's authoring ticket. LP-323-IN-A's recon refuted the predicted calculator-operand gap and found the
income arithmetic routes through LP-326 DERIVED TAGS. This ticket authors IN-1..IN-14 as DATA and tests
the wave's steady-state claim: **can a whole family be added with ZERO engine Python?**

## THE SUCCESS CRITERION — HELD ✅

**Income is the first wave where authoring required no engine Python.** Git-verified (`git diff
--name-only`): the evaluators (`deterministic.py` / `consistency.py` / `judgment.py`), the gate, and the
producer core (`producer.py` / `declarations.py` / `subjects.py`) are **UNTOUCHED**. What changed:

| File | Kind | Engine Python? |
|---|---|---|
| `rules/specs/IN-*.yaml` (13 new) | rule SPECS (data) | no |
| `rules/tag_production.yaml` | tag DECLARATIONS (data) | no |
| `rules/vocabulary_extra.yaml` | new vocab tags (data) | no |
| `tag_materialization/derived.py` | 4 recipe **registry entries** + helpers | **the sanctioned extension point** (LP-326: "adding a family = entries here, never new producer Python"). `produce_derived_tags` untouched. |
| tests | count bumps + the income smoke test | no |

Adding recipe *functions + registry entries* is exactly what LP-326's `derived` mode is for (the
`_app_required_fields_present` precedent) — NOT editing the generic producer, the gate, or any evaluator,
and NO rule-id/family branch anywhere. **The steady-state claim holds: a family is DATA + recipes.**

## Acceptance criteria

- [x] 13 of 14 IN rules authored as specs that LOAD (cross-checked against `rule_kinds.csv` — kind /
  numeric_check / priya_validated / threshold_needs_signoff all agree). IN-6 deferred (D3).
- [x] The 18 existing `income.*` vocabulary tags declared in `tag_production.yaml` (4 AI groups + parsed);
  7 new tags in `vocabulary_extra.yaml` (4 derived arithmetic + 3 judgment verdict tags).
- [x] 4 derived recipes, each ABSTAINING to `"unknown"` with a reason when a feeding tag is
  absent/unknown (never a fabricated number).
- [x] Every authored rule runs from its spec through a GENERIC evaluator (proven in the smoke test).
- [x] IN-1 DIRECTION edge (a raise → satisfied, not fired); IN-5 exact-match COST property (no AI call);
  judgment ARMOR (every verdict ratification-pending); derived-tag → couldnt_check (case-12 path).
- [x] ruff + mypy + full suite green (2144 passed, 1 skipped, 1 xfailed). No engine Python.

## THE DECISIONS

### D1 — the IN-1 5% gate + the rule-id correction
IN-A found my ticket said *"IN-3 is the Priya-validated 5% stated-vs-documented variance."* **The
stated-vs-documented variance rule is IN-1**, not IN-3 (rule_kinds.csv: IN-1 = "Stated vs documented
income variance", IN-3 = "YTD income consistency"; `income.documented_monthly.used_by` = IN-1/IN-3).
Neither is `priya_validated:true` in the CSV, and no 5% is encoded anywhere. **So IN-1 is authored with
the 5% value but `priya_validated: false` / `threshold_needs_signoff: true`** (matching the CSV), and a
loud comment: *confirm 5% (not the 10% default) with Priya, then flip the CSV row AND the spec flag
together.* This is the top Priya item. Verified against `rule_kinds.csv`, not the ticket text.

### D2 — the income-arithmetic mechanism: DERIVED TAGS (confirmed), + a NEW producer finding
IN-A recommended derived tags over a new operand/calculator, routing around LP-318's Caveat A. **Confirmed
in implementation** — but with a real new finding:

**NEW FINDING (reported, not worked around): the derived producer is LOAN-ONLY.**
`produce_derived_tags` (derived.py) raises for any `subject != "loan"`, and `validate_declarations`
rejects a non-loan derived declaration at load (*"derived recipes are loan-level today"*). So a
per-BORROWER derived tag is **not supported**. IN-1/IN-2/IN-3/IN-4's arithmetic is therefore authored as
**LOAN-LEVEL aggregates** (a recipe sums the file's documents, exactly as the DTI calculator aggregates
income to a loan total). This is:
- a **DESIGN CHOICE that HOLDS the criterion** (loan-level recipes are registry entries; per-borrower
  would have forced an edit to `produce_derived_tags` — which I did NOT do, per the "STOP and report"
  rule), and
- a **v1 with a KNOWN LIMITATION**: a 2-borrower file where one borrower's income is inflated can be
  masked by the aggregate. **Per-borrower granularity needs a per-borrower derived producer** — the same
  `borrower_id ↔ MISMO-index` / borrower-keyed materialization work that ID-8 waits on (LP-332 reframed).
  Reported, not built.

**Caveat A stays deferred — CONFIRMED avoided.** Because the arithmetic is DERIVED TAGS (not calculators),
each tag's abstention (`"unknown"` + reason) flows through the ordinary tag gate — the smoke test proves a
feeding-tag-absent derived tag → couldnt_check. A calculator would have revived Caveat A (`_calc_operand`
ignores `entry.confidence`); we did not go there.

**The DIRECTION edge (implementation detail beyond IN-A's naming):** IN-A called the tag
`income.stated_vs_documented_variance_pct` (an ABS variance). Implemented, that would false-fire on a
RAISE (documented > stated → large abs variance → fire). So the tag is authored as a **SIGNED SHORTFALL**
`income.documented_income_shortfall_pct` = `(stated − documented)/stated`: positive = a real shortfall,
negative = a raise (never fires). The smoke test asserts a raise → satisfied.

### D3 — IN-6's shape: DEFERRED
IN-6 (pay-stub ↔ W-2 coverage) is bidirectional SET-COVERAGE — a borrower with two jobs SHOULD show two
employers, so LP-325's "all-agree" over-fires. IN-A's recommendation (a judgment over the gathered SETS)
needs LP-331's deferred **multi-value gather-into-judgment leg**, which does not exist. Per the ticket
(*"if (a) needs the gather leg and the leg isn't there: DEFER IN-6… do not build a new evaluator family
inside an authoring ticket"*), **IN-6 is DEFERRED** — no spec authored. It ships as its own ticket once
the multi-value gather leg lands (which also enables any judgment over a gathered set). The 13 other rules
fit existing evaluators.

### D4 — the UNSURE thresholds
Encoded only what is defensible + citable; UNSURE values get a conservative default with the signoff flag
and a loud Priya note (never left un-encoded in a way that silently blocks, and never guessed as fact):

| Rule | Encoded | Basis | Flag |
|---|---|---|---|
| IN-1 | 5% shortfall | Priya (pending — the D1 correction) | priya=false, signoff=true |
| IN-2 | 30-day recency | Fannie B3-3.1-02 default | priya=false, signoff=false (structural) — confirm window |
| IN-3 | 10% YTD tolerance | **UNSURE** — no agency value; a deliberately-loose default | priya=false, signoff=true — confirm |
| IN-4 | 30-day gap window | Fannie B3-3.1-01/02 default | priya=false, signoff=false — confirm window/6-mo history |
| IN-10/11/12 | decline/history/1084 method | Priya-validated per CSV rationale | priya=false, signoff=true |

## The tags: declarations + recipes + reuse

**Reused (18 in `fact_tags.csv`, now DECLARED):** parsed — `income.stated_monthly`,
`income.employment_start/end`, `income.pay_date`, `income.ytd_gross` (subject: document). AI (4 groups,
subject: document) — `income_amounts` (`income.type`/`documented_monthly`/`qualifying_monthly`),
`income_employer` (`income.employer_normalized`), `income_docs` (`voe_present`/`future_employment`/
`offer_letter_present`), `income_stability` (`has_2yr_history`/`is_declining`/`same_line_of_work`/
`continuance_3yr`). No re-minting; the vocabulary's meanings are kept. `occupancy.rental_support` reused
by IN-14.

**New (7 in `vocabulary_extra.yaml`):** 4 derived arithmetic tags (`income.documented_income_shortfall_pct`,
`income.ytd_annualized_shortfall_pct`, `income.max_employment_gap_days`, `income.days_since_most_recent_pay`
— all subject: loan) + 3 judgment verdict tags (`income.job_change_acceptable`,
`income.other_income_continues`, `income.rental_income_supportable`). The 4 recipes are loan-level
aggregates that abstain honestly.

**The LP-325 gather contract:** `income.employer_normalized` (IN-5) keys under the DOCUMENT subject, so
the per-borrower consistency gather works — exactly like the id.* facts.

## Which rules ACTIVATE vs wait

**NONE activated** — `ACTIVE_RULE_IDS` is unchanged (no IN rule added). All 13 are authored + evaluated
against fixtures, activated later (the LP-325/326/331 restraint), because their tags do not yet
materialize where the rules read them:
- **IN-1/2/3/4 (loan-level derived):** need the income AI/parsed tags to materialize per-document so the
  recipes can aggregate. The declarations are in place; live materialization runs when the pipeline is
  wired (Wave-2 activation).
- **IN-5 (consistency):** needs `income.employer_normalized` materialized per-document (declared).
- **IN-7/13/14 (per-borrower judgment):** their `reasoned_over` tags are declared subject: document but
  the judgment reads them per BORROWER — the `borrower_id ↔ MISMO-index` / borrower-keyed materialization
  gap (shared with ID-8). Evaluate via fixtures; do not activate.
- **IN-8/9/10/11/12 (per_document + applicability):** depend on the classifier producing the document
  types (`verification_of_employment`, `offer_letter`, `w2`, `tax_return`) and the income AI tags. Where a
  type is not produced, the rule resolves not_applicable/couldnt_check (honest), not a false green.

## The kind-vs-reality tension (reported, NOT resolved by editing the CSV)

`rule_kinds.csv` is the gate of record, so the specs match it — but three calculative rows do not read a
numeric threshold:
- **IN-10 (declining):** the CSV marks it calculative/numeric; the year-over-year computation is done by
  the AI into `income.is_declining`, so the spec is a deterministic READ of that structured fact. Honest,
  loads, but the "numeric" work lives in the AI tag, not a deterministic operand.
- **IN-11 (variable averaging):** reads `income.has_2yr_history` (enum). **OVER-FIRES** — it fires for any
  income lacking a 2-year history, not just VARIABLE income, because the operand algebra has no
  set-membership (`income.type in {bonus, overtime, commission}`). A faithful IN-11 needs either a
  set-membership operand or a judgment reframe — **a decision-to-be-made ticket**, not a CSV edit.
- **IN-12 (self-employment):** the CSV rationale names a DEDICATED calculator; `compute_self_employed_income`
  exists in `services/` but is NOT wired into `snapshot.calculations`. The spec is a MINIMAL 2-year-return
  check pending that wiring (a follow-on).

These are reported as findings; none was patched by touching the engine or the CSV.

## Was any engine Python needed? — NO (the headline)

Only recipe *registry entries* in `derived.py` (the LP-326 extension point). No evaluator, gate, generic
producer, or rule-id branch was touched. **The wave criterion HELD — the first wave to do so.**

## Guideline text drafted needing human verification

Every `guideline_text` / `guideline_reference` in the 13 specs was drafted at authoring from general
agency knowledge (Fannie B3-3.1 family) and is **HUMAN-VERIFY**: the citations (B3-3.1-02 recency,
B3-3.1-01/02 gaps, B3-3.1-08 rental, B3-3.1-09 continuance/future employment, B3-3.2 self-employment) and
every numeric default (5% / 10% / 30-day) must be confirmed by Priya/the guideline before the rules ship.
None is AI-recalled at runtime (it is transcribed data), but none is Priya-confirmed either.

## PRIYA / HUMAN-VERIFY — the full accumulated income list

| # | Item | Rule | Encoded default | Confirm |
|---|---|---|---|---|
| 1 | **Stated-vs-documented 5% shortfall** (top) | IN-1 | 5% (pending; my ticket mis-labeled it IN-3) | 5% not 10%; then flip CSV IN-1 priya_validated + the spec |
| 2 | YTD tolerance | IN-3 | **UNSURE** 10% loose default | the true tolerance |
| 3 | Pay-stub recency window | IN-2 | 30 days | exact window |
| 4 | Employment-gap window | IN-4 | 30 days (+6-mo history) | exact windows |
| 5 | Declining-income treatment | IN-10 | any decline flags | use lower year / average / decline |
| 6 | Variable averaging method | IN-11 | 2-yr history required | 24 vs 12-mo trigger; + the over-fire fix |
| 7 | Self-employment 1084 method | IN-12 | 2-yr returns | the calculator wiring + add-backs |
| 8 | Continuance horizon | IN-13/14 | 3 years | confirm |
| 9 | Rental vacancy/expense factor | IN-14 | (prose only) | 75% / Schedule-E method |
| 10 | Non-taxable gross-up | IN-1/3 | (not modeled) | whether/how to gross up |

## What LP-323-IN-C (eval) must cover

The full 13-point matrix per rule (both directions, boundaries — **cases 3/4 are finally REAL** for IN-1's
5%; **case 12 gated-derived → couldnt_check is finally in play**), tag-level golden labels, the judgment
armor, the IN-1 direction edge, the IN-5 cost property, and the DOMAIN edges (raise-between-docs, mid-year
YTD, partial-period paystub, same-field job change, community/other-income end dates, rental adjustment).
Plus the honest N/As: IN-6 (deferred), the IN-11 over-fire, the per-borrower activation gaps. -C also
inherits the calibration duty for the income AI tags (documented_monthly, qualifying_monthly, employer,
the judgment verdicts).

## THE WAVE-COST CHECK

IN-A predicted Wave 2 ≈ 3 tickets (A/B/C) + one shared activation ticket, no new evaluator/operand.
**Confirmed by this ticket:** authoring was pure DATA + recipes — the steady-state claim held. The
residual work is NOT new per-wave cost: (a) IN-6 + the multi-value gather leg (a one-time reusable
primitive, deferred), (b) the per-borrower derived producer / borrower-keyed materialization (shared with
ID-8), (c) IN-11's set-membership-or-reframe + IN-12's calculator wiring (two small rule-specific
follow-ons). None required touching the engine here.

## ADR

- **ADR (D2): income arithmetic is DERIVED TAGS, loan-level, not a calculator/operand** — sets the pattern
  for every future family's arithmetic (confidence via the tag gate; Caveat A stays deferred; per-borrower
  granularity is a producer-generalization follow-on). Worth recording in `decisions.md`.
- **D3 (IN-6 set-coverage) is a decision-to-be-made in its own ticket** (judgment-over-sets needs the
  multi-value gather leg), not decided here.
- D1/D4 are a Priya list, not an ADR.

## Cross-refs

LP-323-IN-A (the recon this executes); LP-324 (generic evaluators + operands), LP-325 (consistency +
gather contract), LP-326 (tag declarations + derived recipes — the extension point this used), LP-327/331
(judgment + borrower-keyed facts), LP-328 (typed operands + vocabulary overlay), LP-329/330 (document
applicability + absent-document expectation), LP-318 (calculators + Caveat A). Evidence:
`rule_kinds.csv`, `fact_tags.csv`, `derived.py`, `declarations.py`, `specs.py`.
