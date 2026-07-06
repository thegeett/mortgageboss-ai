# LP-115 — Live Verification Rule Inventory (read-only audit)

**Status:** complete · **Type:** read-only spike · **Epic:** Phase 3.5 / Epic A
**Date:** 2026-07-06 · **Author:** LP-115 audit

> This audit replaces reconstructed-from-memory rule counts with facts read from the
> code as it stands on branch `phase3`. **No code was changed.** Every claim below cites
> the file/line evidence it rests on.

---

## 1. Summary — the headline number

**The verification pipeline has exactly ONE live finding-producing path: the cross-source
pass.** Within it, the true count of rules that fire today is:

- **5 deterministic cross-source rules** that can actually produce a finding on real data
  (their input facts are populated), out of **18 wired** `CrossSourceRule`s, **plus**
- **1 AI cross-source pass** (a single generative generator that can emit up to ~10
  canonical finding types, minus any type a deterministic rule already owns this run).

Everything else that *looks* like a rule is **dormant**:

- **13 of the 18** deterministic cross-source rules are wired and reachable but
  **fact-starved** — the `CrossSourceFacts` fields they read are never populated by the
  fact-builder, so they can never fire today.
- The **threshold engine** — **107 registry rules** (50 conventional + 49 FHA + 8
  samples/regulatory) — is **dormant**: nothing in any request or task path calls it. Its
  *threshold data* is reused by the calculators, but its finding-emission never runs.

**Correction to prior planning:** the "~30 exists" reconstruction was wrong in both
directions. There are **18** deterministic cross-source rules in code (not ~30), only **5**
of which fire today; and the **107-rule threshold engine is not a live rule set at all** —
it emits zero findings in production.

| Category | Count | Fires today? |
|---|---|---|
| Deterministic cross-source rules — facts populated | **5** | ✅ yes |
| Deterministic cross-source rules — fact-starved | 13 | ❌ dormant |
| AI cross-source pass (generative) | 1 pass | ✅ yes |
| Threshold-engine rules (conv./fha./samples) | 107 | ❌ dormant (no caller) |
| Calculator-surfaced checks (DTI/LTV/MI/reserves/max-loan/self-emp) | 6 | ➖ not findings (separate category) |
| Playbook rules with no code (AS-/IN-/CR-/… scheme) | ~130 planned | ❌ not-built |

---

## 2. Orchestration map — the actual run path from trigger to findings

```
POST /loan-files/{id}/verification/run          app/api/verification.py:134  run_verification()
  │  (NOTE: same function name as the dormant threshold service — different code entirely)
  ├─ compute_input_fingerprint(context)          api/verification.py:154
  │    └─ if unchanged & !force → return CACHED run, NO AI call        api/verification.py:157-163
  ├─ create_verification_run(...) → RUNNING        api/verification.py:165
  └─ _enqueue_cross_source() → run_cross_source_pass.delay(...)        api/verification.py:124-127,170
        │
        ▼  (Celery worker)
   app/tasks/cross_source.py:32  run_cross_source_pass()
        └─ _run() → run_cross_source(db, loan_file, run)              tasks/cross_source.py:50
              │
              ▼  app/services/cross_source.py:97  run_cross_source()
              ├─ assemble_cross_source_context(db, loan_file)          services/cross_source.py:124
              ├─ reason_cross_source(context_json)  ── AI CALL ──►      ai/cross_source.py:144
              ├─ build_cross_source_facts(...)                          services/cross_source.py:140
              ├─ run_cross_source_deterministic(...) ─► DET RULES ─►    services/cross_source_deterministic.py:61
              │     returns (det_red, det_yellow, fired_types)          → evaluate_cross_source()  cross_source/engine.py:59
              ├─ for raw in AI findings: if raw.type in fired_types: DEFER   services/cross_source.py:150-163
              ├─ reconcile_findings(existing_ai, fresh_ai, external)    services/cross_source.py:169
              ├─ _generate_novel_guidance(added)                        services/cross_source.py:180
              ├─ populate_finding_source_documents(...)                 services/cross_source.py:196
              └─ run COMPLETED; findings persisted (origin=deterministic_rule / ai_cross_source)
```

