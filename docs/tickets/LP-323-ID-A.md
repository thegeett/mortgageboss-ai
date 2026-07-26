# LP-323-ID-A — Identity wave recon + generalization gate + plan (READ-ONLY)

**Status:** Recon complete. **No code written.** Deliverable: this report only.
**Scope:** the IDENTITY family, ID-1…ID-10. **Cross-ref:** §3A/§3D/§8/§9; LP-311 (rule kinds),
LP-313/314 (Stage A/B), LP-315 (gate + thin rule), LP-316/319/321/322 (findings/judgment/orchestrator/reconcile).

---

## 0. THE GENERALIZATION GATE — **VERDICT: NO. THIS WAVE IS BLOCKED.**

**Can the ID family run through a GENERIC evaluator from specs alone? NO.** Do not plan around it by
copying `as1.py`. A generalization ticket must land first.

### What is AS-1/OC-2-SPECIFIC (per-rule modules — the 130-files trajectory if copied)

- **`rule_engine/engine.py:54` `evaluate_as1_rule`** hardcodes `load_rule_spec("AS-1")` (line 65),
  the subject universe `all_transactions(snapshot)` (line 74), AS-1's threshold-prose regex
  (`_threshold_multiplier`, reads `reference_values.large_deposit_threshold`), AS-1's operand Y
  (`_qualifying_income` → the DTI calc), and calls `evaluate_as1`. It is a **single-rule dispatcher**,
  not a generic evaluator (its own docstring: "Today it dispatches only AS-1").
- **`rule_engine/as1.py` `evaluate_as1`** hardcodes the load-bearing tag set (`TAG_IS_MONEY_IN/AMOUNT/
  HAS_SOURCE/SOURCE_STRENGTH`), the applicability (`is_money_in == "in"`), and the fire arithmetic.
- **`rule_engine/oc2.py` `evaluate_oc2`** is the SECOND per-rule module: OC-2's tag set, `LOAN_SUBJECT`,
  and the judgment prompt are all hardcoded.
- **Dispatch is hardcoded** in `services/verification_run.py:201-203` — it literally calls
  `evaluate_as1_rule(snapshot)` then `evaluate_oc2(snapshot, …)`. **No rule registry, no generic loop.**
- **The `RuleSpec` schema itself is AS-1-shaped** (`rules/specs.py:81` `ReferenceValues` has a single
  `large_deposit_threshold: str`; `subject_enumeration` is a prose string). Its docstrings say
  "Provisional (AS-1-shaped) — **LP-308 generalizes**." **LP-308 was never done** (no
  `docs/tickets/LP-308.md`; only `AS-1.yaml` exists in `rules/specs/`). A spec today cannot *express*
  an ID rule — there is no machine-readable subject enumeration, no declared load-bearing tags, no
  comparison/condition field, and the only reference-value slot is AS-1-named.

### What IS already generic + reusable (build the evaluators ON these)

- **`rule_engine/gate.py:46` `evaluate_gate`** — the fail-closed gate is fully generic (load-bearing
  tag map + floor + contradiction → `GateResult`). Reusable by every rule as-is.
- **`rules/schema.py:269` `satisfies(condition, observed)` + `Operator` (LE/LT/GE/GT/EQ/NE) +
  `Condition`** — the deterministic comparison primitive. Reusable for numeric/date/exact checks.
- **`result.py` `RuleEvaluation`**, LP-316 persist/reconcile, LP-319's judgment armor (mandatory
  ratification), LP-317's eval harness — all rule-agnostic infrastructure, reusable.

### What the generalization ticket must build (before ANY ID rule authoring)

1. **A generalized, machine-readable spec schema** (the deferred LP-308): declared `subject_enumeration`
   (an executable enumerator key, not prose), declared `load_bearing_tags` (+ the gated subset),
   a declared comparison (`Condition`/`Operator`) for deterministic rules, and generically-keyed
   `reference_values` (not `large_deposit_threshold`).
