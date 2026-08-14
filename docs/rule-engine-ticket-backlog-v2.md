# Rule engine — ticket backlog v2 (post-census)

_2026-08-11. **Supersedes `rule-engine-ticket-backlog.md`.** Rewritten against LP-476's findings.
LP-476 is DONE; LP-477 and LP-478 carry forward unchanged in intent but LP-478 is now much larger._

**Goal: 37 → 115 rules.** Nothing outside the rule engine is in scope.

---

## What the census changed

| the old backlog assumed | the census found |
|---|---|
| ~30 rules blocked on 6 missing extractors | **all six extractors exist.** 1 rule is genuinely extractor-gated |
| Tags ≈ 26 rules | **tag production blocks 54 of 83** — nearly ⅔ of all remaining work |
| TI-4 is a "nearest miss to write-now" | `judgments_indicator` is **None on all 4** title commitments |
| 8 credit rules from the tradelines consumer | **7** — CR-11 has **0 public_records rows** |
| Documents are a Stage-4 concern | **26 rules blocked on corpus** — the second-largest lever |
| `tag_dependencies.csv` is an empty stub to fill | **generated, test-pinned empty by design**, and the wrong relation anyway |

**The verdict roll-up (83 unwritten rules):**

| verdict | count |
|---|---|
| blocked-on-tag-production | **54** |
| blocked-on-CALIBRATION (Priya, as first blocker) | 10 |
| blocked-on-vocabulary | 7 |
| never-write (VAC/RED, inherited from LP-451) | 5 |
| blocked-on-DOCUMENTS (n=0) | 5 |
| blocked-on-producer-resolution | 1 (AS-3) |
| **WRITABLE-NOW** | **1** (DT-4, deterministic branch only) |

⚠️ **10 need Priya as their FIRST blocker; 66 of 83 touch Priya eventually** (51 carry an
uncalibrated load-bearing AI tag once produced, 14 need a threshold sign-off). Do not let "only 10"
become a planning fiction.

**Standing on every ticket:** Phase A stops and reports · the documents are the gate of record ·
regression check on neighbouring types · report cost before any model call · commit locally, never
push · write `docs/tickets/LP-XXX.md` on completion.

**Standing method (from LP-476):** ⚠️ **LP-451's field names are shorthand, not literal** — three
resolve to different real keys (`aus_dti`→`aus_dti_ratio`, `aus_ltv`→`aus_ltv_ratio`,
`repairs_required`→`repairs_required_indicator`). Any ticket generating a field list from LP-451
**must resolve every name against the real key set first.** The insurance spec also disagrees with
its own extractor on three names, so specs alone are not sufficient either.

---

# DONE

## ✅ LP-476 — The rule census
Six of six extractors exist. 83 rules verified. Phase C correctly refused. See `docs/tickets/LP-476.md`.

---

# LONG-LEAD TRACK — both start now

## LP-477 — Agency/overlay shape: the decision memo
**Type:** Design · **Cost:** $0 · **Blocks:** AS-3, CR-7, CR-9, DT-1, PC-4, PR-1

- Unchanged by the census — its six gates hold regardless of anything LP-476 found.
- Survey what each gated rule needs to express (CR-9: 1% Fannie vs 0.5% Freddie/FHA · DT-1: 50% DU vs
  36–45% manual vs an FHA matrix · plus AS-3, PC-4, PR-1, CR-7).
- Read the existing shell: `verification/overlays/schema.py`, `starter.py`, `samples.py`.
- Draft 2–3 candidate shapes, each with its migration cost for the 37 live rules on single-threshold
  `activation_bars.yaml`.
- Must satisfy Priya's ruling: **store all agency rules and select the applicable one; never the
  strictest; a lender's conservative choice is an explicit `LENDER_OVERLAY`; when the agency is
  unselected, return comparative results.**
- ⚠️ **A memo and an ADR, not an implementation.** Geet chooses the shape.

## LP-478 — The document ask ⚠️ **now the second-largest lever in the plan**
**Type:** Coordination · **Cost:** $0 · **Blocks:** 26 rules