**Two finding generators exist on this path** and only these two:
1. `run_cross_source_deterministic` → `evaluate_cross_source` → the 18 `CrossSourceRule`s
   (`origin=DETERMINISTIC_RULE`, `confidence=1.0`, templated wording).
2. `reason_cross_source` → the AI pass (`origin=ai_cross_source`), deduped/deferred against
   the deterministic types that fired this run.

The `GET …/verification` status endpoint (`api/verification.py`) only **reads + filters**
already-stored findings by the aggression cutoff — it never runs a generator.

---

## 3. The three-state inventory

State definitions used:
- **fires-today** — wired into the run path **and** its input data is actually populated,
  so it can produce a live finding on real data.
- **scaffolded-dormant** — exists in code but never produces a finding in production, either
  because nothing calls its engine (threshold engine) or because its input fact is never
  populated (fact-starved cross-source rules).
- **not-built** — referenced in the plan/playbook but has no code.

Conservative-classification rule (per the ticket): a rule is only **fires-today** if it can
be shown to fire; otherwise it is **scaffolded-dormant**.

### 3a. Deterministic cross-source rules (`app/verification/cross_source/rules.py`)

All 18 are registered in `CROSS_SOURCE_RULES` (rules.py:587) and reachable via
`evaluate_cross_source`. The discriminator is whether `build_cross_source_facts`
(`services/cross_source_deterministic.py:181-262`) populates the fact the rule's `check`
reads. The fact-builder sets **only** these fields: `names`, `subject_property_address`,
`dl_address`, `stated_income_monthly`, `stated_employers`, `documented_employers`,
`stated_employer_count`, `income_item_count`, `stated_liabilities`, `gift_amount`,
`gift_letter_present` (cross_source_deterministic.py:250-262). Every other
`CrossSourceFacts` field keeps its empty default (facts.py:62-97) — confirmed by grep: those
fields are assigned **only** in `facts.py` (the default) and **read** only in `rules.py`,
never populated anywhere else.

