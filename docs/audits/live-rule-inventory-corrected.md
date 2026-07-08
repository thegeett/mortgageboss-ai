# Corrected live-rule inventory + Wave 1 buildability (read-only audit)

**Status:** complete · **Type:** read-only audit · **Epic:** Phase 3.5 / Epic B
**Date:** 2026-07-08 · **Triggered by:** LP-123R discovering AS-8 is not live (the sequencing
assumption was unreliable).

## Why this exists

We were sequencing rule tickets off an assumption about which rules are "already live" (used as
pipeline-validation anchors). LP-123R claimed **AS-8 (bank-statement continuity)** was live; the code
says it is **not**. This audit establishes the REAL ground truth from the code — trusting no prior
"live" claim (including the LP-115 audit and my own) without re-verifying against `cross_source/rules.py`,
the `verification_rules` seed/table, and the fact-builders.

## Executive summary — "live" has two distinct senses

There is exactly **ONE live finding-producing path**: the cross-source pass
(`api/verification.py` → `tasks/cross_source.py::run_cross_source` → `evaluate_cross_source`).

| Sense of "live" | Count | What it means |
|---|---|---|
| **Fires today** (produces findings on real data) | **5** | Its input facts are populated by the LIVE deterministic fact-builder (`cross_source_deterministic.py` / `facts.py`). |
| **Wired + enabled** (`CrossSourceRule`, `enabled=true`) | **18** | In code + in `verification_rules`, but 13 are fact-starved → never fire on the live path today. |
| **Dormant threshold engine** (conv./FHA/samples) | **107** | No caller in any request/task path. Its threshold *data* feeds calculators; its finding-emission never runs. |
| **AI cross-source pass** | 1 generative pass | Fires; emits canonical types minus any a deterministic rule owns this run. |

**Only AS-5 is a confirmed-live rule that is ALSO validated + already built in the new engine.** Note
that `validated=true` in the seed does NOT imply "fires today": **AS-1** and **IN-1** are `validated=true`
yet dormant on the live path (fact-starved).

## 1. Authoritative live (wired) rule set — the 18 `xsrc.*` cross-source rules

Source: `app/verification/cross_source/rules.py:401-603`. "Fires today" per the LP-115 audit,
re-verified against the fact-builder.

