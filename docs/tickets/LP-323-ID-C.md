# LP-323-ID-C — IDENTITY family eval (the full case matrix + calibration)

## What it is

The wave's rules are authored (LP-323-ID-B + the gap tickets LP-327/328/329/330/331). This ticket
**proves they WORK** — both directions, edge cases, tag-level — against a golden case matrix, in the
spirit of the LP-317 harness. **EVALUATE, DON'T FIX:** every failure is reported as a finding/ticket, not
patched. The diff is **eval cases + calibration + the doc only** — no rule/tag/spec/engine file changed
(verified: `git diff --name-only` is two test files + this doc).

**Deliverables**
- `backend/tests/verification/eval/test_identity_family_eval.py` — the ID golden harness + the full
  matrix (finding-level + tag-level + provenance + cost + armor), 39 cases.
- `backend/tests/verification/eval/test_identity_family_calibration.py` — the ID-tag calibration
  (unknown-rate + accuracy-when-concrete), keyless + a skipped live seam, 4 + 1 cases.
- This doc: the per-rule case table, the calibration, the bugs/observations (reported not fixed), the
  ID-6 known limitation, the ID-family Priya list, and the **wave-cost assessment**.

## The harness situation (why a dedicated ID harness, not LP-317's)

The LP-317 harness is **AS-1/transaction-shaped**: `FixtureTxn`, `_build_snapshot(txns)`, and
`_score_tags` hardwired to the four `txn.*` tags and the candidate-search pipeline. It cannot run the ID
rules (consistency over borrower documents, `per_document`/`per_borrower` judgment, `loan`/date
deterministic) without a rewrite. So this ticket adds a **dedicated ID golden harness beside it**, with the
SAME discipline (finding-level verdict + tag-level golden labels + provenance + the no-AI cost property +
the ratification armor), keyless via the `Reasoner` stub. Each rule is evaluated **through its real
evaluator** (`evaluate_consistency_rule` / `evaluate_deterministic_rule` / `evaluate_judgment_rule`) —
activation gates the *orchestrator*, not the evaluator, so **unactivated rules (ID-5, ID-8) are exercised
by calling their evaluator directly**.

## Acceptance criteria

- [x] Every in-scope ID rule (ID-1..ID-9) has a **must-FIRE** and a **must-not-fire** case — both
  directions non-negotiable. A guard test (`test_every_in_scope_id_rule_has_a_must_fire_case_in_this_module`)
  fails loudly if a fire case is ever dropped.
- [x] The fail-closed cases (absent / unknown / low-confidence) covered, with the **absent≠unknown
  distinct-reason** property demonstrated at the gate (ID-6) and the consistency-collapse observed (ID-1).
- [x] Tag-level golden labels independent of the finding; the **no-AI cost property** asserted for the
  fuzzy rules (ID-1/ID-4 exact match → `stub.calls == 0`); the **armor** asserted for the judgment rules
  (ID-8/ID-9 every verdict ratification-pending); **provenance** (a fired/needs_review finding carries
  non-empty reasoning).
- [x] ID-10 resolves to `not_applicable` (out_of_scope), never `couldnt_check`; no spec, no tags.
- [x] Calibration extended to the five AI-produced ID tags; keyless scoring runs, live is skippable.
- [x] ruff + mypy + full suite green (2132 passed, 1 skipped, 1 xfailed, deterministic order).
- [x] **No rule/tag/spec/engine file changed** (the integrity property).

## THE PER-RULE CASE TABLE (rule × the 13 cases)

Legend: **P** = pass (asserted) · **N/A** = not applicable, reason given · numbers are the LP-323-ID-A §4
matrix cases. Case 12 (gated calc → couldnt_check) is **N/A for the entire family** — no ID rule reads a
calculator input (there is no ID calculator; AS-1/OC-2/Income own that path).

