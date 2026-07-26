# LP-323-IN-C — INCOME family eval (the full case matrix + calibration)

Wave 2's eval ticket. The rules are authored (LP-323-IN-B: 13 specs as pure DATA — the first wave the
zero-engine-Python criterion held). This ticket proves they WORK — both directions, edge cases, the NEW
numeric boundaries and the case-12 abstention path — and **PINS three known-wrong behaviours honestly**.
**EVALUATE, DON'T FIX.** The diff is two test files + this doc (no app/ file changed — verified).

**Deliverables**
- `backend/tests/verification/eval/test_income_family_eval.py` — the income golden harness + the matrix
  (finding-level + tag-level + provenance + cost + armor + abstention), incl. the 3 pins, 18 cases.
- `backend/tests/verification/eval/test_income_family_calibration.py` — the income-tag calibration
  (unknown-rate + accuracy-when-concrete), keyless + a skipped live seam, 4 + 1 cases.
- This doc: the per-rule case table, the calibration, the 3 pins, the bugs, the Priya list, IN-6's
  deferral, and the wave-cost assessment.

## Harness

Mirrors LP-323-ID-C: the LP-317 harness is AS-1/txn-shaped, so this is a **dedicated income harness
beside it**, same discipline. Each rule is evaluated **through its real evaluator** (`evaluate_*`).
**NONE of the 13 rules is activated** (`ACTIVE_RULE_IDS` unchanged, verified) — each is exercised by
calling its evaluator directly (activation gates the orchestrator, not the evaluator), exactly as ID-8 and
the ID family were. **IN-6 is DEFERRED** (no spec — D3, needs LP-331's multi-value gather leg).

## Acceptance criteria

- [x] Every in-scope IN rule (the 13) has a **must-FIRE** and a **must-not-fire** case; the guard test
  (`test_every_in_scope_in_rule_has_a_must_fire_case_in_this_module`) fails loudly if a fire case drops.
- [x] **NEW THIS WAVE — real numeric boundaries** (IN-1 `5.01% → fire`, `4.99% → satisfied`; IN-2/3/4
  day/%-boundaries) and **case 12** (a derived tag abstaining → couldnt_check — the path ID could never
  test), asserted for every derived-reading rule (IN-1/2/3/4).
- [x] The three known-wrong behaviours PINNED (current behaviour asserted + documented, NOT fixed).
- [x] Judgment ARMOR (IN-7/13/14 every verdict ratification-pending); the IN-5 no-AI COST property;
  provenance (a fired/needs_review finding carries non-empty reasoning).
- [x] Calibration extended to the 11 income AI tags; keyless runs, the metric is proven not-inert, live is
  skippable.
- [x] ruff + mypy + full suite green (2170 passed, 2 skipped, 1 xfailed). **No app/ file changed.**

## THE PER-RULE CASE TABLE (rule × the 13 cases)

**P** = pass (asserted) · **N/A** = not applicable, numbered reason below · **PIN** = a pinned known-wrong.
Case 12 here = a derived/enum input abstaining/absent → couldnt_check.

| Rule | 1 fire | 2 clean | 3 over | 4 under | 5 absent | 6 unknown | 7 low-conf | 8 variance | 9 prov | 10 tag | 11 armor | 12 abstain | 13 domain |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **IN-1** shortfall (det/derived) | P | P | P 5.01% | P 4.99% | P⁶ | P⁶ | N/A¹ | N/A² | P | P | N/A³ | P | P raise→satisfied |
| **IN-2** recency (det/derived) | P | P | P 31d | P 30d | P⁶ | P⁶ | N/A¹ | N/A² | P | P | N/A³ | P | P partial-period |
| **IN-3** YTD (det/derived) | P | P | P 10.01% | P 9.99% | P⁶ | P⁶ | N/A¹ | N/A² | P | P | N/A³ | P | P mid-year start |
| **IN-4** gap (det/derived) | P | P | P 31d | P 30d | P⁶ | P⁶ | N/A¹ | N/A² | P | P | N/A³ | P | P <2 records→abstain |
| **IN-5** employer (consistency) | P | P (+no-AI) | N/A⁴ | N/A⁴ | P | P⁷ | P⁷ | P DBA | P | P | N/A³ | N/A⁵ | P legal-vs-DBA |
| **IN-7** job change (judgment) | P | P | N/A⁴ | N/A⁴ | P gated | — ⁷ | — ⁷ | — | P | P | **P** | N/A⁵ | P same-field vs unrelated |
| **IN-8** VOE (det per_doc) | P | P | N/A⁴ | N/A⁴ | P⁸ | P | P | — | P | P | N/A³ | N/A⁵ | P verbal-VOE |
| **IN-9** offer letter (det per_doc) | P | P | N/A⁴ | N/A⁴ | P NA⁹ | P | P | — | P | P | N/A³ | N/A⁵ | P start-after-note |
| **IN-10** declining (det per_doc) | P | P | N/A⁴ | N/A⁴ | P | P | P | — | P | P | N/A³ | N/A⁵ | P fires on decline |
| **IN-11** variable (det per_doc) | **PIN** | P | N/A⁴ | N/A⁴ | P | P | P | — | P | P | N/A³ | N/A⁵ | PIN over-fire |
| **IN-12** self-emp (det per_doc) | P | P | N/A⁴ | N/A⁴ | P | P | P | — | P | P | N/A³ | N/A⁵ | PIN minimal-check |
| **IN-13** continuance (judgment) | P | P | N/A⁴ | N/A⁴ | P gated | — ⁷ | — ⁷ | — | P | P | **P** | N/A⁵ | P child-support-ends |
| **IN-14** rental (judgment) | P | P | N/A⁴ | N/A⁴ | P gated | — ⁷ | — ⁷ | — | P | P | **P** | N/A⁵ | P vacancy-adjustment |
| **IN-6** coverage | — DEFERRED (D3) — no spec; asserts only `RuleSpecNotFound`. Needs LP-331's multi-value gather leg. |

**N/A reasons (stated, never silently omitted):**
1. **Low-confidence N/A for the derived rules** — a `derived` tag's confidence is `None` (a passthrough,
   LP-315 convention), so it never routes to needs_review; low-confidence lives on the AI-produced tags
   (covered on IN-5/8/9/10/11/12).