2. **A generic DETERMINISTIC evaluator** (spec-driven: enumerate subjects → build the load-bearing tag
   map → `evaluate_gate` → `satisfies`). AS-1 should be re-expressed as data on top of it (proof it
   generalizes without regressing).
3. **A generic JUDGMENT evaluator** (the OC-2 armor as a reusable engine: spec-declared prompt + the
   reasoned-over structural tags + mandatory ratification), OC-2 re-expressed on it.
4. **A cross-source CONSISTENCY primitive (NEW).** AS-1 is per-transaction; OC-2 is loan-level. The ID
   family is dominantly **cross-source** (compare a borrower fact across DL / 1003 / paystub / title /
   credit report). Neither existing shape covers "gather tag T for borrower B across all sources,
   compare (exact, then AI-fuzzy)". This primitive does not exist and is load-bearing for ID-1/2/3/4/7.
5. **A rule registry** so the orchestrator dispatches the rule set generically instead of two hardcoded
   calls.

### SECOND blocker (independent of the evaluator): the id.* tags are NOT MATERIALIZED

Every ID tag exists in the *vocabulary* (`fact_tags.csv`) but **no producer materializes any `id.*`
tag** — Stage A/B produce only `txn.*` today (the same "vocabulary-not-materialized" gap already noted
for OC-2's occupancy tags in LP-319 and the calculator input tags in LP-318). Even with a generic
evaluator, every ID rule would `couldnt_check` (inputs absent) until a producer exists. So the wave
also needs **id.\* tag producers** (parsed-from-extraction for ssn_hash/dob/expiration/citizenship/
marital; AI for name/address/title-consistency/POA).

**Recommendation: BLOCKED.** Do NOT proceed to -B (author ID specs/rules) until a generalization
ticket delivers (1)–(4) above, and a materialization ticket delivers the `id.*` producers. Proceeding
now means copying `as1.py`/`oc2.py` ten times — the exact trajectory that kills the tag architecture's
scalability claim. The plan below is ready to execute the moment those land.

---

## 1. The ID family by kind / evaluation path (from `rule_kinds.csv`)

| rule | name | kind | evaluation_path | numeric | exact | priya_validated | needs_signoff |
|---|---|---|---|---|---|---|---|
| ID-1 | Borrower name consistency | structural | ai_fuzzy_match | false | false | false | false |
| ID-2 | SSN consistency | structural | deterministic_only | false | **true** | false | false |
| ID-3 | DOB consistency | structural | deterministic_only | false | **true** | false | false |
| ID-4 | Current address consistency | structural | ai_fuzzy_match | false | false | false | false |
| ID-5 | ID expiration | structural | deterministic_only | false | **true** | false | false |
| ID-6 | Application completeness (1003) | structural | deterministic_only | false | **true** | false | false |
| ID-7 | Marital status / title consistency | structural | ai_fuzzy_match | false | false | false | false |
| ID-8 | Citizenship / residency eligibility | **judgmental** | ai_judgment | false | — | false | false |
| ID-9 | Power of attorney acceptability | **judgmental** | ai_judgment | false | — | false | false |
| ID-10 | OFAC / fraud / sanctions | **out_of_scope** | static_filter | false | — | false | false |

**Path grouping:**
- **Thin deterministic (LP-315 gate + `satisfies`):** ID-2 (SSN exact), ID-3 (DOB exact), ID-5
  (`id_expiration >= closing_date` date math), ID-6 (1003 presence check).
- **Cross-source hybrid (deterministic exact bookend → AI fuzzy fallback — candidate-then-judge,
  LP-314 pattern):** ID-1 (name), ID-4 (address), ID-7 (marital/title).
- **AI-at-rule-time judgment (LP-319, MANDATORY ratification):** ID-8 (citizenship eligibility),
  ID-9 (POA acceptability).
- **Out of scope → `not_applicable`, NO tags, NO rule here:** ID-10 (external OFAC/watchlist service —
  a `static_filter`, not computed in this pipeline; record as out-of-scope).

**Domain trap flagged (Stage A vs Stage B):** ID-1/2/3/4/7 are **cross-source** (compare one fact
across documents/entities) → they need **Stage B**-style correlation, NOT per-entity Stage A. ID-5/6
and the raw inputs to ID-8/9 are per-entity (Stage A / parsed). This is the primary reason the cross-
source consistency primitive (§0.4) is required.

---

## 2. Tags — exist (REUSE) vs new

**The reuse story is strong: nearly every ID tag already exists in `fact_tags.csv`.** No new tag is
clearly required for the *raw facts*; the open modeling question is whether the cross-source
*consistency verdict* is a rule-time computation over existing raw tags or a NEW verdict tag.

| rule | tags it needs | status |
|---|---|---|
| ID-1 | `id.name_normalized` (borrower, AI) | EXISTS (reuse) |
| ID-2 | `id.ssn_hash` (borrower, parsed match_hash) | EXISTS (reuse) |
| ID-3 | `id.dob` (borrower, parsed date) | EXISTS (reuse) |
| ID-4 | `id.address_normalized` (doc, AI), `id.current_address_type` (borrower, AI enum) | EXIST (reuse) |
| ID-5 | `id.id_expiration` (doc, parsed date), `contract.closing_date` (doc, parsed date) | EXIST (reuse) |
| ID-6 | `id.app_required_fields_present` (loan, derived enum: complete \| incomplete+list) | EXISTS (reuse) |
| ID-7 | `id.marital_status` (borrower, parsed enum), `id.title_vesting_consistent` (doc, AI enum), `title.vesting` (doc, AI) | EXIST (reuse) |
| ID-8 | `id.citizenship` (borrower, parsed enum), `program.type` (loan, parsed enum) | EXIST (reuse) |
| ID-9 | `id.poa_present_and_acceptable` (doc, AI enum) | EXISTS (reuse) |
| ID-10 | — (out of scope) | none |

### The consistency-verdict modeling question (open — resolve in -B)

The vocabulary is **inconsistent** about how a cross-source consistency check is represented:
- Some rules have a **verdict-as-tag**: `id.title_vesting_consistent` (ID-7), `property.address_normalized_match`
  (property family) — the compare result IS a tag.
- Others have only the **raw fact**: `id.name_normalized`, `id.ssn_hash`, `id.dob`, `id.address_normalized`
  — the compare would happen in the rule (needs the cross-source primitive §0.4).

**Recommendation:** for the EXACT ones (ID-2 SSN, ID-3 DOB) do the compare deterministically in the
evaluator over the raw tags (no new tag). For the AI-FUZZY ones (ID-1 name, ID-4 address) consider a
NEW `rule_judgment` verdict tag to mirror `id.title_vesting_consistent`:

- **`id.name_consistent`** — entity=borrower, enum `["yes","no","unknown"]`, tag_role=`rule_judgment`,
  produced_by=AI, **stage B**; depends_on=`id.name_normalized` (per source). Candidates = the same
  borrower's `id.name_normalized` across all sources; the AI judges match vs nickname/maiden/format
  variance.
- **`id.address_consistent`** — entity=borrower, enum `["yes","no","unknown"]`, tag_role=`rule_judgment`,
  produced_by=AI, **stage B**; depends_on=`id.address_normalized`, `id.current_address_type`. Candidates
  = the borrower's addresses across sources, filtered by `id.current_address_type` (compare residence↔
  residence — the absent≠empty trap), AI judges tolerant match.

