# LP-323-ID-B — Author the IDENTITY family (rule specs + tag declarations, DATA ONLY)

## What it is

The wave's blockers were cleared (LP-324 rules-as-data, LP-325 the consistency primitive, LP-326 tags
as declarations). This ticket authors the remaining ID rules on that base — and, critically, tests
whether **"a rule is just data"** holds by trying to author them with ZERO engine Python. It does not
fully hold for the ID family: **3 rules author cleanly as data; 4 surface concrete generalization gaps.**

## Acceptance criteria

- [x] ID-1 (name, fuzzy consistency), ID-3 (DOB, exact consistency), ID-6 (1003 completeness,
  deterministic) authored as SPECS and evaluating through the generic evaluators + LP-326 producers.
- [x] ID-10 → `not_applicable` (out_of_scope; no spec, no tags — never `couldnt_check`).
- [x] The D2 decision recorded (ADR-267).
- [x] **Zero engine Python** except one explicitly-allowed registry entry (a `date` normalizer) — and a
  *removal* of a hardcoded rule-id set (a generalization improvement). A test asserts no rule-id/family
  branch in the evaluators.
- [x] Minimal per-rule fires/doesn't/couldnt_check tests through the generic path; the PRIYA/HUMAN-VERIFY
  list (D3); the generalization-gap report (below).
- [x] ruff + mypy + full suite green (AS-1/OC-2/ID-2/ID-4 unchanged): **2038 passed, 1 xfailed**.

## The rules authored (by shape)

| Rule | Shape | Block | Status |
|---|---|---|---|
| **ID-1** Borrower name consistency | fuzzy consistency (gather `id.name_normalized`, no filter, AI-fuzzy residue) | `consistency` | **authored + ACTIVE** |
| **ID-3** DOB consistency | exact consistency (gather `id.dob`, declared `date` normalization) | `consistency` | **authored + ACTIVE** |
| **ID-6** 1003 completeness | deterministic presence (loan subject, `id.app_required_fields_present`) | `deterministic` | **authored + ACTIVE** |
| **ID-10** OFAC/sanctions | out_of_scope | — | not_applicable (no spec) |

**Activation:** ID-1/ID-3/ID-6 join `ACTIVE_RULE_IDS`; their tags already materialize via LP-326
(`id.name_normalized` = ai/`id_name`, `id.dob` = parsed, `id.app_required_fields_present` = derived). The
orchestrator auto-runs the `id_name` AI group because `_required_ai_groups()` derives it from the active
rules' load-bearing tags — no wiring edit. `_per_borrower_rules()` (retire-eligibility) is now DERIVED
from each spec's `subject_enumeration` instead of a hardcoded `{ID-2, ID-4}` set — so ID-1/ID-3 are
picked up automatically (a generalization improvement, removing a rule-id list).

## D2 — the consistency-verdict modeling decision (ADR-267)

**RAW-COMPARE-IN-RULE.** The LP-325 primitive already does the comparison; a verdict tag
(`id.name_consistent`) would duplicate that machinery in two places that can disagree and make the
compare implicit rather than declared. So ID-1/ID-3 gather the RAW tags (`id.name_normalized`, `id.dob`)
and the rule produces the verdict; no verdict tags minted. `id.title_vesting_consistent` /
`property.address_normalized_match` remain the odd ones out (a verdict baked into a tag), not collapsed
into each other (different facts). Full reasoning in ADR-267.

## Tag declarations added

**None.** Every tag these three rules need was already declared + materialized by LP-326
(`id.name_normalized`, `id.dob`, `id.app_required_fields_present`). No new tag was required. The gap
rules (ID-5/7/8/9) would need declarations, but they are deferred (below), so their declarations are not
added.

## Engine Python needed? (the wave's success criterion)

**Almost none — and only what the ticket explicitly permits.** The evaluators (`deterministic.py`,
`consistency.py` logic, `judgment.py`), the gate, and the producers are UNCHANGED, except:
- **One allowed registry entry:** a `date` normalizer added to `consistency.py`'s `_NORMALIZERS` (for
  ID-3's format-tolerant DOB compare) — exactly the "one-line registry entry for a genuinely new
  normalizer" the ticket allows. It never guesses an ambiguous date (leaves it verbatim), so a real
  mismatch is never masked.