- **26 rules are blocked on corpus, not code.** This is no longer a Stage-4 side task.
- **n=0, cannot be measured at all:** flood certification (IH-5), flood insurance policy (IH-6), MI
  certificate (MI-2/3/5), gift deposits (AS-5's trigger).
- **n≤2, present but unmeasurable:** credit report **n=2** (10 rules), AUS/DU **n=1** (AU-1/2/3),
  appraisal **n=2** (PR-2/4/5/6), URLA **n=2** (PE-2).
- ⚠️ **Both credit reports appear to be the same bureau format.** n=2 proves the plumbing, not
  generalisation. State this in the ask — the need is for *varied* reports, not merely more.
- **Batch with the ADR-332 real-file ask** (FR-1/2/3/6, CR-4, OC-1, RE-1, PC-1, TI-1, TI-2, AU-1) —
  same request, same lead time, one conversation.
- Include the de-identification requirement and the GLBA constraint: real client files must not enter
  environments without proper safeguards.
- **Done when:** a one-page ask Priya can act on without a follow-up, naming document types and counts.

---

# STAGE 2 — LISTS

The tradelines list is the one whose row fields are **uniformly populated** — `is_disputed` 35/35,
`balance` 35/35, `monthly_payment` 34/35. LP-451's build order is confirmed correct here.

## LP-479 — `stable_row_id` on tradelines + the free-proof rule
**Depends on:** LP-476 · **Cost:** $0 (reads stored data)

- Flip `stable_row_id` on the tradelines `ListSpec`. Only `bank_statement.transactions` declares it today.
- Write the first rule against `credit.tradeline_count` — declared, materialized, read by **no spec**.
- Verify against the two stored reports: 21 and 14 rows, 34/35 carrying `monthly_payment`, zero
  unparseable, correct `_UNKNOWN` abstain when absent.
- Confirm a file with no credit report yields `couldnt_check` (present-but-unclear), **never 0**.
- ⚠️ **Frame as "proves the list→tag→rule path on 2 documents of one bureau format."** Not readiness.

## LP-480 — The per-liability enumerator
**Depends on:** LP-479 · **Cost:** $0

- Add `per_liability` to `rule_engine/enumerators.py:_ENUMERATORS` (five exist: `per_deposit`, `loan`,
  `per_borrower`, `per_document`, `per_account`).
- Model on `_per_account` (LP-336): **fail-closed composite identity**, surfacing unresolvable members
  as their own subjects rather than dropping or guess-merging.
- Liabilities live in two places — MISMO file-level `liability.{n}.*` and credit-report tradeline rows.
  Reconcile both without double-counting.
- Copy `_per_deposit`'s four properties: stable content id as subject (never a position); absent tags
  yield subjects with empty maps (gate reports `couldnt_check` per row rather than the rule vanishing);
  returns `(id, tags)` only, no domain logic; `subject_key_fields` gives the finding a readable identity.
- Register the drift guard (`KNOWN_*` frozenset + assert) so a typo fails at import.

## LP-481 — The tradelines consumer and its 7 rules
**Depends on:** LP-480 · **Cost:** low

- Ship **CR-1, CR-3, CR-5, CR-6, CR-8, CR-10, CR-12** — seven, not eight.
- ⚠️ **CR-11 is OUT.** `public_records` has **0 rows across both credit reports**. The list is declared
  and captured; there is no data in it. Moves to LP-478 (documents).
- ⚠️ **CR-9 is held** — agency-gated on LP-477. Building it here means building it twice.
- CR-4 is *fed* by this but stays calibration-gated → Stage 4.
- Regression check: **AS-1, AS-2, AS-12, IN-12** ride the legacy `transactions`/`schedule_c`
  attributes, which coexist with `lists`. Confirm all four byte-unchanged.
- **Done when:** 7 rules ship and the 37 live rules produce identical verdicts.

---

# THE CORRECTNESS GATE

## LP-482 — Wire the accuracy layer to the verdict layer
⚠️ **Blocks: any new rule shipping `auto`** — and Stage 3 roughly doubles the parsed-tag surface.

- Four live rules take a **direct operand** from a field with a confirmed wrong value: **IH-1** (auto —
  `replacement_cost_or_coinsurance_basis`, its only gated tag, fills 46.7%, doc 104 wrong) · **AS-2**
  (auto — `txn.amount`, doc 049 holds the running balance) · **ID-5** (auto — DL `expiration_date`,
  docs 146/294 hallucinated) · **ID-3** (ratify — DL `date_of_birth`).
- Structural cause: the parsed path sets `confidence=None`, so `gate.py` ignores those tags in the
  confidence minimum. The gate's armor covers absence, unknown-ness, contradiction and low confidence —
  a confidently-wrong parsed value defeats all four by construction.
- LP-474's checks run at the **extraction** layer and are not wired to the verdict layer.
- ⚠️ The census adds a third ledger-exposed rule set: **IH-2, IH-8** also read document-104 fields.
- **Phase A — STOPS AND REPORTS:** two options costed. (a) Wire LP-474 so a flagged extraction degrades
  the verdict to `needs_review`. (b) Demote IH-1, AS-2, ID-5 from `auto` to `ratify`. Recommend one.

---

# STAGE 3 — TAGS ⚠️ **the plan's centre of gravity: 54 of 83**

Sequenced by leverage. ⚠️ **New tags go in `vocabulary_extra.yaml`** — `fact_tags.csv` is generated
from `docs/snapshot-fact-tags.xlsx` and hand edits are lost on regeneration. Every tag must pass
`test_parsed_declaration_fields.py` (the LP-450 guard — a pytest, not load-time, deliberately).

## LP-483 — The one writable-now rule: DT-4
- The census's single WRITABLE-NOW hit. `property_tax_bill.assessed_value` fills **5/5**.
- **Deterministic branch only** — the new-construction branch is AI and is not in scope here.
- Smallest possible proof of the parsed-tag path before the larger families.
- ⚠️ **Replaces the old LP-483.** TI-4 is not a nearest miss — see LP-489.

## LP-484 — The 7 vocabulary-blocked rules
- Blocked at hop 1 (tag undeclared) rather than hop 2 — the shortest chain in the census.
- **CR-13, FR-3, IH-7, IH-8, MI-4, OC-3** and one further, per the census table.
- FR-3's `purchase_agreement.side_agreements_referenced` fills 2/5; IH-8's wind/hail pair 7/15.
- Backfill `rule_tags.csv` rows for those with neither spec nor tag rows as they are touched.

## LP-485 — Insurance cohort ⚠️ **the only statistically usable type (n=15)**
- **IH-2** (`mortgagee_name` 14/15, `mortgagee_clause_raw` 14/15).
- Every other cohort in the plan is n≤5. This is the only place a fill rate is a real measurement.
- ⚠️ Carries accuracy-ledger exposure (doc 104) — sequence after LP-482.
- ⚠️ **IH-4 is never-write** (RED, dup of DT-5). Do not build it.

## LP-486 — Contract cohort
- **PC-4** (`seller_credit_amount` 3/5) ⚠️ *agency-gated, held for LP-477* · **PC-5**
  (`earnest_money_amount` 4/5) · **PC-8** (`personal_property_included` 4/5).
- ⚠️ **PC-6 and PC-9 are NOT here.** Their lists fill but the row field each needs does not —
  `addendum_date` **0/12**, `deadline_date` **6/26**. Both are extractor-prompt work → LP-489.

## LP-487 — Property/appraisal cohort
- **PR-2** (`appraised_value` 2/2) · **PR-4** (`appraisal_completion_condition` 2/2) · **PR-5**
  (`condition_rating` 2/2, `repairs_required_indicator` 2/2) · **PR-6** (`appraisal_effective_date` 2/2).
- ⚠️ **All corpus-thin (n=2).** Ship them, but every one carries a thin-n caveat on its spec until
  LP-478 delivers more appraisals. `fha_condition_deficiencies` is **0/2** — PR-5's FHA branch is
  LP-489 work, not this ticket.
- ⚠️ **PR-1 held** — agency-gated.

## LP-488 — Title cohort (the fields that DO fill)
- **TI-1** (`vested_owner_name` 4/4) · **TI-2** (`legal_description` 4/4) · **TI-6**
  (`chain_of_title` 3/4 docs).
- ⚠️ TI-3, TI-4, TI-5's second field are **excluded** → LP-489.

## LP-489 — ⚠️ NEW: the extractor-prompt gap _(category (e))_
**The census's most important new finding.** Field present, extractor present, corpus present — and
the field never populates. Not a tag problem; a prompt problem.

- **TI-3** `open_liens_indicator` **0/4** · **TI-4** `judgments_indicator` **0/4** · **TI-5**
  `vesting_marital_recital` **0/4**.
- **PC-6** `addenda[addendum_date]` **0/12** · **PC-9** `contingencies[deadline_date]` **6/26**.
- **PR-5** `fha_condition_deficiencies` **0/2** · **AU-2** `aus_required_conditions[is_prior_to_close]`
  **2/22** · **TI-3** `schedule_b_items[is_satisfied]` **2/19**.
- ⚠️ **Prompt changes go in the `.txt`, under that prompt's own naming** — specs and prompts diverge.
  89 of 109 prompts are untouched STARTER placeholders; the 19 hand-tuned ones are the types that
  performed at parity.
- ⚠️ **A spec edit does not reach a shipped prompt** — the generator runs diff-mode for shipped extractors.
- Each field re-verified against the source PDFs before any prompt change: is the datum on the page at all?
- **Done when:** each field either fills, or is documented as absent from the document class.

## LP-490 — The remaining tag-production bulk
- The balance of the 54, sequenced by shared-tag leverage per LP-451's build order.
- Split into sub-tickets as the cohorts emerge; do not attempt as one.

---

# STAGE 4 — CALIBRATION

⚠️ **The only stage that costs API credit** — scoring re-runs the reasoner per worksheet. **Batch the
sessions: one beats five.** ~20 min per 30 rows (LP-420).

## LP-491 — Build the calibration worksheets in advance
- All worksheets prepared before Priya sits down, so her time is labelling, not waiting.
- `guard_pii_safe_out_dir` fail-closed guard keeps any real-PII worksheet out of the repo.
- ⚠️ Scope to **66 rules**, not 10 — 51 need a bar once produced, 14 need a threshold sign-off.

## LP-492 — AS-4: the reserve-eligibility ruling
- ⚠️ **Not a bar-height problem.** `stmt.is_reserve_eligible` measures **0% (0/5)** — the model calls
  standard checking/savings reserve-eligible where Priya labels "no."
- Sequence: **ruling → re-prompt → re-score.** A threshold change fixes nothing.

## LP-493 — The 10 first-blocker calibration rules + the inert specs
- The census's 10 blocked-on-CALIBRATION rules, plus AS-5, AS-7, CR-4, IN-13, OC-1.
- AS-5 needs a file with a **real gift deposit** (n=0 on the trigger). CR-4, OC-1 are ADR-332
  real-file cases. All depend on LP-478 delivering.
- IN-14 needs a producer first (`occupancy.rental_support` has no `tag_production.yaml` entry).

## LP-494 — The judgmental lane and AI cross-source
- ~29 judgmental rules plus the cross-source discovery lane.
- ⚠️ **Lineage under-states judgmental rules** (LP-476 assumption 4) — PE-4's lineage lists only
  `program.type` while the rule is an `ai_judgment`. Do not size these from `rule_tags.csv`.
- Every threshold ships as a **grounded starter** at reduced confidence until Priya confirms it.

---

# STAGE 5 — TAIL

## LP-495 — The agency-gated six
- **AS-3, CR-7, CR-9, DT-1, PC-4, PR-1** — built once, on the shape chosen in LP-477.
- AS-3 additionally needs closing-cost extraction from the LE/CD; its `_cash_to_close_shortfall`
  recipe is an unconditional-abstain stub today.

## LP-496 — ⚠️ NEW: the tag DAG
- `tag_dependencies.csv` **cannot be filled by hand.** It is generated by
  `app/scripts/generate_fact_tags.py` from the vocabulary xlsx, and pinned empty by three tests
  (`test_generated_csvs_are_committed_and_current`, `test_projection_counts_match_files`,
  `test_desired_state_shape`). The empty DAG is deliberate — LP-311 Phase 0.
- Needs: a `depends_on` column in the xlsx (or a generator change), plus updates to the three tests.
- ⚠️ **The header is the wrong relation anyway** — `tag_id,depends_on_tag_id` is tag→tag; "which rules
  unblock together" is rule→tag, already in `rule_tags.csv`. Decide what the file is *for* first.
- **19 tag→tag edges** were extracted by LP-476 as starting data — a lower bound (most recipes read
  extraction fields, not tags).

## LP-497 — AU-4: run-state persistence
- The **only** genuinely extractor-gated rule, and it is not an extractor problem: AU-4 needs
  **prior-run history** to compare current data against last-run values. No run-state store exists.
- Scope the store before building the rule.

## LP-498 — MI certificate extractor
- The only genuinely missing document extractor. No module, no spec, no catalog type.
- ⚠️ **n=0 in the corpus — it cannot be validated even once built.** Gated on LP-478 delivering
  certificates. Unblocks MI-2, MI-3, MI-5.

## LP-499 — Re-derive the five VAC/RED vacuity proofs
- **DT-2, DT-3, DT-5, CO-2, IH-4** are permanent write-offs against a 115 target, inherited from
  LP-451 without the vacuity proof being re-derived (LP-476 assumption 5, honestly flagged).
- ~1 hour of operand tracing. If any one is wrong, it is a rule deliberately never built on a proof
  nobody checked.
- **Do this before the 115 count is called final.**

## LP-500 — Spec drift cleanup
- Five schema specs carry `"existing_extractor": null` while the modules exist and are registered —
  credit_report, aus_findings, appraisal, flood_certification, title_commitment. **This is the probable
  cause of the work breakdown's "six missing extractors" error.**
- The insurance spec disagrees with its own extractor on three names: spec `insurance_carrier` /
  `insured_property_address` / `dwelling_coverage_a` vs emitted `carrier_name` / `property_address` /
  `coverage_amount`. The spec even attributes IH-1/IH-7 to `dwelling_coverage_a`.
- No live rule is broken. This is documentation integrity — and the specs are the stated source of
  truth for generating field lists, so it will mislead the next reader exactly as it misled the last.

---

## Held out of scope

Not rule-engine work. Do not pick up until 115 is reached: the splitter (066, 069, 167, 196, 204, 271) ·
image preprocessing (ADR-365) · the 89 untuned prompts *(except where LP-489 needs them)* ·
`loan_number_masked` storing the unmasked value · PII inside captured list rows (routed by prompt only,
36 of 119 prompts) · the UI · Phase 4.5 conditions.

⚠️ The last two are **live PII issues on a GLBA-covered platform.** Held for scope discipline, not
because they are safe.