| rule_id | canonical_type | what it checks | severity | state | playbook id | evidence |
|---|---|---|---|---|---|---|
| `xsrc.identity.name_consistency` | identity_discrepancy | borrower name differs across app + doc name fields | YELLOW | **fires-today** | ID-1/ID-2 (identity, inferred) | reads `names`; populated at cross_source_deterministic.py:200-211 |
| `xsrc.address.dl_equals_subject` | property_address_discrepancy | driver's-license address == subject property (occupancy/ID red flag) | YELLOW | **fires-today** | ID-* / OC-3 (inferred) | reads `dl_address`+`subject_property_address`; both populated (cs_det.py:203-217, 197) |
| `xsrc.income.employer_name_consistency` | employer_mismatch | documented employer not among stated employers | YELLOW | **fires-today** ⚠️ known FP bug | **IN-5** (explicit, phase3_5_1.md:206) | reads `stated_employers`+`documented_employers`; populated (cs_det.py:219-223,236) — see §5 |
| `xsrc.income.employer_count_matches_items` | employer_mismatch | stated employer count ≠ income-item count | YELLOW | **fires-today** | IN-* (inferred) | reads `stated_employer_count`+`income_item_count`; populated (cs_det.py:257-258) |
| `xsrc.asset.gift_without_letter` | gift_discrepancy | stated gift with no gift-letter document | YELLOW | **fires-today** | AS-* / gift (inferred) | reads `gift_amount`+`gift_letter_present`; populated (cs_det.py:248, `_gift_facts`) |
| `xsrc.identity.ssn_consistency` | identity_discrepancy | SSN differs across documents | RED | scaffolded-dormant | ID-* | reads `ssns` — **never populated** (facts.py:63 default only) |
| `xsrc.identity.dob_consistency` | identity_discrepancy | DOB differs across documents | YELLOW | scaffolded-dormant | ID-* | reads `dobs` — never populated (facts.py:64) |
| `xsrc.address.current_address_consistency` | identity_discrepancy | current/mailing address differs across docs | YELLOW | scaffolded-dormant | ID-* | reads `current_addresses` — never populated (facts.py:65) |
| `xsrc.address.employer_equals_subject` | property_address_discrepancy | employer address == subject property | YELLOW | scaffolded-dormant | — | reads `employer_addresses` — never populated (facts.py:70) |
| `xsrc.income.stated_vs_documented` | income_variance | stated vs documented income > threshold (10%) | YELLOW | scaffolded-dormant | IN-3 (YTD) | reads `documented_income_monthly` — never populated (facts.py:74) → returns [] |
| `xsrc.liability.undisclosed_debt` | liability_discrepancy | credit-report liability not on application (+APPLY spec) | YELLOW | scaffolded-dormant | **CR-1** (phase3_5_1.md:217) | reads `credit_report_liabilities` — never populated (facts.py:81) |
| `xsrc.liability.stated_not_on_report` | liability_discrepancy | stated liability absent from credit report | YELLOW | scaffolded-dormant | CR-* | early-returns when `credit_report_liabilities` empty (rules.py:274) |
| `xsrc.asset.stated_missing_document` | missing_documentation | stated asset lacks a supporting doc | YELLOW | scaffolded-dormant | AS-* | reads `stated_assets_missing_doc` — never populated (facts.py:85) |
| `xsrc.asset.large_deposit_unsourced` | asset_discrepancy | large deposit unsourced across sources | YELLOW | scaffolded-dormant | **AS-1** (phase3_5_1.md:193) | reads `unsourced_large_deposits` — never populated (facts.py:86) |
| `xsrc.terms.price_vs_contract` | terms_discrepancy | stated price ≠ contract price (purchase-only) | YELLOW | scaffolded-dormant | **PR-2** (phase3_5_1.md:229) | reads `stated_purchase_price`+`contract_purchase_price` — never populated (facts.py:91-92) |
| `xsrc.terms.loan_vs_documented` | terms_discrepancy | stated loan amount ≠ documented terms | YELLOW | scaffolded-dormant | — | reads `stated_loan_amount`+`documented_loan_amount` — never populated (facts.py:93-94) |
| `xsrc.property.subject_address_consistency` | property_address_discrepancy | subject address differs across docs | YELLOW | scaffolded-dormant | PR-* | reads `subject_addresses_across_docs` — never populated (facts.py:95) |
| `xsrc.property.occupancy_vs_evidence` | occupancy_discrepancy | stated occupancy conflicts with evidence | YELLOW | scaffolded-dormant | OC-3 (inferred) | reads `stated_occupancy`+`occupancy_evidence` — never populated (facts.py:96-97) |

> **Nuance:** the 13 fact-starved rules are dormant *today* but are one fact-builder change
> away from firing — unlike the threshold engine, which needs a caller. They are honestly
> "promotion-pending" (Tier-2), documented as such at cross_source_deterministic.py:15-18.
> They are still classified **scaffolded-dormant** because they produce zero findings now.

### 3b. AI cross-source pass (`app/ai/cross_source.py`)

| generator | what it produces | state | evidence |
|---|---|---|---|
| `reason_cross_source` | one AI reasoning pass over the assembled stated-vs-verified context; emits `CrossSourceRawFinding[]` across the taxonomy below | **fires-today** | called at services/cross_source.py:123-126; findings persisted `origin=ai_cross_source` |

AI taxonomy (prompt `CROSS_SOURCE_SYSTEM_PROMPT`, ai/cross_source.py:76-93; categories from
`_TYPE_CATEGORY`, services/cross_source.py:83-94): `income_variance`, `employer_mismatch`,
`gift_discrepancy`, `asset_discrepancy`, `liability_discrepancy`,
`property_address_discrepancy`, `co_borrower_discrepancy`, `identity_discrepancy`,
`missing_documentation`, `other`. See §4 for the graduation/dedup relationship.

### 3c. Threshold engine (`app/services/verification_engine.py`, `app/verification/*`)

**Whole engine = scaffolded-dormant (no production caller — see §6).** The rule *data* is
reused by the calculators (§7). Rules are composed by `default_registry().resolve(program,
lender)` (registry.py:87-128) and evaluated by `evaluate()` (engine.py:59) — but only from
`services/verification_engine.py:67 run_verification`, which nothing in `app/` imports.