**REUSE FLAG:** `id.address_consistent` is a *near-neighbor* of `property.address_normalized_match` —
but they are **different facts** (borrower's identity/current address vs the SUBJECT PROPERTY address
across MISMO/contract/tax/appraisal). Distinct on purpose; do NOT collapse them. This is a decision for
-B, not a foregone new tag — the alternative is the generic cross-source primitive doing the compare
over the raw `id.name_normalized`/`id.address_normalized` tags with no verdict tag at all.

**Materialization (repeat of §0):** none of these tags are produced yet. -B must author the producers.

---

## 3. Thresholds — agency-default vs overlay-pending

**The ID family is threshold-LIGHT.** Most rules are exact-match / presence / fuzzy with NO numeric
threshold. `priya_validated=false` / `threshold_needs_signoff=false` on every ID row (they carry no
agency numeric value to sign off).

| rule | threshold / window | agency default | guideline reference | classification |
|---|---|---|---|---|
| ID-1, ID-2, ID-3, ID-4, ID-6, ID-7 | — (exact / presence / fuzzy) | — | — | **N/A (no threshold)** |
| ID-5 | `id.id_expiration >= contract.closing_date` (date-vs-date) | The reference is the **file's own closing date**, not an agency numeric value. Agency requires acceptable, unexpired evidence of identity at closing. | No single Selling-Guide numeric threshold (identity-evidence acceptability is lender/investor-doc-driven, not a B-chapter number) | **N/A numeric; UNSURE re a grace period** — needs human/Priya confirmation |
| ID-8 | citizenship eligibility per program | Fannie: US citizens, permanent residents, AND non-permanent residents are eligible (non-permanent needs valid work authorization); FHA similar; **investor overlays vary**. Not a numeric threshold — eligibility CRITERIA (spec data). | Fannie B2-2-01/02 (borrower eligibility / non-US citizens) — value to be human-encoded | **overlay-pending / UNSURE** (investor overlays + evolving statuses e.g. DACA) — needs Priya |
| ID-9 | POA acceptability | investor rules (occupancy limits, interested-party prohibition, durable vs specific, dating) — interpretive, not numeric | Fannie B8-5-05 (POA) — to be human-encoded | **overlay-pending / judgment** — needs Priya |

