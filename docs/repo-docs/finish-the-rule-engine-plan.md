# Finishing the rule engine — brief plan

_2026-08-10. **37 live of ~113 real targets.** The last several weeks built the input layer; the rules are
still where they were._

---

## Why the count has not moved

LP-434 → LP-470 was **extraction and classification** — making documents readable. **That is the foundation,
not the building.** A rule cannot read a field that does not exist, but creating the field does not create
the rule.

---

## The ~76 remaining, by blocker _(from the LP-451 five-gate audit)_

| blocker | rules | needs |
|---|---|---|
| **AI calibration** | ~25 | Priya's labels + a bar |
| ↳ **of those, REAL FILES** | **11** | ⚠️ ADR-332 — a self-authored fixture leaks its own answer |
| A tag declaration | ~16 | ⚠️ **the bench re-run first** |
| A derived recipe | ~10 | code |
| Re-extraction to make fields measurable | ~15 | ⚠️ **the bench re-run** |
| **The agency/overlay design** | **6** | ⚠️ **a decision, not a ticket** |
| A missing extractor | ~6 | MI certificate, rate lock |
| **Vacuous** | 5 | never write |

---

## PHASE 1 — Read the bench re-run _(running now)_

**The baseline to compare against:** 889 docs · 748 at ≥0.9 · 88 unknown · 54 misclassified · 74 capturing
nothing.

**What to read, in order:**
1. **Fill rates on the ~40 new fields and 6 new lists** — ⚠️ **this is the deliverable.** It tells you which
   tags can be written against evidence rather than a schema declaration.
2. The unknown count — seven new types should absorb most of it.
3. The misclassification rate — the decline mechanism, the guard, and the sharpened indicators.
4. The captured-nothing count — CD, LE, 1098 and the EAD now extract.

⚠️ **Read fill rate as "available to write a tag against", NOT as "correct".** Document 244 returned a
confident wrong Box 1. **Coverage is not accuracy.**

---

## PHASE 2 — Write tags and rules, deterministic first _(~25 rules, no Priya)_

**Only against fields Phase 1 shows actually populate.** ⚠️ **This is the LP-454 lesson**: three tag-writing
attempts under-delivered because the audit measured what schemas *declared*, not what documents *contained*.

**Build order, cheapest leverage first:**
- **The parsed tags** — a field that populates + a declaration
- **The derived recipes** — each mirrors one that already exists
- **The list consumers** — 60+ lists are captured and **no rule reads any of them.** An enumerator (per-row
  subject, the AS-1 pattern) or a recipe (aggregate, the IN-12 pattern)

⚠️ **Every tag must pass the LP-450 load-time guard** — a reference outside the legal universe now fails
loudly instead of silently resolving to absent.

**Realistic: 37 → ~62.**

---

## PHASE 3 — The agency/overlay design call _(6 rules — a DECISION)_

**Priya's ruling is unambiguous** (`docs/domain/priya-rulings-2026-08.md`): *store all agency rules and select
the applicable one; **never the strictest**; a lender's conservative choice is an explicit `LENDER_OVERLAY`,
not disguised agency policy.* When the agency is not yet selected, **return comparative results.**

⚠️ **`activation_bars.yaml` holds ONE threshold per rule and cannot express this.**

**Concretely:** CR-9's deferred-student-loan payment is **1% (Fannie)** vs **0.5% (Freddie/FHA)**. DT-1 is
**50% (DU)** vs **36-45% (manual)** vs **an FHA compensating-factor matrix**.

**Gates:** CR-9 · DT-1 · AS-3 · PC-4 · PR-1 · CR-7's minimum.

⚠️ **This is not a ticket to write — it is a shape to choose.** Do it before building any of the six, or they
get built twice.

---

## PHASE 4 — Priya's batch _(~25 rules)_

**Three kinds of input, and they are not interchangeable:**

**Decisions in conversation** — the earnings classification procedure is already ruled; what remains is her
NSF tier confirmation and any threshold not yet given.

**Labelling sessions** — a blind worksheet per tag, her filling a `golden_label` column, then scoring against
the AI's answers and a bar she approves. **~20 minutes per 30 rows** (the LP-420 measure). **Batch them** —
one session beats five.

⚠️ **11 rules need REAL FILES** — the fraud lane (FR-1/2/3/6) and the cross-source matchers (CR-4, OC-1, RE-1,
PC-1, TI-1, TI-2, AU-1). **A fixture you author leaks its own answer.** **This is a document-collection ask,
not just a calendar ask.**

⚠️ **And it costs API credit** — scoring re-runs the reasoner over each worksheet. Everything before this
phase is nearly free; this one is not.

**Realistic: → ~87, and → ~100 with a real-file corpus.**

---

## Running alongside — not blockers

| item | why it can wait |
|---|---|
| **The accuracy-audit layer** | ⚠️ **do it BEFORE tags at scale** — a tag on a wrong value is worse than one on a missing value. Document 244 is the motivating case |
| The splitter | 066, 069, 167, 204, 271 — one file, one label |
| Bank statement Option 3 | `ending_balance` is the FIRST account only; live for AS-3/AS-4/AS-10 |
| The 89 untuned prompts | long-tail quality; the 19 tuned types are the ones that performed at parity |
| Image preprocessing | rotated ID cards default to `passport` — neither the guard nor an indicator can fix it |

---

## The honest arc

**37 → ~62** on your own, after the bench re-run.
**→ ~87** with Priya's calibration.
**→ ~100** with a real-file corpus.

**5 are vacuous and will never be written. 7 compliance rules are out of scope. ~6 need extractors that do
not exist.**

⚠️ **The binding constraints are a document corpus, a domain expert's time, and one design decision — not
engineering.**