| group | source | count | RED | state |
|---|---|---|---|---|
| Conventional program `CONVENTIONAL_RULES` | rules/conventional/ | 50 | 5 | scaffolded-dormant |
| FHA program `FHA_RULES` | rules/fha/ | 49 | 10 | scaffolded-dormant |
| Sample conv./fha./regulatory `SAMPLE_RULES` | rules/samples.py | 8 | — | scaffolded-dormant (some thresholds read by calculators) |
| **registry total** | `default_registry()` | **107** | 15 | scaffolded-dormant |

Representative conventional rules: `conv.credit.min_score_delivery_floor` (score ≥620, RED),
`conv.dti.back_end_max_manual` (≤45%, RED, manual-UW gate), `conv.assets.large_deposit_source`
(≤$10k), `conv.property.appraisal_age` (≤4mo), `conv.docs.purchase_agreement_present`
(purpose=PURCHASE). Representative FHA rules: `fha.credit.mdcs_eligibility_floor` (≥500, RED),
`fha.dti.back_end_max_with_factors` (≤50%, RED), `fha.mip.ufmip_present` (RED),
`fha.property.mpr_bedroom_egress` (RED), `fha.doc.fha_appraisal_present` (RED). Full 99-rule
program enumeration is in the sub-agent trace; the **state is identical for every one of them:
scaffolded-dormant** (the engine that would emit them is never called). Sample-bank
thresholds consumed by calculators: `conv.dti.back_end_max`, `conv.ltv.purchase_max`,
`conv.ltv.cash_out_max`, `fha.dti.back_end_max`, `fha.ltv.purchase_max`, `fha.ltv.cash_out_max`
(rules/samples.py).

### 3d. Not-built (playbook rules with no code)

The ~130-rule playbook (`AS-/IN-/CR-/PR-/DT-/IH-/MI-/PE-/AU-/TI-/CO-/OC-/RE-` scheme,
enumerated in `docs/phases/phase3_5_1.md:193-360`) is a **plan**, not code. Examples with
no code counterpart today: `AS-2` EMD sourcing, `AS-7` NSF/overdraft, `AS-8` chaining,
`CR-2` HELOC-in-HCLTV, `CR-3` paid-to-qualify, `CR-4..13`, `AU-1..4` (AUS/DU),
`TI-1..6` (title), `IH-1..6` (insurance/hazard), `DT-4/5`, `IN-13/14`, `PR-4/5/6/7`,
`CO-1..5` (condo), `RE-1`. There is **no committed `verification_rule_playbook.xlsx`** in the
repo (`find . -iname '*playbook*'` and `-iname '*.xlsx'` both empty) and **no code-level
playbook-ID mapping** (`grep -rin playbook backend/app` empty; no `playbook_id` field on any
rule). The mapping exists only as future audit work (phase3_5_1.md:25).

---

## 4. AI cross-source pass — graduation / dedup relationship

- The deterministic pass runs **first** and returns `fired_types` — the set of
  `canonical_type`s whose rule actually fired **this run** (cross_source_deterministic.py:90,
  returned as `frozenset` at :95).
- The AI defers per-run: `for raw in result.findings: if raw.type in fired_types: continue`
  (services/cross_source.py:150-163). An AI finding is dropped **only** when a deterministic
  rule fired that same type on this run — dynamic, not a static blocklist.
- The static owned set `OWNED_CANONICAL_TYPES` (rules.py:612) = the 10 deterministic
  canonical types: `identity_discrepancy`, `property_address_discrepancy`, `income_variance`,
  `employer_mismatch`, `liability_discrepancy`, `missing_documentation`, `asset_discrepancy`,
  `gift_discrepancy`, `terms_discrepancy`, `occupancy_discrepancy`.
- **AI types that can never be suppressed** (no deterministic rule owns them):
  **`co_borrower_discrepancy`** and **`other`** — the genuine-discovery bucket.
- Practical consequence today: because only 5 deterministic rules can fire, most owned types
  (`terms_discrepancy`, `occupancy_discrepancy`, `liability_discrepancy`, `asset_discrepancy`,
  `income_variance` when documented income absent, etc.) are **never in `fired_types`**, so the
  AI is effectively the sole producer for those discrepancy classes right now.