**Honesty note:** I am **UNSURE** of (a) any grace period for an expired ID at closing (ID-5), (b) the
exact investor-overlay set for non-permanent-resident/DACA eligibility (ID-8), and (c) POA acceptability
specifics (ID-9). These are guideline values a HUMAN must encode from the real Selling Guide /
investor matrices — **do not guess them into a spec**; a wrong encoded value mis-evaluates silently
and permanently.

---

## 4. The eval plan — case matrix per in-scope rule

Mandatory 13-point matrix; N/As explicit. (ID-10 out of scope → the only "case" is: it resolves to
`not_applicable` with no tags/rule and is recorded as externally-filtered.)

**Legend for the repeated cases (apply to every rule below):** 5 required tag ABSENT → couldnt_check ·
6 required tag UNKNOWN → couldnt_check (distinct reason) · 7 low-confidence tag → needs_review ·
9 a fired finding carries NON-EMPTY reasoning · 10 tag-level golden labels on the rule's tags.
Case 12 (gated calc → couldnt_check) is **N/A for the entire ID family** — no ID rule reads a calculator.

### ID-1 — Borrower name consistency (fuzzy)
1 must-fire: two sources give genuinely different names for the same borrower slot. 2 must-not-fire:
all sources agree. 3/4 boundary: **N/A** (no threshold). 8 variance: "Robert" vs "Bob", maiden vs
married surname, suffix Jr./III drift, a two-part Hispanic surname truncated in one source → exact
fails, fuzzy should MATCH (must-not-fire). 11 judgment (fuzzy leg): the fuzzy match verdict is
ratification-pending. **13 DOMAIN EDGE:** borrower **married between document dates** — DL shows maiden,
1003 shows married name → NOT a discrepancy (same person). A naive exact-match test fires falsely;
the rule must reconcile via marital/name-change signals, not just string-compare.

### ID-2 — SSN consistency (deterministic exact)
1 must-fire: `id.ssn_hash` differs across sources for one borrower. 2 must-not-fire: all hashes equal.
3/4 boundary: **N/A**. 8 variance: a transposed digit (typo) still hashes differently → fires (correct
— a typo IS a discrepancy to resolve). **13 DOMAIN EDGE:** a **non-permanent resident with an ITIN on
one document and an SSN on another**, or the credit-report SSN differing from the 1003 (a classic
identity-theft / synthetic-fraud signal) — the rule must fire and route to review, not silently pass.
(Exact-hash: a match_hash `null` on a source → couldnt_check, not a false match.)

