# mortgageboss-ai — handoff summary

_2026-08-11. **Read this first when picking the work up in a new chat.**_

---

## ORIENTATION

### Key paths
```
repo              ~/Geet/project/loan-processing/mortgageboss-ai   (branch phase3_bucket_2)
bedrock worktree  ../mbai-bedrock                                  (branch bedrock_integration)

specs             docs/schema-specs/*.json        ← THE SOURCE OF TRUTH for every extractor
Priya's rulings   docs/domain/priya-rulings-2026-08.md
tickets           docs/tickets/LP-*.md
ADRs              through ADR-372

bench tool        app/dev/bench/  + /dev/extraction-bench  (DEV ONLY; 404s in production)
bench output      ~/Geet/project/loan-processing/mb_quality_check/
                    mortgageboss-batch-bench-out/8c999b3f7a1b/   ← the v2 run, 303 docs
                    _records.jsonl                                ← consolidated records
comparison        ~/Geet/project/loan-processing/comparison-output/
                    one folder per doc: bench_extraction.json · cowork_extraction.json · comparison.md
source documents  ~/Geet/project/loan-processing/mortgageboss-batch/
```

### Companion documents — put these in the repo alongside this summary
| document | what it is | status |
|---|---|---|
| `verification-architecture-v2.md` | the architecture — snapshot, tags, rules, verdicts | **current** |
| `extraction-schema-standard.md` | how a schema is designed; the six tests a field must pass | **current** |
| `bench-v2-analysis.md` | the v2 measurement in full — wins, regressions, the accuracy ledger | **current** |
| `extraction-accuracy-problem.md` | the wrong-value problem and why prompts do not fix it | **current** |
| `finish-the-rule-engine-plan.md` | the four phases to 37 → ~100 | **current** |
| `classification-remediation-plan.md` | the three-phase classification fix | mostly executed |
| `missing-types-plan.md` · `missing-extractors-plan.md` | the type/extractor workstreams | executed |
| `schema-gap-remediation-plan.md` · `extractor-failure-remediation-plan.md` | ditto | executed |
| `mortgageboss-progress-summary.md` | ⚠️ **SUPERSEDED — stops at LP-433**, before the generator, the 91 extractors, the tier merge, Bedrock and the whole bench exercise |

### ⚠️ Working notes for a new chat
- **File attachments have arrived EMPTY all session. Paste text into the message instead.**
- **Commits are local. Geet pushes manually. Never push.**
- **Report cost before any model call.** Recent tickets ran $0.05–0.30; the 889-doc bench cost ~$18.
  ⚠️ **Never re-run the full bench casually** — read stored extractions instead.

---

## Where things stand

| | |
|---|---|
| **Rules live** | **37** of ~113 real targets — ⚠️ **unchanged through all of the below** |
| **Extractors wired** | **109+** document types (was 18) |
| **Nested lists captured** | 60+ |
| **Branch** | `phase3_bucket_2` — **commits are local; Geet pushes manually** |
| **Provider** | Bedrock · Haiku 4.5 for classification + extraction · **Sonnet for reasoning** |

**The engine is built. The remaining rule work is gated on inputs — documents, Priya's time, API credit —
not on more engineering.**

---

## ⚠️ IN FLIGHT — LP-475, awaiting Phase B/C

**Fix ONLY the clear reclassification regressions.** Phase A triaged 10 candidates; **3 qualify:**
- **202** title_commitment — siblings 201 (32pp) and 203 (19pp), the same invoice+CPL+commitment bundle,
  classified fine and extracted Schedule B. So 202's "package" decline is a genuine regression.
- **208, 209** earnest_money_receipt — 1-page "ACKNOWLEDGMENT OF RECEIPT OF MONIES", identical to the proven
  sibling 207.