- A second dedup layer reconciles surviving AI findings against live AI findings and dedups
  against non-AI identities (`reconcile_findings(..., external_identities=...)`,
  services/cross_source.py:169-173); deterministic findings are deduped against but never
  dropped (`_non_ai_identities`).
- The AI pass does **not** run on every trigger: an unchanged input fingerprint returns the
  cached run with no AI call unless `force=true` (api/verification.py:157-163).

---

## 5. Employer-consistency rule — deep dive (input for LP-120)

This is the reference **DET-FUZZY** case (the "Novant vs Novant Health" false positive on
loan file **LF-6T3N**, phase3_5_1.md:190 AC).

**Location.** Two pieces:
- Check: `_check_employer_name_consistency` — `app/verification/cross_source/rules.py:208-224`.
- Rule row: `XSRC_INCOME_EMPLOYER_NAME` (`rule_id="xsrc.income.employer_name_consistency"`,
  `canonical_type="employer_mismatch"`, `category=INCOME`, `severity=YELLOW`) — rules.py:468-475.
- Facts populated by: `build_cross_source_facts` (`stated_employers` from
  `borrower.employers[].name`, cross_source_deterministic.py:236; `documented_employers` from
  each document's `employer_name`/`employer` field, cross_source_deterministic.py:219-223).

**Matching logic (rules.py:208-224):**
```python
stated = {_norm(e) for e in facts.stated_employers if e}
for emp in facts.documented_employers:
    if emp and _norm(emp) not in stated:   # exact set-membership after _norm
        out.append(CrossSourceMatch(subject_key=f"employer_name:{_norm(emp)}",
                                     fields={"employer": emp}, document_value=emp))
```
- `_norm` (rules.py:105-107) = `lowercase → strip → collapse internal whitespace`. **Nothing
  else** — no corporate-suffix stripping (Inc/LLC/Health/Medical Group), no token-subset or
  containment matching, no fuzzy distance.
- Fires when a documented employer's normalized string is **not exactly equal** to any stated
  employer's normalized string.

**The bug.** Stated `"Novant"` → `"novant"`; documented `"Novant Health"` → `"novant health"`.
`"novant health" ∉ {"novant"}` → **the rule fires a false-positive finding**. Any legitimate
DBA / legal-name / suffix variation (`"NOVANT MEDICAL GROUP LLC"`, `"Novant Health, Inc."`)
triggers it. This is the identity-false-positive that LP-120 replaces with `cross_source_match`
(corporate-suffix canonicalization + conservative containment; clean match → high confidence,
shared-token-not-subset → low-confidence "possible variation — verify", never a false 100%).

**Confidence (the "100%" part).** The finding is written with `confidence=DETERMINISTIC_CONFIDENCE`
which is the **global constant `1.0`** (`app/verification/confidence.py:27`), set in
`_to_finding` (cross_source_deterministic.py:148). So the false positive is asserted at **full
confidence** — there is no per-rule / match-quality confidence today. LP-120's AC "replace the
global `DETERMINISTIC_CONFIDENCE = 1.0` with per-rule `confidence_mode`" targets exactly this.

**Dedup behavior.** `subject_key = f"employer_name:{_norm(emp)}"` — keyed on the **normalized
documented-employer name**. The check emits one `CrossSourceMatch` per entry in
`documented_employers`, which is built **per document** (one employer field per doc,
cross_source_deterministic.py:205-223). So:
- The raw check is **per documented-employer-occurrence** (effectively per document that names
  an employer).
- Two documents naming the same normalized employer collapse to **one** stored finding, because
  identical `subject_key`s dedup within-run (LP-93) and reconcile by normalized identity
  (LP-93/94) — see reconcile at cross_source_deterministic.py:93.
- Net: effectively **one finding per distinct normalized documented-employer name**, but the
  dedup is a downstream side effect of identity collapse, **not** an explicit `_distinct`
  de-dup in the check itself. LP-120's AC "Dedup employer findings by `_distinct` (one per
  employer, not per document)" makes this explicit and moves it into the evaluator — worth
  noting the current behavior already lands one-per-employer for identical names, but does NOT
  group near-variant names (which is the same gap as the matching bug).