| Rule | 1 fire | 2 clean | 3 over | 4 under | 5 absent | 6 unknown | 7 low-conf | 8 variance | 9 prov | 10 tag | 11 armor | 12 calc | 13 domain |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **ID-1** name (fuzzy) | P | P (+no-AI) | N/A¹ | N/A¹ | P | P² | P | P (nickname+maiden) | P | P | N/A³ | N/A | P married-between-docs |
| **ID-2** SSN (exact) | P | P | N/A¹ | N/A¹ | P | N/A²ᵃ | N/A⁴ | P (ITIN vs SSN) | P | P⁵ | N/A³ | N/A | P null-hash→<2 couldnt_check |
| **ID-3** DOB (exact) | P | P | N/A¹ | N/A¹ | N/A²ᵇ | N/A²ᵇ | N/A⁴ | P (date-format) | P | P⁵ | N/A³ | N/A | P ambiguous 13/04 not silently equal |
| **ID-4** address (fuzzy+filter) | P | P (+no-AI) | N/A¹ | N/A¹ | P²ᶜ | N/A²ᶜ | N/A⁴ | P (abbrev/unit) | P | P | N/A³ | N/A | P mailing-only→couldnt_check |
| **ID-5** ID-exp (date det.) | P | P | P ==closing(`>=`) | P valid | P | N/A⁶ | N/A⁷ | P (date coercion) | P | P | N/A³ | N/A | P closing-slip + non-expiring→couldnt_check |
| **ID-6** 1003 (det., loan) | P | P | N/A⁸ | N/A⁸ | P | **P (distinct)** | N/A⁷ | P | P | P | N/A³ | N/A | **P KNOWN UNDER-FIRE (starter set)** |
| **ID-7** title (det., per_doc) | P | P | N/A⁸ | N/A⁸ | P⁹ | P | N/A⁷ | P | P | P | N/A³ | N/A | P scope + no-title→couldnt_check(LP-330) |
| **ID-8** citizenship (judgment) | P | P | N/A⁸ | N/A⁸ | P | P (gate) | N/A⁷ | P | P | P | **P** | N/A | P per-borrower isolation, one absent→couldnt_check |
| **ID-9** POA (judgment, per_doc) | P | P | N/A⁸ | N/A⁸ | P⁹ | P | N/A⁷ | P | P | P | **P** | N/A | P investment/interested-party/dated-after-note |
| **ID-10** OFAC | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A¹⁰ | N/A | → not_applicable, never couldnt_check |

**N/A reasons (stated, never silently omitted):**
1. **No numeric threshold** — a fuzzy/exact string compare has no over/under boundary.
2. **Consistency case-5/6 collapse** — a consistency rule's gather EXCLUDES both an absent tag AND an
   `"unknown"`-valued tag (`absent≠unknown≠empty` — an unknown name/SSN is not a value to compare), so
   both route to the SAME `couldnt_check` "nothing to compare". (a) ID-2 unknown-hash = a null hash =
   case-5. (b) ID-3 exercises its absent/unknown via the shared consistency path proven on ID-1. (c) ID-4
   case-5 is the residence-filter mailing-only edge (case 13); unknown-value is the same collapse. **The
   absent≠unknown DISTINCT-reason guarantee is a GATE property** — demonstrated on the deterministic ID-6
   (`is absent` vs `is unknown`, asserted distinct) and the judgment ID-8. This is an **OBSERVATION, not a
   bug** — see Findings §F1.
3. **Not a judgment rule** — case 11 (every-verdict-ratification-pending) applies only to ID-8/ID-9.
4. **No AI leg** — an exact-compare rule (ID-2/ID-3) has no confidence-floor needs_review path; low-conf
   is a fuzzy/gate concern proven on ID-1/ID-5/ID-6.
5. **Tag-level via the value semantics** — ID-2/ID-3 rest on `id.ssn_hash`/`id.dob` equality; the tag
   golden label is the compared value itself (a systematically wrong hash → a spurious fire, caught by
   the exact-compare cases).