### ID-3 — DOB consistency (deterministic exact)
1 must-fire: `id.dob` differs across sources. 2 must-not-fire: equal after normalization. 3/4: **N/A**.
8 variance: `03/04/1985` vs `1985-03-04` (format) → normalize, MATCH (must-not-fire); `MM/DD` vs
`DD/MM` ambiguity is the trap. **13 DOMAIN EDGE:** a DOB **off by one digit/year** (typo) reads as a
different person vs a genuine mismatch — plus a DOB implying an implausible age (minor / 100+) is a
data-integrity red flag the rule should surface.

### ID-4 — Current address consistency (fuzzy)
1 must-fire: the borrower's stated CURRENT residence disagrees across sources. 2 must-not-fire: agree.
3/4: **N/A**. 8 variance: "123 N Main St Apt 4" vs "123 North Main Street #4" → canonicalize, MATCH.
11 fuzzy verdict ratification-pending. **13 DOMAIN EDGE (the absent≠empty trap):** the **DL address is a
PRIOR address** (borrowers rarely update a DL after moving) or a **mailing / PO-Box** — comparing it to
the current *residence* is a false discrepancy. The rule must use `id.current_address_type` to compare
residence↔residence, never mailing↔residence.

### ID-5 — ID expiration (deterministic date)
1 must-fire: `id.id_expiration < contract.closing_date` (expired at closing). 2 must-not-fire:
expiration ≥ closing. **3 boundary OVER:** expiration = closing_date − 1 day → fires. **4 boundary
UNDER:** expiration = closing_date exactly → passes (valid on the day; confirm ≥ vs > with Priya).
8 variance: date-format normalization on the expiration. **13 DOMAIN EDGE:** the ID was valid at
APPLICATION but the **closing date slipped** (rate-lock extension) past expiration → must fire at
closing, not application; and a state that issues **non-expiring** IDs (absent expiration ≠ expired →
couldnt_check, not a fire).

### ID-6 — Application (1003) completeness (deterministic presence)
1 must-fire: `id.app_required_fields_present == "incomplete + list"`. 2 must-not-fire: `"complete"`.
3/4: **N/A**. 8 variance: a field **present but placeholder** ("N/A" / 0 / whitespace) — present≠valid;
the producer of `id.app_required_fields_present` must treat a blank/placeholder as missing. **13 DOMAIN
EDGE:** the **Declarations** section (citizenship, prior foreclosure/bankruptcy) or the **co-borrower's**
section left blank on a joint 1003 — a naive "all top-level fields present" check misses these; the
required-field set must be the real 1003 required set.

### ID-7 — Marital status / title consistency (fuzzy)
1 must-fire: `id.title_vesting_consistent == "no"` (e.g. married borrower, title vests "a single
person"). 2 must-not-fire: `"yes"`. 3/4: **N/A**. Title doc ABSENT → couldnt_check (or n/a if title
not yet in file — decide in -B). **13 DOMAIN EDGE:** a **community-property state** (spouse must be on
title / sign even if not a borrower) — the rule must know the state; and a borrower **married after the
title commitment** (timing) reads as inconsistent but is explainable.

### ID-8 — Citizenship / residency eligibility (JUDGMENT — ratification-pending)
1 must-fire: an ineligible status for the program (per the encoded eligibility criteria). 2 must-not-
fire: a clearly eligible status. 3/4: **N/A**. 11 EVERY verdict ratification-pending (LP-319 armor —
yes/no/unknown all → needs_review). 8 variance: status expressed unusually on the doc. **13 DOMAIN
EDGE:** a **non-permanent resident on a work visa with a valid EAD** (eligible for Fannie, but some
investors overlay-restrict) vs an **expired visa/EAD at closing**, vs a **DACA** recipient (eligibility
changed over time) — the judgment must reason against the *program's* rules + note investor-overlay
uncertainty, never auto-clear.