---

## 6. Threshold-engine verdict — DORMANT, with the caller-search evidence

**Verdict: the threshold engine's finding-emission path is DORMANT. It has no production
caller.** The hypothesis is **confirmed**.

Caller search (grep over `app/`, excluding tests and `__pycache__`):

- **`app.services.verification_engine` importers:** none in `app/`. The only non-test
  references are **docstrings** — `registry.py:21`, `facts.py:14`, `engine.py:13`. Every real
  import is a **test** (`tests/services/test_verification_engine.py:27`,
  `tests/integration/test_refinance_e2e.py:41`, the rule tests using `build_file_facts`, etc.).
- **`app.verification.engine.evaluate` importers:** only `services/verification_engine.py:53`
  imports it and calls it at `:99`. Since nothing imports `services/verification_engine`, that
  chain is never entered in production. All other importers are tests.
- **Name-collision trap (NOT a caller):** `app/api/verification.py:134` defines its **own**
  `async def run_verification` (the POST route). It does **not** call the threshold service —
  it enqueues `run_cross_source_pass` (api/verification.py:124-127, 170). Same name, entirely
  different code. This is likely the source of the prior mis-reconstruction: the route named
  `run_verification` was assumed to run the `verification_engine.run_verification`; it does not.

Conclusion: no route, task, or service invokes `services.verification_engine.run_verification`
or `verification.engine.evaluate`. The 107 threshold rules emit **zero** findings today.

---

## 7. Calculator-surfaced checks (separate category — not findings)

DTI/LTV/MI/reserves/max-loan/self-employed surface via **on-demand calculator endpoints**,
never as `Finding` rows. They are neither fires-today rules nor dormant rules.

| calculator | computes | pure module | API |
|---|---|---|---|
| DTI | front/back-end DTI | services/dti.py | `GET/PUT …/dti` (api/dti.py) |
| LTV | LTV / CLTV / HCLTV | services/ltv.py | `GET/PUT …/ltv` (api/ltv.py) |
| mortgage_insurance | PMI vs FHA UFMIP+MIP+duration | verification/mortgage_insurance.py | `…/calculators/mortgage_insurance` |
| self_employed | Form-1084 qualifying income | verification/self_employed.py | `…/calculators/self_employed` |
| reserves | eligible vs required reserve months | verification/reserves.py | `…/calculators/reserves` |
| max_loan | binding of DTI/LTV/program limits | verification/max_loan.py | `…/calculators/max_loan` |

Evidence they write no findings: `grep "Finding(" ` over the six math modules + calculators
service returns nothing; the only findings touch is `_findings()` (calculators.py:137-139),
which **reads** open-finding counts via `open_in_scope_findings` and returns a count/boolean.
Persistence is limited to `CalculatorOverride` rows + activity-log entries. Router
`app/api/calculators.py` returns `CalculatorView` (headline + inputs + transparent steps +
methodology), validated against `CALCULATORS = ("mortgage_insurance","self_employed",
"reserves","max_loan")`. **The calculators reuse the dormant engine's threshold *data*** (they
read `rule.condition.value` via `default_registry().resolve(...)`, e.g. services/dti.py:332-347,
services/ltv.py:252, services/mi.py:71, calculators.py:458-467) — the rule model is live as a
*limits lookup* even though the engine's *finding emission* is dormant.

---

## 8. Dormant-engine fate — options + recommendation (decision deferred to LP-123)

The dormant threshold engine is a **false-coverage trap**: 107 authored, tested rules that
look like coverage but fire nothing. Leaving it as-is is the worst option — it invites exactly
the reconstructed-count error this audit corrects.

**Option A — Wire it into the runner.** Build the missing facts (`build_file_facts` already
exists but is fact-limited like the cross-source side) and call `evaluate()` from a live
task/endpoint, routing its `EngineFinding`s through the shared `_to_finding` /
dedup(LP-86) / reconcile(LP-93/94) / provenance(LP-114.1) pipeline.
- Pros: unlocks 99 program rules (single-source threshold checks: credit score, DTI, doc age,
  MIP, MPR) that have no cross-source equivalent; reuses real, tested logic.