2. **Label/format variance N/A for the derived rules** — the derived tag is a canonical number; unit/format
   variance is the AI perceiver's problem (calibrated), not the rule's compare.
3. **Armor N/A** — every-verdict-ratification-pending applies only to the judgment rules (IN-7/13/14). NB:
   the ticket text lists IN-12 as a judgment; it is **deterministic** (calculative per `rule_kinds.csv`) —
   see Findings §F1.
4. **No numeric threshold** — a consistency/presence/enum/judgment rule has no over/under boundary (the
   real boundaries are IN-1/2/3/4, covered as cases 3/4).
5. **No derived/calc input** — IN-5/7/8/9/10/11/12/13/14 read tags directly; there is no abstaining derived
   input to gate. (An absent/unknown TAG is case 5/6, covered.)
6. **Absent/unknown live in the RECIPE** — IN-1/2/3/4's feeding tags absent/unknown → the derived tag
   becomes `"unknown"` (proven in LP-323-IN-B's `test_recipe_abstains_*`) → case 12 here (couldnt_check).
7. **Consistency/judgment gate** — an unknown-valued or low-conf gathered/reasoned tag → couldnt_check /
   needs_review via the shared gate (proven on IN-5 and the judgment fail-closed test).
8. **IN-8 absent = expected-absence** — no VOE document → couldnt_check (LP-330, a VOE is expected), NOT
   not_applicable (case 5 folds into the domain edge).
9. **IN-9 absent = not_applicable** — no offer-letter document → not_applicable (future employment is the
   exception, not every file has it).

**Both-directions guard:** every one of the 13 has an asserted must-FIRE case. No eval fatigue.

## Calibration (Phase 3)

11 income AI tags (the structuring outputs + the 3 judgment verdicts), reusing LP-317's
`DimensionCalibration` UNCHANGED. Keyless baseline (labels replayed → trivially perfect — a plumbing
check):

```
INCOME-FAMILY CALIBRATION — KEYLESS (labels replayed — plumbing + structure check)
dimension                          n  unknown%  acc-concrete%  flags
income.documented_monthly         10     20.0%         100.0%  ok
income.qualifying_monthly         10     20.0%         100.0%  ok
income.employer_normalized        10     20.0%         100.0%  ok
income.type                       10     20.0%         100.0%  ok
income.is_declining               10     20.0%         100.0%  ok
income.has_2yr_history            10     20.0%         100.0%  ok
income.same_line_of_work          10     20.0%         100.0%  ok
income.continuance_3yr            10     20.0%         100.0%  ok
income.job_change_acceptable      10     20.0%         100.0%  ok
income.other_income_continues     10     20.0%         100.0%  ok
income.rental_income_supportable  10     20.0%         100.0%  ok
```

**The metric is NOT inert:** two tests feed a live-shaped distribution on `income.documented_monthly` (THE
hard structuring step that feeds the shortfall recipe) and assert the flags fire — 70%-unknown →
**OVER-ABSTENTION**; 40%-concrete-wrong → **UNDER-ABSTENTION / fabrication**. **Live calibration** (the
real income reasoners over raw content, scored vs golden labels) is a **skipped seam** without a key.

## THE THREE PINNED KNOWN-WRONG BEHAVIOURS (asserted current behaviour; NOT fixed)

### PIN #1 — the #1 FALSE-GREEN: loan-level aggregate MASKS per-borrower income fraud
`produce_derived_tags` is loan-only (`derived.py` raises for `subject != "loan"`), so the income arithmetic
AGGREGATES the file's documents. **A 2-borrower file where borrower A's documented income is 40% short of
stated (the fraud signal) and borrower B's exceeds stated nets to a ~0 aggregate shortfall → IN-1
SATISFIED** — masking exactly the income-fraud case IN-1 exists to catch. Asserted:
`_income_documented_shortfall` on the 2-borrower fixture → `"0"` → IN-1 satisfied, while borrower A alone →
`"0.4"` → would fire.
- **Assessment:** a real false-green, the #1 consequence of the per-borrower derived-producer gap
  (LP-323-IN-B D2). Not a rule bug — an aggregation-granularity gap.
- **Fix ticket:** the **per-borrower derived producer + `borrower_id ↔ MISMO-index` / borrower-keyed
  materialization** (shared with ID-8's activation). Until it lands, IN-1/2/3/4 are file-level screens, not
  per-borrower checks — must not be trusted to catch a single borrower's inflated income.

### PIN #2 — IN-11 OVER-FIRES on non-variable income (false-positive)
IN-11 reads `income.has_2yr_history` and fires for ANY income lacking a 2-year history, because the operand
algebra has no set-membership (`income.type in {bonus, overtime, commission}`). Asserted: salaried W-2
income with `<2yr` history → FIRES, which is WRONG (the 2-year rule is for VARIABLE income); the true
positive (variable income <2yr) is indistinguishable from it.
- **Fix ticket:** a **set-membership operand** (`income.type in {…}`) OR an **IN-11 judgment reframe**. A
  decision-to-be-made in its own ticket.

### PIN #3 — IN-12 is a MINIMAL 2-year-return check (under-coverage)
`compute_self_employed_income` exists in `services/` but is NOT wired into `snapshot.calculations`, so IN-12
is a minimal history check. Asserted: self-employment lacking a 2-year history → fires; a 2-year history
present → SATISFIED **even with declining net / missing add-backs** (K-1/1099/P&L). The real Form-1084
cash-flow analysis is not modeled.
- **Fix ticket:** **wire the self-employment calculator** into `snapshot.calculations` and read its cash-flow
  output (a calc operand — the existing operand handles it, no new primitive).

## FINDINGS — reported, NOT fixed

No rule/engine BUG surfaced beyond the three pins (which are known design gaps, documented in IN-B). One
ticket-text discrepancy caught:

**F1 — IN-12 is deterministic, not a judgment (a ticket-text error).** The LP-323-IN-C brief lists IN-12
as a judgment and includes it in "IN-7/12/13/14 armor". But `rule_kinds.csv` marks IN-12 **calculative**
(→ a deterministic block), and the authored spec is deterministic. So the ARMOR (every-verdict-
ratification-pending) applies to **IN-7/13/14 only**; IN-12 has no armor case (N/A³). Verified against the
gate of record, not the brief — the same class of correction as IN-A's IN-1/IN-3 finding.

## IN-6 — DEFERRED (recorded, not evaluated)

IN-6 (pay-stub ↔ W-2 coverage) has no spec (LP-323-IN-B D3: its bidirectional set-coverage shape needs
LP-331's multi-value gather leg). The eval asserts only `load_rule_spec("IN-6")` raises `RuleSpecNotFound`.
Its cases will be written when the gather leg lands and IN-6 is authored.

## INCOME PRIYA / HUMAN-VERIFY (the full accumulated list, from IN-B)

| # | Item | Rule | Encoded default | Confirm |
|---|---|---|---|---|
| 1 | Stated-vs-documented 5% shortfall (top) | IN-1 | 5% (pending; the brief mislabeled it IN-3) | 5% not 10%; then flip CSV IN-1 priya_validated + the spec |
| 2 | YTD tolerance | IN-3 | **UNSURE** 10% loose default | the true tolerance |
| 3 | Pay-stub recency window | IN-2 | 30 days | exact window |
| 4 | Employment-gap window | IN-4 | 30 days (+6-mo history) | exact windows |
| 5 | Declining-income treatment | IN-10 | any decline flags | use lower year / average / decline |
| 6 | Variable averaging method | IN-11 | 2-yr history required | 24 vs 12-mo trigger; + the over-fire fix (PIN #2) |
| 7 | Self-employment 1084 method | IN-12 | 2-yr returns | the calculator wiring + add-backs (PIN #3) |
| 8 | Continuance horizon | IN-13/14 | 3 years | confirm |
| 9 | Rental vacancy/expense factor | IN-14 | (prose only) | 75% / Schedule-E method |
| 10 | Non-taxable gross-up | IN-1/3 | (not modeled) | whether/how to gross up |

Every `guideline_text` in the 13 specs was drafted at authoring and is HUMAN-VERIFY (transcribed data,
never AI-recalled at runtime, but not Priya-confirmed).

## Did any app/ file change? — NO

`git status` is exactly two new test files + this doc. **No `app/` file, no spec, no tag, no engine logic
was touched.** The harness was not bent; the three pins assert the CURRENT (wrong) behaviour and are
reported as fix tickets. Matches the ID-C discipline.

## ADR

**None** — eval only, no architecture changed. The pins' fixes (per-borrower derived producer; IN-11
set-membership vs reframe; IN-12 calculator wiring) are decisions-to-be-made in their own tickets, not
decided here.

## THE WAVE-COST ASSESSMENT

**What Wave 2 (Income) actually cost — 3 tickets:** IN-A (recon) + IN-B (authoring) + IN-C (eval).
**The steady-state claim HELD, confirmed from the eval's side.**

**Did evaluating reveal engine gaps that authoring didn't?** No new ones. The eval CONFIRMED the gaps IN-B
already reported (the loan-only derived producer → PIN #1; IN-11's missing set-membership → PIN #2; IN-12's
unwired calculator → PIN #3) by turning them into failing-in-the-real-world scenarios. Crucially, **the
eval touched no app/ code** — the same clean two-files-and-a-doc shape as ID-C. The zero-engine-Python
criterion held across the whole wave, authoring AND eval.

**The residual — all one-time-shared or per-rule, none per-wave:**
- The **per-borrower derived producer / borrower-keyed materialization** — SHARED with ID-8's activation;
  fixes PIN #1 and unblocks per-borrower income + citizenship at once. The single highest-value follow-on.
- The **multi-value gather leg** — one-time reusable; authors IN-6 and any judgment-over-a-gathered-set.
- IN-11 set-membership operand (or reframe) + IN-12 calculator wiring — two small per-rule follow-ons.

**Forecast for Waves 3–10 (is ~3/wave holding? — YES, with named risks):**
- **Assets (AS-2..AS-12):** mostly consistency + deterministic over existing asset tags → ~3 tickets. Risk:
  the same per-borrower/per-account aggregation granularity (PIN #1's cousin) if any asset rule is
  per-borrower — but the shared borrower-keyed producer will already exist.
- **DTI:** reads the DTI calculator (the `calc` operand already generalizes — proven by AS-1) → likely ~3,
  no new primitive. Risk: multi-scenario DTI (with/without a retained property) may want a small operand.
- **Title / insurance / condo (small families):** document-type applicability (LP-329) + presence +
  expected-absence (LP-330) already cover the shapes → ~2–3 each, mostly authoring.
- **Credit / property:** **BLOCKED on blocker-document extractors** (credit report / appraisal parsing) —
  their tags cannot materialize until those extractors exist. Authoring + eval can proceed against
  fixtures, but activation waits — flag as an infra dependency, not a per-wave authoring cost.
- **The one recurring new-primitive risk:** each family that introduces genuinely NEW arithmetic beyond a
  ratio/date (e.g. amortization schedules, LTV tiers) may need a derived recipe — but that is a registry
  entry, not engine Python (the ADR-273 pattern holds).

**Bottom line:** ~3 tickets/wave is holding. Wave 1 (Identity) front-loaded the five reusable primitives;
Wave 2 (Income) spent them and added zero engine code. The biggest lever for Waves 3+ is landing the
shared **borrower-keyed materialization** (PIN #1 / ID-8), after which per-borrower rules across every
family activate for free.

## Cross-refs

LP-323-IN-A (recon + domain edges), LP-323-IN-B (the authored rules + D1-D4 + the three known-wrongs),
LP-323-ID-C (the eval precedent this mirrors); LP-317 (harness + DimensionCalibration), LP-325 (consistency
cost property), LP-326 (derived abstention), LP-327/319 (judgment armor), LP-329/330 (applicability +
absent-document), LP-318 (Caveat A — confirmed avoided). §3D/§8.