### ID-9 — Power of attorney acceptability (JUDGMENT — ratification-pending)
1 must-fire: `id.poa_present_and_acceptable == "no"`. 2 must-not-fire: `"yes"` (or `"n/a"` when no POA
used). 3/4: **N/A**. 11 EVERY verdict ratification-pending. **13 DOMAIN EDGE:** a POA used on an
**investment property** (commonly disallowed), an **interested party** (loan officer / realtor) named
as attorney-in-fact (prohibited), a POA **dated after the note**, or a **specific vs durable** POA that
doesn't cover the transaction — each is an acceptability failure a boolean "POA present?" check misses.

### ID-10 — OFAC / fraud / sanctions
**Out of scope** (external watchlist service, `static_filter`). No tags, no in-pipeline rule. The only
assertion: it resolves to `not_applicable` and is recorded as externally-handled (do NOT fabricate an
OFAC verdict from tags).

**Rules with no credible must-fire case:** none — every in-scope ID rule has a clear violation it
exists to catch. (ID-10 is deliberately out-of-scope, not un-authorable.)

---

## 5. Risks / open questions (need Priya or human guideline verification)

1. **BLOCKER — evaluator generalization (LP-308 never landed).** The wave cannot author rules as specs
   until the generic deterministic + judgment evaluators, the generalized spec schema, the cross-source
   consistency primitive, and a rule registry exist. **Priority-0 decision-to-be-made.**
2. **BLOCKER — `id.*` tag materialization.** No producer exists for any `id.*` tag; the wave needs the
   producers (parsed + AI) before any ID rule can do more than `couldnt_check`.
3. **Consistency-verdict modeling** (§2): raw-compare-in-rule vs `id.name_consistent`/`id.address_consistent`
   verdict tags. Decide in -B; keep the vocabulary honest (reuse `id.title_vesting_consistent`'s pattern;
   do not collapse borrower-address into `property.address_normalized_match`).
4. **Guideline values (UNSURE — human-encode, do not guess):** ID-5 expired-ID grace period + ≥ vs >
   at closing; ID-8 non-permanent-resident/DACA eligibility + investor overlays; ID-9 POA acceptability
   specifics; ID-6 the authoritative 1003 required-field set (incl. Declarations + co-borrower).
5. **Cross-source subject identity.** The consistency rules key on "the same borrower across sources" —
   this depends on a reliable borrower↔document resolution (the `belongs_to` link, LP-202). Confirm it is
   trustworthy enough to group facts by borrower before comparing (a mis-resolved doc → a false
   discrepancy). The LP-302a "no raw account to hash" gap is a nearby caution.
6. **State-dependent rules** (ID-7 community property, and address rules) need the property/borrower
   state — confirm it is available as a tag/field.

---

## 6. Recommendation

**BLOCKED — do NOT proceed to LP-323-ID-B (author ID specs/rules) yet.** Land, in order:
1. **A generalization ticket** (the deferred LP-308 + generic deterministic evaluator + generic judgment
   evaluator + the cross-source consistency primitive + a rule registry), with AS-1 and OC-2
   re-expressed as data on top (regression-proof).
2. **An `id.*` tag-materialization ticket** (the producers).

Then -B (author the ID specs + the `id.name_consistent`/`id.address_consistent` decision) and -C (the
golden eval cases per §4) can proceed on a scalable base. Authoring ID rules before the generic
evaluator exists would fork `as1.py`/`oc2.py` across the family — the precise failure this gate exists
to prevent.

## ADR

**None (recon only).** The gate surfaced two decisions-to-be-made, to be recorded in the tickets that
make them (not here): **(D1)** the evaluator/spec generalization design (owns re-expressing AS-1/OC-2 as
data + the cross-source consistency primitive), and **(D2)** the consistency-verdict tag modeling
(raw-compare vs verdict tags) with its reuse boundaries.