- Cons: none of the thresholds are Priya-validated (over-flagging risk); the fact-builder gap
  is large; it duplicates the model that LP-118 makes data-driven.

**Option B — Retire it.** Delete/park the engine, keep the rule *data* the calculators need,
and re-express any worth-keeping thresholds as registry rows under the LP-118 data-driven
engine.
- Pros: removes the false-coverage trap; aligns with the LP-118..123 direction (rules become
  data rows, not code classes); one engine, not two.
- Cons: loses the authored program-rule logic unless it is ported; the port is real work.

**Recommendation (advisory — decision is LP-123):** **retire the threshold engine as a
separate code engine, porting its still-wanted single-source checks into the LP-118
registry** as data rows with `confidence_mode` + editable `params`, each gated behind Priya
validation before going live. This avoids maintaining two engines, kills the false-coverage
trap, and lets the genuinely-useful single-source checks (credit-score floors, DTI ceilings,
document-age, FHA MIP/MPR) re-enter through the same runner and confidence machinery as the
cross-source rules. Keep the calculators' threshold-data dependency intact during the port
(they read `rule.condition.value`, not the engine). **Do not leave it wired-but-silent.**

---

## 9. Bugs / oddities noticed (noted, NOT fixed — read-only)

1. **Employer FP at 100% confidence** (§5) — the LP-120 reference case. `xsrc.income.employer_name_consistency`
   exact-matches after whitespace/case normalization only; any suffix/DBA variation fires a
   false positive at `DETERMINISTIC_CONFIDENCE = 1.0`.
2. **False-coverage trap** — the 107-rule threshold engine (§6) exists, is tested, and never
   runs. High risk of future mis-estimation; §8 addresses it.
3. **Fact-starved cross-source rules** — 13 of 18 deterministic rules (§3a) are wired but can
   never fire because `build_cross_source_facts` never populates their facts. They look like
   coverage in the rule list but are inert. A completeness view keyed on the rule table would
   over-count live coverage 3.6×.
4. **Duplicated `run_verification` name** (§6) — the API route and the dormant service share a
   function name, which plausibly seeded the earlier incorrect reconstruction. Renaming one
   (e.g. the route to `trigger_verification_run`) would remove the trap; noted only.
5. **`xsrc.income.employer_name_consistency` category is INCOME but is only a name check** —
   the "count" sibling (`employer_count_matches_items`) shares the `employer_mismatch`
   canonical type, so if both fire the AI defers on `employer_mismatch` for both — expected,
   noted for completeness.
6. **Playbook is uncommitted** — `verification_rule_playbook.xlsx` is referenced across the
   plan but is not in the repo; the AS-/IN-/CR- IDs live only in `docs/phases/phase3_5_1.md`.
   Any "map to playbook ID" work (LP-116+) needs the file checked in first.

---

## Appendix — evidence file map

| area | primary files |
|---|---|
| Run trigger + status | `app/api/verification.py` |
| Live task | `app/tasks/cross_source.py` |
| Cross-source orchestration | `app/services/cross_source.py` |
| Deterministic service (facts + emit + dedup) | `app/services/cross_source_deterministic.py` |
| Deterministic rules (the 18) | `app/verification/cross_source/rules.py` |
| Deterministic facts snapshot | `app/verification/cross_source/facts.py` |
| Deterministic evaluate loop | `app/verification/cross_source/engine.py` |
| AI pass | `app/ai/cross_source.py` |
| Threshold engine (dormant) | `app/services/verification_engine.py`, `app/verification/engine.py`, `app/verification/registry.py`, `app/verification/facts.py`, `app/verification/rules/**` |
| Confidence constant | `app/verification/confidence.py:27` |
| Calculators | `app/services/calculators.py`, `app/verification/{dti,ltv,mortgage_insurance,reserves,max_loan,self_employed}.py`, `app/api/calculators.py` |
| Plan / playbook IDs | `docs/phases/phase3_5_1.md` |