**7 correctly stay declining** — 204/196 are multi-doc packages (splitter's job) · 132 is a portal screenshot ·
177/178 are lease *addenda* (an addendum is not a lease) · **211 fails the triage rule: zero documents ever
classified that type, so its extractor is unproven** · **236** is an occupancy LOX **in Gmail form** — any cue
tight enough to catch it would pull generic correspondence, and Tier 3 already reads its 16 occupancy facts.

**Mechanism: positive indicator cues only**, drawn from the documents' own printed language.
⚠️ **No threshold change, no `type_matches_document` change** — those are the force-fit risk.

⚠️ **PHASE C'S ACCEPTANCE TEST IS THE FORCE-FIT CHECK:** a **T4** must still decline (not become a `w2`),
a **compensation statement** must reach `compensation_statement` (not `commission_income_statement`), and a
**portal screenshot** must hold. **Undoing LP-463 would be worse than the regression this fixes.**

---

## What was done (LP-434 → LP-475)

### The extraction build-out
108 JSON specs in `docs/schema-specs/` (**the source of truth**) · a generator with a validator that
**refuses rather than emitting broken code** · 91 generated extractors · **+232 typed fields and 9 lists**
added to the original 18 · Tier 2 merged into Tier 1 · the schema/catalog vocabularies reconciled (109 of 109
resolve).

### The mechanisms
- **Generic nested lists** (LP-437) — `ListRow` + `DocumentEntry.lists` + `_LIST_SPECS`, replacing ~5
  hand-written files per list. ⚠️ **The legacy `transactions` / `schedule_c` / `schedule_e` attributes
  COEXIST and were deliberately NOT migrated** — AS-1, IN-12, IN-13 are live on them.
- **Cross-source AI over lists** (LP-444) — per-group `include_lists`, a row cap, **truncation visible as
  truncation**. CR-4 built and inert.
- **The tag→field guard** (LP-450) — parsed loan/borrower `data` references validated at load.
- **Three model tiers** (LP-457) — ⚠️ **12 reasoning callers previously shared the extraction setting;
  collapsing them would invalidate every calibrated bar.**

### The v2 remediation (after the bench re-run)
- **LP-471 — the Tier-3 fallback.** ⚠️ **The highest-leverage change.** A no-extractor type or an extraction
  error now falls back to scoped free extraction. **~59 documents went from nothing to something**, incl. 069
  (a 118-page package the typed path cannot handle). **Fallback runs AFTER retries** — a throttle is
  re-runnable and must not be silently degraded.
- **LP-472 — one shared identity schema** for passport / PRC / EAD / government_issued_id, **classified
  precisely, extracted in common.** Three prior misreads in this family; a shared schema makes the next one
  cheap. `drivers_license` keeps its own working extractor.
- **LP-473 — the 3 remaining extractor failures: none was an extraction bug.** 069 → splitter · 174 → the
  image gap (already fixed by streaming) · 222 → a transient all-null, confirmed by re-run (14/16 today).
  **Found en route: the bench read `failure_reason` when the attribute is `reasoning`, so EVERY failed
  extraction recorded a blank cause** — affects both bench reports.
- **LP-474 — the accuracy layer.** One primitive: *"two extracted values that must differ came out equal."*
  **3 of 3 targets caught, 0 false positives across 303 documents.** **FLAG, never correct.** Deterministic —
  no model call.

---

## ⚠️ The lessons that must survive

**Schema presence ≠ data availability.** Verify a field is populated AND its values usable **on real
documents** before declaring a tag on it. (ADR-354)

**Verification rate varies by document structure.** **Tables** — 7/7 claims real. **Fixed-layout forms** —
high. ⚠️ **Free-text contracts — mostly wrong**: of ~8 purchase-agreement claims, **one** was real; the free
reader projected **Texas** TREC fields onto a **North Carolina** form.

**Precision beats recall on a field with a confusable neighbour.** IH-1's fix was **reverted** — it failed to
populate the one real case and wrongly populated a control. *"A wrong value is worse than the null."*
**And it recurs at row granularity** (LP-460: 11 rows → 5 by framing the unit precisely).

**Three classification failure modes, and only two yield to prompts:**
| failure | fix |
|---|---|
| the model contradicts itself | LP-463's `type_matches_document` guard ✅ |
| **confidently wrong, self-consistent** | a sharpened indicator ✅ |
| **the input is unreadable** (rotated/low-res scans) | ⚠️ **preprocessing — neither works** (ADR-365) |

**Confidence does not predict correctness.** Misclassifications ran **0.75–0.99**. **Never add a confidence
threshold.**

**A spec edit does not reach a shipped prompt.** The generator runs diff-mode for shipped extractors.
⚠️ **89 of 109 prompts are untouched STARTER placeholders**; only 19 are hand-tuned — **and those are the
types that performed at parity.** Prompt changes go in the `.txt`, **under that prompt's own naming**
(specs and prompts diverge: `institution_name` vs `bank_name`).

**A "missing extractor" is often a routing problem.** Three cases: EAD → passport · compensation statements →
commission_income_statement · LOX emails → general_correspondence.

**A limit applied to one call path must be checked against every call path.** Classification capped at 15pp,
Tier 3 at 50pp, **typed extraction uncapped** (ADR-370).

**We measured LP-463's benefit and not its cost.** Declining fixed force-fitting and caused over-declining.
⚠️ **The remedy was NOT to loosen declining — it was to make the failure cheap (LP-471) and fix only
evidence-backed cases (LP-475).**

---

## Priya's rulings — `docs/domain/priya-rulings-2026-08.md`

**Earnings classification** — a decision procedure, not a label list: not cash → NONCASH (qualifying 0) ·
guaranteed + fixed + not performance-dependent → BASE · performance-dependent → VARIABLE · **else UNKNOWN and
request the employer's earning-code definition.** ⚠️ **The UNKNOWN branch is load-bearing.**

**Declining income** — ⚠️ **supersedes LP-393-6.** **Per component, not per borrower.** Base declining with
bonus rising is `NEEDS_REVIEW`. **Do not make "any YoY decrease" automatic.**

**NSF** — an **internal policy**, not an agency rule. **Event type matters.**

**Agency differences** — ⚠️ **architectural.** Store all agency rules and select the applicable one;
**never the strictest**; a lender's conservative choice is an explicit `LENDER_OVERLAY`. When the agency is
unselected, **return comparative results.** ⚠️ **`activation_bars.yaml` holds ONE threshold per rule and
cannot express this — 6 rules are gated on this design decision.**

**Reserves** — ⚠️ **no blanket 60% haircut for Fannie** (that is FHA's).

---

## THE PLAN — finishing the rule engine

**Phase 1 — DONE.** The bench re-run gave fill rates per type (`_SCHEMA_GAPS.md`).
⚠️ **Read fill rate as "available to write a tag against", NOT as "correct".**

**Phase 2 — write tags and rules, deterministic first (~25 rules, no Priya).**
Only against fields the bench shows actually populate (the ADR-354 lesson).
Order: parsed tags → derived recipes → **list consumers** ⚠️ **(60+ lists are captured and NO rule reads any
of them)**. Every tag must pass the LP-450 load-time guard. **37 → ~62.**

**Phase 3 — the agency/overlay design call (6 rules).** ⚠️ **A shape to choose, not a ticket to write.**
CR-9 is 1% (Fannie) vs 0.5% (Freddie/FHA); DT-1 is 50% (DU) vs 36-45% (manual) vs an FHA matrix.
**Decide before building any of the six, or they get built twice.**

**Phase 4 — Priya's batch (~25 rules).** ⚠️ **11 need REAL FILES** — the fraud lane and the cross-source
matchers (ADR-332: a self-authored fixture leaks its own answer). **This is a document-collection ask, not
just a calendar ask — and it costs API credit**, unlike everything before it. **→ ~87, and ~100 with a
real-file corpus.**

---

## Deferred, with owners

| item | note |
|---|---|
| **The splitter** | 066, 069, 167, 196, 204, 271 — **one file, one label.** 271 dropped ~$164k of wages |
| **Classified-type threading** | ⚠️ **the best idea to come out of LP-472** — thread the classified type into the extractor so a shared/generic extractor anchors on what classification decided. Helps every long-tail extractor **and the Tier-3 fallback** |
| **Image preprocessing** | ADR-365 — rotated/low-res scans (266, 294, 174). **Neither the guard nor an indicator can fix these** |
| **bank_statement Option 3** | `ending_balance` is the FIRST account only — live for AS-3/AS-4/AS-10. Option 1 recovered the balances; **the second account's transactions are still uncaptured** |
| **The 89 untuned prompts** | long-tail quality |
| **244's Box 10** | deferred as *"needs a typed Box-10 field"*, not uncatchable — the day it exists, an accuracy check drops in free |
| **253's $224k gift** | ⚠️ genuinely uncatchable by self-consistency — a lone amount with no internal contradiction. **The boundary of that layer** |

---

## Standing disciplines

- **Tags describe, rules judge.** No conclusion in a tag; no threshold in an extractor; **no computed totals**
  (247's "$195,000 total compensation" was deliberately not captured).
- **Fail closed.** Absent ≠ empty ≠ unknown. **Never a fabricated default.**
- **Never accuse on a missing document.**
- **Nothing activates without a measured bar.**
- **The five gates before writing a rule:** vacuous? redundant? inputs available? expressible? calibrated?
- **`SNAPSHOT_VERSION` stays 4** — a bump breaks the committed golden fixture (74 failures, LP-421).
- **Never migrate the legacy list attributes.**
- **Ticket shape that works:** a Phase A that **STOPS and reports** before building · *"the documents are the
  gate of record — they beat my ticket text"* · a **regression check on the neighbouring types** (run in 7
  tickets, held every time) · **report cost before any model call** · **commit locally, never push**.