- **A generalization improvement:** `_PER_BORROWER_RULES` (a hardcoded rule-id set) was replaced by
  `_per_borrower_rules()` derived from specs — the opposite of adding a branch.

No `if rule_id == …`, no `id.`-family branch. A test asserts this.

## GENERALIZATION GAPS FOUND (reported, NOT patched — decisions for their own tickets)

Authoring revealed that the three shapes built so far (per-subject Decimal deterministic; cross-source
same-fact consistency; single-loan judgment) do NOT cover four ID rules. Per the ticket ("STOP and report
… do not work around it"), these are NOT hacked into the engine:

- **GAP-A — ID-5 (ID expiration): date-typed deterministic comparison.** `deterministic.py` resolves
  every operand to `Decimal` (`coerce_decimal`); a date *inequality* between two fact-tags
  (`id.id_expiration >= contract.closing_date`) is inexpressible. Needs date-aware operands/comparison, or
  a date→ordinal materialization primitive — an evaluator/producer change, not a one-line registry entry.
- **GAP-B — ID-8 (citizenship) + ID-9 (POA): per-entity judgment.** `judgment.py` is STRICTLY
  single-subject (it fails loud on ≠1 subject — the OC-2 loan shape). ID-8 (per-borrower eligibility) and
  ID-9 (per-POA-document acceptability) need a per-borrower / per-document judgment; the evaluator has no
  multi-subject mode. (ID-8 would also need a new vocabulary output tag; ID-9's POA verdict is inherently
  per-document.)
- **GAP-C — ID-7 (marital/title): per-document structural rule with document-type applicability.**
  Expressible only by enumerating ALL documents (flooding `couldnt_check` on every non-title doc, since
  `id.title_vesting_consistent` materializes "unknown" there) without a document-type applicability
  primitive to scope the rule to the title document.

**Recommendation:** three small generalization tickets — (A) a date/typed-operand comparison in the
deterministic evaluator, (B) a multi-subject judgment evaluator, (C) a document-type applicability /
per-document enumerator with scoped applicability — each with its rule(s) re-expressed as data on top.
A gap found at rule 5 is cheap; the same gap at rule 90 is not.

## PRIYA / HUMAN-VERIFY list (D3 — encoded defaults that MUST be confirmed)

A wrong encoded guideline value mis-evaluates silently and permanently. Every ID rule row is
`priya_validated: false`.

| Item | Rule | Encoded default | Must confirm |
|---|---|---|---|
| 1003 required-field set | ID-6 (live) | LP-326 STARTER: borrower name, SSN, loan amount, property address | The AUTHORITATIVE required set incl. the Declarations section + co-borrower fields on a joint 1003. |
| ID grace period + `>=` vs `>` at closing | ID-5 (gap) | (unencoded — deferred) | Whether an ID expiring ON the closing date is valid (`>=`) or not (`>`); any acceptable grace period. |
| Non-permanent-resident / DACA eligibility + investor overlays | ID-8 (gap) | (unencoded — deferred) | Which citizenship/visa statuses are eligible per program, and the investor-overlay set (evolving, e.g. DACA). |
| POA acceptability specifics | ID-9 (gap) | (unencoded — deferred) | Investor POA rules (occupancy limits, interested-party prohibition, durable vs specific, dating). |

## What -C must cover

The full 13-point golden eval matrix (LP-323-ID-A §4) for the ACTIVE rules (ID-1/ID-3/ID-6) — the domain
edge cases (ID-1 married-between-documents maiden→married name; ID-3 MM/DD vs DD/MM ambiguity + implausible
age; ID-6 placeholder-vs-blank + Declarations/co-borrower). The gap rules (ID-5/7/8/9) get their eval cases
when their generalization tickets land.

## Cross-refs

§3D; ADR-267; LP-324 (rules as data), LP-325 (consistency primitive), LP-326 (tag declarations),
LP-323-ID-A (the wave plan §1/§2/§3/§4/§5).