6. ID-5 **absent** expiration IS the domain edge (non-expiring ID → couldnt_check) — case 5 = case 13.
7. **No low-confidence path for a parsed/derived deterministic input** — ID-5 (parsed dates), ID-6
   (derived), ID-7 (the tag's own confidence gates; a below-floor `id.title_vesting_consistent` →
   needs_review is the gate path shared with the judgment rules). Low-conf is exercised on ID-1.
8. **No numeric threshold** — a `ne`/`eq`/`<` tag predicate has no over/under boundary (ID-5's `<` date
   boundary IS covered as case 3/4: `==closing` and a valid date).
9. ID-7/ID-9 **absent** = the LP-330/LP-329 scope edge (title expected → couldnt_check; a POA doc absent
   → not_applicable) — case 5 folds into case 13.
10. **Out of scope** — ID-10 (OFAC/sanctions) is an external watchlist service, `out_of_scope` in
    `rule_kinds.csv`; it has no spec and no tags, so the engine evaluates nothing → `not_applicable`
    (Tab 4). The ONLY assertion that matters is that it never masquerades as `couldnt_check`.

**Both-directions guard:** every in-scope rule (ID-1..ID-9) has an asserted must-FIRE case. No rule ships
with only a doesn't-fire case. No eval fatigue.

## Calibration (Phase 3)

Extended to the five AI-produced ID tags LP-323-ID-A named, reusing the LP-317 `DimensionCalibration`
primitive **unchanged** (no app-code edit). Two numbers per tag: **unknown-rate** (over-abstention if
high — everything routes to couldnt_check) and **accuracy-when-concrete** (under-abstention/fabrication if
< 90%). KEYLESS baseline (labels replayed → trivially perfect, a plumbing check, per calibration.py's own
docstring):

```
ID-FAMILY CALIBRATION — KEYLESS (labels replayed — plumbing + structure check)
dimension                    n  unknown%  acc-concrete%  flags
id.name_normalized          10     20.0%         100.0%  ok
id.address_normalized       10     20.0%         100.0%  ok
id.current_address_type     10     20.0%         100.0%  ok
id.residency_eligible       10     20.0%         100.0%  ok
id.poa_acceptable           10     20.0%         100.0%  ok
```

**The metric is NOT inert** (the honest part): two tests feed a live-shaped distribution and assert the
flags fire — a 70%-unknown tag → **OVER-ABSTENTION**; a tag concrete-but-wrong 40% → **UNDER-ABSTENTION /
fabrication**. So when live numbers replace the replayed baseline, over/under-abstention WILL be caught.

**Live calibration** (the real LP-326 materialization reasoner producing these tags from raw content,
scored vs golden labels) is the meaningful measure and is a **skipped seam** without an API key — wiring
the ID materialization reasoners into a scored live harness is its own follow-on (see the Priya/gap list).
Keyless scoring always runs for CI.

## FINDINGS — reported, NOT fixed (the integrity property)

No case revealed a **rule/engine bug** — the authored rules behave as specified across both directions and
every edge. Two things surfaced, both reported honestly rather than patched:

### F1 — OBSERVATION (not a bug): consistency collapses absent + unknown-value into one couldnt_check
For a **consistency** rule the gather EXCLUDES both a `None` tag and an `"unknown"`-valued tag
(`consistency.py::_borrower_documents`: *"absent≠unknown≠empty … Neither is a value to compare"*), so
case 5 (absent) and case 6 (unknown value) yield the **same** `couldnt_check` reason ("nothing to
compare"). The matrix's case-5≠case-6 distinct-reason guarantee is therefore a **GATE** property
(deterministic/judgment: `"is absent"` vs `"is unknown"`, asserted distinct on ID-6), **not** a
consistency property.
- **Assessment:** correct-by-design, not a defect — an unknown SSN is as uncomparable as a missing one.
- **Proposed action:** none (documented). If a future rule needs to *distinguish* "a source affirmatively
  said unknown" from "a source was silent" at the consistency layer, that is a **new capability ticket**
  (surface the unknown-count in the couldnt_check reason), not a bug fix.

### F2 — KNOWN LIMITATION (do NOT fix here): ID-6 under-fires on the STARTER 1003 field set
`id.app_required_fields_present` is DERIVED (LP-326) from a **STARTER** required-field set — borrower
name, SSN, loan amount, property address — which **omits the Declarations section and co-borrower
fields**. So a 1003 that is missing Declarations still derives `"complete"` → **ID-6 SATISFIED, which is
WRONG** (it under-fires; an incomplete 1003 passes). The eval asserts the CURRENT (under-firing) behavior
honestly (`test_id6_case13_known_underfire_starter_fieldset`).
- **Assessment:** a real coverage gap, but the authoritative required-field set is a **domain value that
  is Priya's, not ours to guess** — expanding it here would fabricate an underwriting standard.
- **Proposed action:** **the top Priya item below.** A follow-on ticket expands the derivation's field set
  to Priya's authoritative 1003 completeness standard (Declarations, co-borrower, HMDA/GMI as required).
  Not an engine bug — a data/domain gap.

## KNOWN LIMITATION (headline) — ID-6 starter field set → the top Priya item

Restated for planning visibility: **ID-6 is LIVE and firing, but against a starter completeness
definition — it will pass an incomplete 1003.** This is the single most consequential ID-family gap that
is *not* a code defect. It must be closed by Priya's field set before ID-6 can be trusted to block an
incomplete application.

## PRIYA / HUMAN-VERIFY — the full accumulated ID-family list

| # | Item | Rule | Encoded default (conservative) | Priya must confirm |
|---|---|---|---|---|
| 1 | **1003 required-field set** (top item) | ID-6 | STARTER: name, SSN, loan amount, property address | The authoritative completeness set (Declarations, co-borrower, GMI/HMDA). |
| 2 | ID-expiration `>=` / grace | ID-5 | `>=` closing (valid ON the closing day; expired strictly before) | Whether a grace period / "valid at application" rule applies. |
| 3 | Title-commitment expectation | ID-7 | UNCONDITIONALLY expected (purchase AND refi) → confident absence = couldnt_check | Whether a loan-purpose carve-out makes it purchase-only (no loan-purpose tag exists yet). |
| 4 | Community-property vesting | ID-7 | judged from `id.title_vesting_consistent` as produced | Community-property-state spousal-join rules; married-after-title-date handling. |
| 5 | Non-permanent-resident eligibility | ID-8 | eligible with valid work authorization, subject to investor overlays (Fannie B2-2-01/02) | The work-authorization requirements + which programs. |
| 6 | DACA / evolving statuses | ID-8 | judged per program, flag uncertainty, never auto-clear | The current DACA eligibility stance per investor. |
| 7 | Investor OVERLAY set | ID-8 | the prompt flags overlay uncertainty | The authoritative per-investor overlay list. |
| 8 | POA acceptability rules | ID-9 | attorney-in-fact not an interested party; durable/specific & covers the txn; dated consistent with the note | The investor's exact POA form/dating/interested-party rules. |
| 9 | **Live ID-tag calibration seam** | all AI ID tags | keyless plumbing check only | Run the live materialization reasoner over real (GLBA-safe) content to get true unknown-rate + concrete accuracy. |

ID-8's items are **fair-lending-sensitive**: a wrong encoded eligibility rule is a serious, silent,
permanent error — hence the conservative "answer unknown when unsure" default and the ratification armor.

## Did any engine/rule/tag file change? — NO

`git diff --name-only HEAD` is exactly two new test files + this doc. **No `app/` file, no spec YAML, no
tag declaration, no engine logic was touched.** The harness was not bent to pass. Every green case is the
authored rule behaving as specified; the two things that surfaced (F1, F2) are reported above, unpatched.

## THE WAVE-COST ASSESSMENT (why this ticket matters beyond ID)

**What the ID wave actually cost (7 tickets):**
- `-A` recon (the case plan + domain edges) — **one-time per wave** (recurring, but cheap).
- `-B` authoring (the 9 specs + tags) — **recurring per wave** (this is the irreducible per-rule cost).
- FIVE gap tickets — LP-327 (multi-subject judgment), LP-328 (typed operands + the hand-edit overlay),
  LP-329 (document applicability), LP-330 (absent-document resolution), LP-331 (borrower-keyed facts).
- `-C` eval (this ticket) — **recurring per wave** (the matrix + calibration).

**One-time shape-space discovery (now REUSABLE — the five gaps are paid off):**
- Typed operands (decimal + date coercers) — **LP-328**, reusable by any deterministic rule.
- Multi-subject judgment (one verdict per subject) — **LP-327**.
- Document-type applicability (`not_applicable` ≠ `couldnt_check`) — **LP-329**.
- Absent-expected-document resolution (`applicability_expected`) — **LP-330**.
- Borrower-keyed fact assembly for per-borrower judgment — **LP-331**.

These five were **the identity wave discovering the generic engine's missing primitives**. They are NOT
per-wave costs — they are now part of the engine and every later wave reuses them for free.

**Recurring per-wave cost:** the `-A` case plan, `-B` spec/tag authoring, and `-C` eval. That is the
steady-state cost of a wave once the shape space is covered.

**Honest estimate — what should Wave 2 (Income) cost?**
- **Likely ~3 tickets, not 7:** `-A` recon + `-B` authoring + `-C` eval. The five gap tickets should NOT
  recur — Income's needs map onto primitives the ID wave already built:
  - stated-vs-documented consistency → **LP-325** (the consistency primitive) ✓
  - date recency (paystub/W-2/VOE dates vs application) → **LP-328** typed `date` operands ✓
  - per-borrower judgment (employment reasonableness, income stability) → **LP-331** borrower-keyed facts ✓
  - document applicability (a VOE rule scoped to a VOE doc) → **LP-329** ✓
- **New gaps Wave 2 WILL likely surface (predicted):**
  1. **The calculator seam is INERT (flag it).** LP-318's Caveat A: no rule currently reads a calculator
     input, and this eval confirms **case 12 (gated calc → couldnt_check) is N/A across all of ID** — the
     path is untested by any live rule. Income's qualifying-income / DTI checks are the FIRST real
     calculator consumers, so Wave 2 will need a **calculator-operand primitive** (a deterministic/
     judgment operand that reads a `CalculationEntry`, gates on a failed/absent calc → couldnt_check).
     This is a genuine new gap — predict a ticket.
  2. **Variance thresholds are Priya values** (e.g. "income within X% of stated") — an authoring/Priya
     cost, not an engine gap, but it will need the typed-operand threshold discipline + sign-off table.
  3. **Multi-value gather leg** (deferred in LP-331): if an Income per-borrower judgment reasons over a
     document-sourced, multi-valued fact (several paystubs), the LP-325 gather-leg-into-judgment (reason
     over the SET) is still unbuilt — Income may be the wave that forces it. Predict a possible ticket.
  4. **Materialization of the borrower-level Income facts** — the same `borrower_id ↔ MISMO-index`
     resolution LP-331 flagged (still open) is a prerequisite for per-borrower Income judgment to
     *activate*, not just evaluate.

**Bottom line:** the ID wave's 7-ticket cost was front-loaded shape discovery. Steady-state is ~3
tickets/wave, plus **one predictable new primitive per wave** where the wave touches an engine capability
ID never exercised — for Income, that is the **calculator-operand seam** (LP-318 Caveat A, today inert).

## ADR

**None** — this is an eval ticket; it changed no architecture. The one architectural *question* it
surfaces (should the consistency layer distinguish affirmative-unknown from silent-absent in its
couldnt_check reason — F1) is a **decision-to-be-made in its own ticket**, not decided here.

## Cross-refs

§3D/§8; LP-317 (the golden harness + calibration); LP-323-ID-A §4 (the case plan + domain edges);
LP-323-ID-B (the family); LP-325/326 (consistency semantics + tag declarations); LP-327/328/329/330/331
(the five gap tickets); LP-318 Caveat A (the inert calculator seam).