| rule_id | playbook_id | checks | check fn | fires today? |
|---|---|---|---|---|
| `xsrc.identity.name_consistency` | ID-1 | borrower name differs across sources | `_consistency_check("names")` | ✅ **fires** |
| `xsrc.address.dl_equals_subject` | — | driver's-license address == subject property | `_check_dl_equals_subject` | ✅ **fires** |
| `xsrc.income.employer_name_consistency` | IN-5 | documented employer not among stated | `_check_employer_name_consistency` | ✅ **fires** ⚠️ known FP bug (LP-115 §5) |
| `xsrc.income.employer_count_matches_items` | — | stated employer count ≠ income-item count | `_check_employer_count` | ✅ **fires** |
| `xsrc.asset.gift_without_letter` | AS-5 | stated gift with no gift-letter doc | `_check_gift_without_letter` | ✅ **fires** (built = rule #1) |
| `xsrc.identity.ssn_consistency` | ID-2 | SSN differs across documents (RED) | `_consistency_check("ssns")` | ❌ dormant (`ssns` never populated) |
| `xsrc.identity.dob_consistency` | ID-3 | DOB differs across documents | `_consistency_check("dobs")` | ❌ dormant |
| `xsrc.address.current_address_consistency` | ID-4 | current/mailing address differs | `_consistency_check("current_addresses")` | ❌ dormant |
| `xsrc.address.employer_equals_subject` | — | employer address == subject property | `_check_employer_equals_subject` | ❌ dormant |
| `xsrc.income.stated_vs_documented` | IN-1 | stated vs documented income > 10% | `_check_income_variance` | ❌ dormant (`documented_income_monthly` never populated) — **validated=true** |
| `xsrc.liability.undisclosed_debt` | CR-1 | credit-report liability not on app (+APPLY) | `_check_undisclosed_debt` | ❌ dormant |
| `xsrc.liability.stated_not_on_report` | — | stated liability absent from report | `_check_stated_not_on_report` | ❌ dormant |
| `xsrc.asset.stated_missing_document` | — | stated asset lacks a supporting doc | `_check_stated_asset_missing_doc` | ❌ dormant |
| `xsrc.asset.large_deposit_unsourced` | AS-1 | large deposit unsourced across sources | `_check_large_deposit_unsourced` | ❌ dormant (`unsourced_large_deposits` never populated) — **validated=true** |
| `xsrc.terms.price_vs_contract` | PC-2 | stated price ≠ contract price (purchase-only) | `_check_price_vs_contract` | ❌ dormant |
| `xsrc.terms.loan_vs_documented` | — | stated loan amount ≠ documented terms | `_check_loan_vs_documented` | ❌ dormant |
| `xsrc.property.subject_address_consistency` | — | subject address differs across docs | `_check_subject_address_consistency` | ❌ dormant |
| `xsrc.property.occupancy_vs_evidence` | OC-1 | stated occupancy conflicts with evidence | `_check_occupancy_vs_evidence` | ❌ dormant |

**5 fire; 13 are wired-but-fact-starved.** No bank-statement continuity rule exists anywhere (confirmed:
not in `cross_source/rules.py`, not in the FHA/program modules).

### `verification_rules` table/seed state

- **18 rows** `enabled=true` — the `xsrc.*` rules above (whether or not they fire on the live path).
- **122 rows** `enabled=false` — `pb.*` playbook-only placeholders, `applicability=null`, `evaluator=null`
  (not yet built). **AS-8 is one of these: `pb.as-8`, enabled=false, applicability=null.**
- The **107-rule threshold engine** (conventional/FHA/sample registries) is a separate structure, not the
  `verification_rules` table's live set, and has no caller.

## 2. Corrected "not actually live" list (what prior notes mislabeled)

| Called "live" by | Reality |
|---|---|
| **AS-8** bank-statement continuity | **No code counterpart at all** — `pb.as-8`, never implemented. (LP-115 already listed it under "no code counterpart today", alongside AS-2 EMD sourcing and AS-7 NSF/overdraft.) |
| **AS-1** large-deposit (validated=true) | Wired + validated but **dormant** — `unsourced_large_deposits` never populated by the live fact-builder. |
| **IN-1** income variance (validated=true) | Wired + validated but **dormant** — `documented_income_monthly` never populated. |
| **CR-1 / PC-2 / OC-1** and 10 others | Wired (`enabled=true`) but **dormant** (fact-starved). "Enabled" ≠ "fires." |
| The **FHA / threshold-engine** rules | **Dormant** — no caller. Not a live rule set. |

**The reliable anchors that actually fire today are exactly 5:** `name_consistency`,
`dl_equals_subject`, `employer_name_consistency` (buggy), `employer_count_matches_items`,
`gift_without_letter`.

## 3. New-engine buildability — the reframe that matters

The **new** data-driven engine (LP-121 runner) reads the **LP-118.6 fact snapshot**, NOT the old
`CrossSourceFacts` fact-builder. So a rule that is "dormant" on the live path (fact-starved in
`facts.py`) can still be **buildable in the new engine** if the *snapshot* carries its data. Key snapshot
facts confirmed available:

- **Computed block IS populated** — `_build_computed` (`builder.py:348`) calls the real calculators:
  `build_ltv_calculation`, `build_dti_calculation`, `compute_loan_mi`, `build_reserves_view`. So
  `computed.{ltv, cltv, hcltv, front_end_dti, back_end_dti, mi_monthly, reserves_months}` are available
  (when inputs exist). **This unblocks the calc rules (DT/PR/MI/reserves) on the DATA axis — their gap is
  the LIMIT/threshold (Priya/program), not data.**
- **Documents** — `snapshot.documents: list[DocumentRef]`, each with `document_type` + a flat
  `fields: dict[str,str]` of every typed extraction field (so bank-statement `beginning_balance`,
  `ending_balance`, `statement_period_start/end` are present as strings).
- **Transactions** — `snapshot.transactions: list[TransactionFacts]` (date, amount, description, type)
  materialized from bank-statement extractions.
- **Borrowers** — `borrowers[].income_items`, `borrowers[].employers`, names, addresses.
- **Assets / liabilities** — `assets[]` (incl. `is_gift`, `value`), `liabilities[]`.
- **File / property** — `file.{program, loan_purpose, refinance_type}`, `property.{occupancy, property_type}`.

## 4. Wave 1 buildability table

"Live anchor?" = does a firing live rule exist to match (real parity). "Data present?" = the LP-118.6
snapshot carries what its evaluator would read. "Domain gap?" = a threshold/limit/spec Priya must confirm.

| Rule | Live anchor? | Data in snapshot? | Domain gap (Priya)? | Buildable now? |
|---|---|---|---|---|
| **AS-5** gift-without-letter | ✅ fires | ✅ assets `is_gift` + docs | none | **BUILT (rule #1)** |
| **employer-count** (`employer_count_matches_items`) | ✅ **fires** | ✅ `borrowers[].employers` + `income_items` | **none** — exact count compare | ✅ **YES — clean #2** |
| name_consistency (ID-1) | ✅ fires | ✅ borrower names + doc fields | name normalization (suffix/middle) | ~ needs fuzzy spec |
| dl_equals_subject | ✅ fires | ~ DL address in `DocumentRef.fields`? + subject addr | address normalization | ~ needs match spec |
| employer_name (IN-5) | ✅ fires ⚠️ | ✅ | fuzzy employer match + **known FP bug** | ~ fix + fuzzy spec |
| **AS-8** continuity | ❌ none | ✅ balances/periods (strings in `fields`) | continuity tolerance + 1-stmt handling | ❌ needs domain spec |
| **DT-1** DTI vs limit | ❌ (threshold engine dormant) | ✅ `computed.back_end_dti` | **DTI limit** (program/Priya) | data-ready; needs limit |
| **PR-1** LTV/CLTV/HCLTV limits | ❌ | ✅ `computed.ltv/cltv/hcltv` | **LTV limits** (program/Priya) | data-ready; needs limit |
| **MI-1** PMI required (Conv >80% LTV) | ❌ | ✅ `computed.ltv` + `mi_monthly` | 80% is a GSE standard (likely low-Priya); confirm | ~ near-clean |
| **AS-4** reserves adequacy | ❌ | ✅ `computed.reserves_months` | **required reserves months** (program/Priya) | data-ready; needs limit |
| **DT-3** MI in DTI | ❌ | ✅ `computed.mi_monthly` + dti | how MI factors into DTI (spec) | needs spec |
| **AS-6** account ownership | ❌ | ~ `fields.account_holder_name` + borrower names | DET-FUZZY name match (like IN-5) | needs fuzzy spec |
| **AS-2** EMD sourcing | ❌ | ~ purchase-agreement EMD + bank txns | sourcing spec | needs spec |
| **CL-1** rate-lock expiration | ❌ | ❌ rate-lock/closing-date not surfaced | — | data gap first |

## 5. Settled technical facts (for exact-match triggers)

- **documents-`entity_exists` idiom — SETTLED / works.** `snapshot.documents` is a `list[DocumentRef]`;
  each element exposes `document_type: str | None`. A trigger
  `entity_exists(collection="documents", field="document_type", op="eq", value="<type>")` resolves in the
  engine exactly like AS-5's `assets` trigger. AS-8 would have been the first document-triggered rule;
  the idiom is confirmed for all future document-triggered rules.
- **Real `document_type` strings** (use these EXACT values, from `app/documents/catalog.py`): `pay_stub`,
  `w2`, `1099`, `tax_return`, `voe`, `profit_and_loss`, `bank_statement`, `investment_account`,
  `retirement_account`, `gift_letter`, `verification_of_deposit`, `brokerage_statement`,
  `gift_donor_bank_statement`, `earnest_money_receipt`, `sale_of_asset_proof`, `purchase_agreement`,
  `appraisal`, `title_commitment`, `flood_certification`, `payoff_statement`, `credit_report`,
  `closing_disclosure`, `loan_estimate`, `rate_lock_agreement`, `drivers_license`, `passport`,
  `uniform_residential_loan_application`, … (89 types total; the ones above are the asset/terms/credit
  ones Wave 1 needs). Note `bank_statement` is the literal string (not "bank statement" / "bankStatement").
- **Real scope value strings** (StrEnum `.value`, for `scope` triggers):
  - `program` (LoanProgram): `conventional`, `fha`
  - `loan_purpose` (LoanPurpose): `purchase`, `refinance`
  - `refinance_type` (RefinanceType): `rate_term`, `cash_out`  *(co-emit `loan_purpose:["refinance"]` — round-3 FIX 6A)*
  - `occupancy` (OccupancyType): `primary_residence`, `second_home`, `investment`
  - `property_type` (PropertyType): `single_family`, `condo`, `townhouse`, `multi_family`, `manufactured`, `other`

## 6. Recommended clean rule #2 — `xsrc.income.employer_count_matches_items`

> **Status (off-list tracking): REPRODUCED / BUILT in the new engine — LP-124R (2026-07-08).** The live
> rule was reproduced (file-level count parity; `validated=true`, no threshold). Round-5 made the zero-on-
> one-side case an intentional stricter-than-live FINDING (Geet's decision). This rule is off the 124
> authored list; recording it here is its coverage tracking.
> **Double-firing gate:** it fires in BOTH the live path and the new engine, so it is listed in
> `runner.LIVE_PATH_OWNED_RULE_IDS` (with `gift_without_letter`) — a persist layer must skip these until
> LP-161 retires the live path.

**Why it's the right #2 (and the anchor AS-8 wasn't):**

1. **It actually fires today** — one of the 5 live rules, so there is a REAL live verdict to match
   (genuine parity anchor, exactly what AS-8 lacked).
2. **Its data is in the snapshot** — `borrowers[].employers` + `borrowers[].income_items` (no
   fact-builder work needed).
3. **No domain-spec gap** — it's an EXACT count comparison (stated employer count vs income-item count),
   not a threshold, tolerance, or fuzzy match. Nothing for Priya to confirm → can seed `validated=true`
   under the LP-122R criterion if it reproduces the live verdict.
4. **It exercises new pattern surface** — a *count/aggregate across a nested collection* (richer than
   AS-5's single boolean), which stresses the per-rule pattern usefully without a domain dependency.

Runner-up: **MI-1** (PMI required for Conv >80% LTV) — data-ready (`computed.ltv` + `mi_monthly`) and its
80% threshold is a GSE standard rather than a Priya judgement; a good first *calc-based* rule once #2
lands, pending a quick confirm that 80% needs no overlay.

**Caveat on employer-count:** confirm the live rule's exact semantics (file-level vs per-borrower count;
how it handles zero income items) so the new evaluator matches it — that parity check is the whole point.

## 7. Scope

Read-only. Nothing was built, migrated, seeded, or changed. AS-8 was **not** built (the LP-123R build was
halted at this discovery). This report is the input to correcting the rule-sequencing plan; the plan
itself (no `vertical_ticket_plan.md` file was found in the repo — the Wave 1 list was taken from the
LP-123R ticket + prior notes) is unchanged here.
