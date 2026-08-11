# mortgageboss-ai — full project brief

_Written 2026-08-11 for a fresh chat. Read top to bottom once; after that use it as a reference._

This is the **whole arc** — Phase 1 through the current work — assembled from every phase plan in
`docs/phases/`, the current architecture docs, and the in-flight ticket. If you only need today's state,
`docs/handoff-summary-2026-08-11.md` is the short version and this document is its context.

---

## 0. TL;DR — what to know in 60 seconds

**The product.** A standalone loan-processing assistant for mortgage **processors** (not underwriters,
not borrowers). It helps a processor assemble a **complete, accurate loan file** — documents, extracted
data, verification findings, conditions — before submission to underwriting. Monorepo: Python/FastAPI
backend, Next.js frontend.

**Where it is.** Phases 1, 1.5 and 2 are **closed**. Phase 3 (the verification engine) is the live work
and has been for months. The engine is **built**; the **rule content** is the remaining project.

**The one number that matters:** **37 rules live** of ~113 real targets. That number has not moved
through LP-434 → LP-475, because those tickets built the *input layer* (extraction + classification),
not rules.

**The binding constraints are not engineering.** They are: a **real-document corpus**, the **domain
expert's time** (Priya), and **one design decision** (agency/overlay shape). Everything else is known work.

**The single most important discipline:** *a wrong value is worse than a missing value.* A missing field
returns `couldnt_check` and a human looks at it. A wrong field returns a confident wrong verdict and
nobody knows. Almost every hard-won lesson in this project is a corollary of that sentence.

---

## 1. Orientation — paths, people, mechanics

### Key paths
```
repo              ~/Geet/project/loan-processing/mortgageboss-ai   (branch: phase3_bucket_2)
bedrock worktree  ../mbai-bedrock                                  (branch: bedrock_integration)

extraction specs  docs/schema-specs/*.json      ← THE SOURCE OF TRUTH for every extractor (121 files)
rule specs        backend/app/verification/rules/specs/*.yaml      (45 written, 37 active)
rule/tag data     backend/app/verification/rules/
                    fact_tags.csv · rule_tags.csv · rule_kinds.csv
                    tag_production.yaml · tag_dependencies.csv
                    activation_bars.yaml · vocabulary_extra.yaml
Priya's rulings   docs/domain/priya-rulings-2026-08.md
tickets           docs/tickets/LP-*.md          (342 files)
ADRs              decisions.md                  (through ADR-373, ~14k lines)

bench tool        backend/app/dev/bench/ + /dev/extraction-bench   (DEV ONLY; 404s in production)
bench output      ~/Geet/project/loan-processing/mb_quality_check/
                    mortgageboss-batch-bench-out/8c999b3f7a1b/     ← the v2 run, 303 docs
                    _records.jsonl                                 ← consolidated records
comparison        ~/Geet/project/loan-processing/comparison-output/
source documents  ~/Geet/project/loan-processing/mortgageboss-batch/
```

### The people
- **Geet** — the engineer/owner. Makes the product and scoping calls.
- **Priya** (referred to in older docs as "sister") — the **resident domain expert**, a working mortgage
  processor. She is the ground truth for every mortgage-domain question, every threshold, and every
  judgment label. **When unsure about a mortgage term or a number, flag it — never guess.**

### Working mechanics (non-negotiable)
- **Commits are local. Geet pushes manually. NEVER push.**
- **Ask before committing** — show the staged diff and the proposed message, wait for approval. When
  Geet says "commit", commit directly with the written message; don't re-ask. Commit messages need a
  descriptive **body** (what/why bullets), not just a subject.
- **Report cost before any model call.** Recent tickets ran $0.05–0.30; the 889-doc bench cost ~$18.
  **Never re-run the full bench casually** — read the stored extractions instead.
- **File attachments have arrived EMPTY.** Paste text into the message rather than attaching.
- **Every ticket writes `docs/tickets/LP-XXX.md`** (what was done, assumptions, decisions).
  Architectural decisions become a new **ADR in `decisions.md`**.
- **CI must stay green:** ruff + mypy (strict) + pytest for backend; biome + tsc + build for frontend.
- Watch out: `detect-secrets` trips on Alembic revision hashes and password/secret literals — add
  `# pragma: allowlist secret` and `git add .secrets.baseline` when the hook rewrites it.

### The ticket shape that works
1. A **Phase A that STOPS and reports** before building anything.
2. *"The documents are the gate of record — they beat my ticket text."*
3. A **regression check on the neighbouring types** (run in 7 tickets, held every time).
4. Report cost before any model call.
5. Commit locally, never push.

---

## 2. The phase history — how it got here

### Phase 1 — Foundation (LP-1…LP-50) — **complete**
Six epics: repo/infra/CI, the full data model (multi-tenancy, loan files, borrowers, property,
documents, extractions, findings, needs, activity log), JWT auth + tenant scoping, loan-file CRUD +
dashboard, document upload → Celery classify/extract pipeline, then testing/polish/seed data.

Principles established here and still binding:
- **The database is the source of truth. AI never touches it directly** — typed tools only.
- **Stated vs verified data tracked separately.**
- **Soft delete · versioning of derived data · audit/activity log · `company_id` scoping everywhere.**
- Async-first (no sync DB calls), SQLAlchemy 2.x `Mapped[...]`, Pydantic v2, fully typed under strict mypy.

### Phase 1.5 — MISMO import (LP-51…LP-57) — **complete**
A **deterministic** (no AI) tolerant lxml/XPath parser for MISMO XML/HTML → stated-financials models →
mapping/creation service → upload endpoint → frontend display → full editability. Import-directly (no
preview/confirm) **with post-import editability as the safety net** for parser gaps.

⚠️ **Hardening honesty:** validated against **one real file** plus synthetic variants. More real files
(especially a real FHA and a real multi-borrower export) are still needed.

**Deferred:** re-import/versioning/diff, smart-needs-from-MISMO, AI-fallback parsing.

### Phase 2 — Document handling (LP-58…LP-73) — **complete**
- **Three-tier document model** — Tier 1 first-class extraction, Tier 2 recognize-and-summarize,
  Tier 3 long-tail generic analysis; catalog-driven routing after classification.
- ~18 Tier-1 extractors, comprehensive classification across ~80 types, `DocumentFinding`.
- **The needs list — the product differentiator.** Deterministic engine (five states, satisfaction
  matching, **per-file serialization** so simultaneous uploads can't race, a thin deterministic floor),
  plus **AI reasoning that proposes needs with explicit reasoning** and a human confirm step.
- Versioning + staleness (Model-C explicit replace), tier-aware detail view, standard naming, package
  qualification groundwork.
- **The phase's lesson:** four bugs passed unit tests and broke *in the seams* → real-stack integration
  tests (real storage/DB/pipeline, AI mocked only at the model boundary) became the standard.

### Phase 3 — Verification (LP-74 onward) — **the live work, and it has been rearchitected twice**

Phase 3 is where most of the project's history lives. It went through four successive designs:

**Design 1 (LP-74…LP-98) — the deterministic rule engine.** A uniform rule structure with
threshold-as-data, three-layer composition (regulatory → investor → **lender overlay as a diff**),
DTI/LTV calculators that show their whole derivation, an AI cross-source discovery pass, an
**aggression dial** (one AI pass, three views, filtering by confidence at read time), starter lender
overlays (UWM, Sun-West), and the findings UI. Plus refinance correctness (LP-99/100/101) and finding
UX work (readable labels, normalized-substance dedup, four-part cards, AI why/fix, View-fix preview, undo).

**Design 2 (Phase 3.5, LP-115…LP-142) — rules as data.** The LP-115 audit was the turning point: it
found **only 5 rules actually fired**, 13 cross-source rules were **fact-starved** (wired but their
facts were never populated), and the 107-rule **threshold engine was completely dormant with no caller**.
Response: a `verification_rules` table fed by a git-tracked seed, an applicability filter with an
explicit **awaiting-data** state, an evaluator library, and a **DET-FUZZY** confidence model (a fuzzy
match yields computed confidence < 1.0 — "Novant" vs "Novant Health" must not be a false finding).

**Design 3 — the fact-tag architecture.** The pivot that stuck. Instead of 130 AI evaluators:
**AI structures raw facts into clean *tags*; deterministic code queries the tags and does the arithmetic.**
A two-layer snapshot (raw + tags), tags citing raw facts by stable content-id, a tag dependency DAG with
confidence propagation, and a **fail-closed gate** (required tag absent → `couldnt_check`; load-bearing
tag `unknown` → `couldnt_check`; below the confidence floor → `needs_review`; contradiction →
`needs_review`).

**Design 4 (`verification-architecture-v2.md`) — the current architecture.** See §3.

Along the way the work was organised into **buckets** (`phase3_bucket.md`, `phase3_bucket2.md`) and
**category waves** (`phase3_categories.md`, `phase3_new_order.md`) — the census that produced today's
"~113 in-scope rules" picture and the finding that **the extractors, not the rules, are the mountain**.

---

## 3. The current architecture (read this section carefully)

### The inversion
The old default was: deterministic Python is the evaluator spine, AI only perceives. Real build
experience killed it — encoding a decision path for every edge case doesn't scale, and the
determinations that matter (what income qualifies, whether a deposit is sourced, whether a story is
plausible) are **judgment, not arithmetic**.

**Current default: AI evaluates; deterministic code is demoted to a narrow integrity check.**
Adding or changing a rule means **writing a spec, never writing an evaluator**. That's the property
that scales to file diversity.

### The pipeline, every run
```
Documents (MISMO XML, PDFs)
      │
      ▼
1. AI EDGE — fact production        extract PDF fields · classify docs · return UNKNOWN when unsure
      │
      ▼
2. FROZEN SNAPSHOT   ← the boundary; no AI writes facts past here
      │                       (raw layer + tag layer; absent ≠ empty ≠ unknown; provenance on every fact)
      ├──────────────────────────────┐
      ▼                              ▼
3a. RULE EVALUATION                3b. CROSS-SOURCE LANE (whole file, undeclared inputs)
    verdict + operative values         surfaces tensions no rule anticipated
      │  threshold rules                │  matches a rule → feeds it as evidence
      ▼                                 │  novel → "AI found — verify"
   NUMERIC-INTEGRITY CHECK              │  recurring → graduates into a scoped rule
   re-runs ONLY the final X vs Y        │
      └──────────────┬─────────────────┘
                     ▼
4. FINDING LIFECYCLE — four states, (rule_id, subject_key) identity, append-only log
```

**The snapshot is stateless** (rebuilt and discarded each run — the run is a pure function).
**Findings are stateful** (persist across runs, matched by identity).

### What stays deterministic — and only this
1. **Snapshot freeze** — facts assembled once and frozen, so a run is replayable.
2. **Numeric-integrity check** — for a threshold rule, code re-runs *only* the terminal comparison on
   the values the AI surfaced. Not the income computation, not the sourcing judgment. **One function,
   not 130.** It exists because comparing two established numbers is the one thing LLMs do unreliably.
3. **The calculators** (DTI / LTV / MI / reserves) — they own computed-ratio conclusions, and the
   cross-source lane stays out of their territory.

### Four states, four tabs — the honesty contract
| State | Meaning | Blocks submit? |
|---|---|---|
| `open` | fired, awaiting fix | **yes** |
| `satisfied` | ran and passed, evidence linked | no |
| `no-longer-applies` | the checked thing genuinely stopped existing | no |
| `couldn't-check` | rule applies but a required document/fact is missing | **yes** |

Tabs: **Needs attention** (`open` + `couldn't-check` — both block) · **Satisfied** ·
**History/no-longer-needed** · **Not applicable** (scope was false for this file).

⚠️ **The three "not firing" cases must stay distinct**, and collapsing any into another is the core
failure mode:
- **Stopped existing** → `no-longer-applies` (was a finding; subject left the file)
- **Never relevant** → not-applicable (scope false from run one; never a finding)
- **Lost visibility** → `couldn't-check` (rule applies, thing might exist, we can't see it) — **blocks**

**Not-applicable must never absorb couldn't-check.** "Doesn't apply to this file" vs "we couldn't
verify" is the whole honesty contract.

### Identity and reconciliation
- **Identity = `(rule_id, subject_key)`.** `subject_key` = the specific deposit/borrower/tradeline/
  property, or `whole_file` — derived from **durable attributes, never array position**.
- Uniqueness `(loan_id, rule_id, subject_key)` — so IN-5 on borrower A and borrower B are independent
  findings with independent states.
- **Immortality:** once a finding fires it never leaves the surface silently — it only moves to a
  visible, labelled state with a reason and a timestamp. Append-only event log answers "where did this
  go, and why?"

### The cross-source discovery lane
Structurally different: its value is that it **does not declare its inputs**. It reads the whole file
and surfaces tensions no rule anticipated. **Locked caution:** it is the least reproducible, least
auditable part of the engine *by design*, and is acceptable only because discovery findings are labelled
and human-verified — they never block submission on their own authority. Every claimed discrepancy must
**name the specific documents and values in tension** (a discrepancy it can't point at is a hallucination).

### Model tiers (LP-457)
Bedrock. **Haiku 4.5 for classification + extraction; Sonnet for reasoning.**
⚠️ **12 reasoning callers previously shared the extraction setting — collapsing the tiers would
invalidate every calibrated bar.**

---

## 4. Extraction — the layer built over the last several weeks

### The schema standard (`docs/extraction-schema-standard.md`)
The first 18 schemas were designed *before the rules existed*, from "what does a mortgage decision need?"
The consequence surfaced in LP-431: rule **IH-1** needs the dwelling's loss-settlement basis; the AI read
it correctly on three insurance documents, but **the schema never asked for it**, so the value landed in
the free-form catch-all — which is **discarded at the snapshot boundary**. The rule was dead and nothing
reported an error.

> **The AI's reading ability is not the ceiling. The field list is.**

**A field earns a place in `typed_core` only if it passes one of six tests:** (1) a rule reads it ·
(2) it is PII · (3) it identifies/attributes the document · (4) a processor uses it · (5) it
**disambiguates** one of the above · (6) nothing → **leave it out**, the catch-all captures it.

**The disambiguator rule** — *a field without its disambiguator is a field you can misread confidently.*
Three real homeowners policies encode the settlement basis three ways (an explicit flag with a
contradictory personal-property flag beside it; only an ISO form code `HO 00 03`; prose). An extractor
searching for "replacement cost" finds it on all three and can invert the answer.

**Hard constraints:**
- Five coercers only: `str`, `Decimal`, `date`, `int`, `page`. No `bool`, no validated `enum`, no
  `percent`. **Money stays a string** and is coerced to `Decimal` on read.
- Output ceiling **16,384 tokens** (`RETRY_MAX_TOKENS`). Use **flat rows** for anything with many items.
- **Absent ≠ empty.** Missing field → `null`. Missing list → `[]`. Missing object → `null`.
  **Never fabricated, never omitted.**
- ⚠️ **The catch-all is not PII-protected.** Anything the model files into `additional_sections` is
  stored **raw** — a real address and an SSN were found unmasked there. Every PII element must be a
  named typed field registered in `_PII_FIELDS`.
- ⚠️ **A rule may only depend on a typed-core field** (LP-405). The catch-all is free-form, per-document
  and uncoerced — nothing built on it can be trusted.

**Target: ~20–25 typed-core fields per document, every one with a recorded reason.**
**Sequencing follows rule count, not the alphabet:** 75 of 99 document types serve exactly one rule; the
top 8 documents cover 70 of 133 rules (52%).

### What LP-434 → LP-475 delivered
- **121 JSON specs in `docs/schema-specs/`** — the source of truth — plus a **generator with a validator
  that refuses rather than emitting broken code**, and 91 generated extractors.
- **+232 typed fields and 9 lists** on top of the original 18 types; **109+ document types** wired
  (was 18); **60+ nested lists** captured.
- **Generic nested lists** (LP-437) — `ListRow` + `DocumentEntry.lists` + `_LIST_SPECS`, replacing ~5
  hand-written files per list. ⚠️ **The legacy `transactions` / `schedule_c` / `schedule_e` attributes
  COEXIST and were deliberately NOT migrated** — AS-1, IN-12, IN-13 are live on them.
  **Never migrate the legacy list attributes.**
- **The tag→field guard** (LP-450) — a tag referencing a field outside the legal universe now **fails
  loudly at load** instead of silently resolving to absent.
- **Three model tiers** (LP-457), Tier 2 merged into Tier 1, schema/catalog vocabularies reconciled.

### The v2 bench (run `8c999b3f7a1b`, 303 documents) — the measurement that shapes everything now
Apples-to-apples on the 276 documents both runs processed:

| metric | v1 | v2 | |
|---|---|---|---|
| Succeeded with a schema | 194 | **229** | ▲ +35 |
| no_extractor | 64 | **44** | ▼ −20 |
| Extractor failures | 10 | **3** | ▼ −7 |
| Classification AI-call failures | 8 | **0** | ▼ eliminated |

Every field and list gap v1 flagged now populates. Crash clusters gone. T4s no longer emit
plausible-but-wrong US W-2 numbers; doc 271 recovered ~$164k of wages lost to a `1099` mislabel.

**⚠️ And the cost side, which is the finding that matters:**
1. **~14 documents that v1 extracted now drop to `unknown`.** LP-463 made declining legitimate —
   correctly — but the classifier now abstains where a specialised type exists *and its extractor works*.
   **We measured declining's benefit and never measured its cost.**
2. **Nine new accuracy errors — the confident-wrong class.** A fabricated Texas state income tax (Texas
   has none); a gift amount read as **$224,307.94 instead of $24,307.94**; a 1098 taxes field echoing
   the interest value; hallucinated driver's-licence values on hard scans.
3. Carried-over bugs: `loan_number_masked` **stores the unmasked number** (a PII violation whose field
   name conceals it); `pay_stub.employee_ssn_masked` holding bank/SIN digits; `credit_report.date_opened`
   fabricating a day-of-month from MM/YY.

**The remediation sequence that followed, and completed:** fallback → regressions → accuracy layer → tags.
- **LP-471 — the Tier-3 fallback.** ⚠️ **The highest-leverage change of the whole run.** A no-extractor
  type or an extraction error now falls back to scoped free extraction. **~59 documents went from
  nothing to something.** Fallback runs **AFTER** retries — a throttle is re-runnable and must not be
  silently degraded.
- **LP-472** — one shared identity schema for passport / PRC / EAD / government_issued_id: *classified
  precisely, extracted in common*. `drivers_license` keeps its own working extractor.
- **LP-473** — the 3 remaining extractor failures: **none was an extraction bug** (a splitter case, an
  image gap already fixed by streaming, and a transient all-null confirmed by re-run). Found en route:
  the bench read `failure_reason` when the attribute is `reasoning`, so **every failed extraction had
  recorded a blank cause**.
- **LP-474 — the accuracy layer.** One primitive: *"two extracted values that must differ came out
  equal."* **3 of 3 targets caught, 0 false positives across 303 documents. FLAG, never correct.**
  Deterministic — no model call.
- **LP-475** — fix only the clear reclassification regressions. See §7.

---

## 5. The rule engine — where the 37 come from and what gates the rest

### The shape of a rule
Rules are **data, not code**: a YAML spec in `backend/app/verification/rules/specs/` naming its
criteria, applicability, required tags, kind, reference values, and evidence. It reads **tags** produced
by declared producers, never raw documents.

- **Tags describe; rules judge.** No conclusion in a tag; no threshold in an extractor; **no computed
  totals** (a "$195,000 total compensation" figure was deliberately not captured).
- Rule kinds: **calculative** (arithmetic) · **structural** (presence/match/count) · **judgmental**
  (needs AI + calibration) · **out-of-scope**.
- **The five gates before writing a rule:** vacuous? redundant? inputs available? expressible? calibrated?
- **Nothing activates without a measured bar.** A judgmental rule ships `validated: false` and goes live
  at full confidence only after Priya confirms its number (`activation_bars.yaml`).

### The ~76 remaining, by blocker (from the LP-451 five-gate audit)
| blocker | rules | needs |
|---|---|---|
| **AI calibration** | ~25 | Priya's labels + a bar |
| ↳ **of those, REAL FILES** | **11** | ⚠️ ADR-332 — a self-authored fixture leaks its own answer |
| A tag declaration | ~16 | the bench re-run first (**done**) |
| A derived recipe | ~10 | code |
| Re-extraction to make fields measurable | ~15 | the bench re-run (**done**) |
| **The agency/overlay design** | **6** | ⚠️ **a decision, not a ticket** |
| A missing extractor | ~6 | MI certificate, rate lock |
| **Vacuous** | 5 | never write |

Plus **7 compliance rules out of scope** (post-submission / LOS territory).

### The four-phase plan to finish (`docs/finish-the-rule-engine-plan.md`)
- **Phase 1 — read the bench re-run. DONE.** Fill rates per type are recorded.
  ⚠️ **Read fill rate as "available to write a tag against", NOT as "correct."** Doc 244 returned a
  confident wrong Box 1. **Coverage is not accuracy.**
- **Phase 2 — write tags and rules, deterministic first (~25 rules, no Priya).** Only against fields the
  bench shows *actually populate* (the ADR-354 / LP-454 lesson: three prior tag-writing attempts
  under-delivered because the audit measured what schemas **declared**, not what documents **contained**).
  Build order: parsed tags → derived recipes → **list consumers**. ⚠️ **60+ lists are captured and NO
  rule reads any of them.** Every tag must pass the LP-450 load-time guard. **37 → ~62.**
- **Phase 3 — the agency/overlay design call (6 rules).** ⚠️ **A shape to choose, not a ticket to write.**
  See §6.
- **Phase 4 — Priya's batch (~25 rules).** Labelling sessions: a blind worksheet per tag, she fills a
  `golden_label` column, then we score the AI's answers against a bar she approves. **~20 minutes per 30
  rows** (the LP-420 measure) — **batch them.** ⚠️ **11 rules need REAL FILES** (the fraud lane FR-1/2/3/6
  and the cross-source matchers CR-4, OC-1, RE-1, PC-1, TI-1, TI-2, AU-1). ⚠️ **And it costs API credit** —
  everything before this phase is nearly free. **→ ~87, and ~100 with a real-file corpus.**

**The honest arc: 37 → ~62 on your own → ~87 with Priya → ~100 with a real-file corpus.**

### The extractor mountain
~55 of the remaining in-scope rules sit behind **absent extractors**. The real Bucket-4 gate narrowed to
**five documents**: **credit report** (13 rules — the largest single category, nested tradelines/scores/
public records/inquiries), **appraisal** (8 — UAD 2.6 *and* 3.6 through the Nov 2026 cutover), **title**
(6), **DU/AUS findings** (4), **MI certificate** (5). Plus condo questionnaire and flood.

⚠️ **Each of these documents is PDF-only with no independent source-of-truth: a misread produces a
confident wrong verdict with nothing to contradict it.** Every one needs an **LP-143 golden-file eval
built alongside it** — non-negotiable. This is where the eval infrastructure matters most.

There is also a **second, cheaper tier**: fields missing from extractors that already run (seller credit,
addenda, personal property, contingency dates for PC-4/6/8/9; `loss_settlement_basis` for IH-1; the
youngest child's age for the child-support rule, after which that rule is pure arithmetic). These are
bounded extensions — and useful rehearsals for the golden-file discipline the absent extractors demand.

**The tripwire pattern, worth reusing:** LP-431 left a **guard test that passes while the blocker exists
and turns red the moment someone removes it**, signalling that IH-1 is now buildable. That beats a note
in a document — it puts the "this is now unblocked" signal in front of whoever does the unblocking, at
the moment they do it.

---

## 6. Priya's rulings — the domain layer (`docs/domain/priya-rulings-2026-08.md`)

**Earnings classification — a decision procedure, not a label list:** not cash → NONCASH (qualifying 0) ·
guaranteed + fixed + not performance-dependent → BASE · performance-dependent → VARIABLE · **else UNKNOWN
and request the employer's earning-code definition.** ⚠️ **The UNKNOWN branch is load-bearing.**

**Declining income** — ⚠️ **supersedes the earlier design.** **Per component, not per borrower.** Base
declining with bonus rising is `NEEDS_REVIEW`. **Do not make "any YoY decrease" automatic.**

**NSF** — an **internal policy**, not an agency rule. **Event type matters.**

**Reserves** — ⚠️ **no blanket 60% haircut for Fannie** (that is FHA's).

**Agency differences — ⚠️ architectural, and this is the open design decision.**
> *Store all agency rules and select the applicable one; **never the strictest**; a lender's conservative
> choice is an explicit `LENDER_OVERLAY`, not disguised agency policy. When the agency is not yet
> selected, return comparative results.*

⚠️ **`activation_bars.yaml` holds ONE threshold per rule and cannot express this.** Concretely: CR-9's
deferred-student-loan payment is **1% (Fannie)** vs **0.5% (Freddie/FHA)**; DT-1 is **50% (DU)** vs
**36–45% (manual)** vs **an FHA compensating-factor matrix**. Gated rules: **CR-9 · DT-1 · AS-3 · PC-4 ·
PR-1 · CR-7's minimum.** **Decide the shape before building any of the six, or they get built twice.**

---

## 7. In flight right now

**LP-475 — fix ONLY the clear reclassification regressions. Phases A/B/C complete; ticket written.**

Phase A triaged 10 candidates against the **stored v2 records** (no model calls, $0). **3 qualified**
under a three-part rule — the lost type must have a **registered, working extractor**, **proven on a
sibling** in this corpus, and the document must be **genuinely that type**:
- **202** `title_commitment` — siblings 201/203 are the same invoice+CPL+commitment bundle and classified
  fine.
- **208, 209** `earnest_money_receipt` — 1-page "ACKNOWLEDGMENT OF RECEIPT OF MONIES", identical to
  proven sibling 207.

**7 correctly stay declining:** 204/196 are multi-doc **packages** (the splitter's job) · 132 is a portal
screenshot · 177/178 are lease **addenda** (an addendum is not a lease) · **211 fails rule #2 — zero
documents in the whole corpus ever classified that type, so its extractor is unproven** · **236** is an
occupancy LOX **in Gmail form** (an occupancy explanation by *content*, an email by *form*) — any cue
tight enough to catch it would key on content, which is exactly how generic correspondence gets pulled
back in. Tier 3 already reads its 16 occupancy facts.

**Mechanism: positive indicator cues only**, drawn from the documents' own printed language ("ACKNOWLEDGMENT
OF RECEIPT OF MONIES"; "Schedule A/B"; "BINDER (ALTA)"). ⚠️ **No threshold change, no
`type_matches_document` change** — those are the force-fit risk. One file touched:
`backend/app/ai/classification_prompt.py`.

**Phase C's acceptance test is the force-fit check, and all three held:** a **T4** still declines
(`unknown @ 0.90`, never `w2`) · a **compensation statement** reaches `compensation_statement` (never
`commission_income_statement`) · a **portal screenshot** still declines. **Undoing LP-463 would be worse
than the regression this fixes.**

Proof cost **$0.1993** on 8 documents (bench run `5ea072872fa7`); the 303-doc bench was **not** re-run.
`ACTIVE_RULE_IDS` = **37**, unchanged (digest `c970b53268f7`). Suite green: 4191 passed.

**Open follow-ups it filed:** `title_commitment` Schedule-B **list-vs-catch-all routing** is unstable on
bundled files (202 came back empty; 201 varied 3→9 rows with no extraction change) · the **splitter** ·
a possible **lease-addendum** type and a home for 236 · `evidence_of_payment` needs a proven example
before any cue.

---

## 8. The lessons that must survive

**Schema presence ≠ data availability.** Verify a field is populated AND its values usable **on real
documents** before declaring a tag on it. (ADR-354)

**Coverage is not accuracy.** A missing field returns `couldnt_check`; a wrong field returns a confident
wrong verdict. Nothing in the pipeline checked correctness until LP-474.

**Verification rate varies by document structure.** **Tables** — 7/7 claims real. **Fixed-layout forms** —
high. ⚠️ **Free-text contracts — mostly wrong:** of ~8 purchase-agreement claims, **one** was real; the
free reader projected **Texas** TREC fields onto a **North Carolina** form.

**Precision beats recall on a field with a confusable neighbour.** IH-1's fix was **reverted** — it failed
to populate the one real case and wrongly populated a control. *"A wrong value is worse than the null."*
And it recurs at row granularity (LP-460: 11 rows → 5 by framing the unit precisely).

**Three classification failure modes, and only two yield to prompts:**
| failure | fix |
|---|---|
| the model contradicts itself (reasoning names one type, label says another) | LP-463's `type_matches_document` guard ✅ |
| **confidently wrong, self-consistent** | a sharpened indicator ✅ |
| **the input is unreadable** (rotated/low-res scans) | ⚠️ **preprocessing — neither works** (ADR-365) |

**Confidence does not predict correctness.** Misclassifications ran **0.75–0.99**. **Never add a
confidence threshold** — it would suppress correct high-confidence calls and still miss the wrong ones.

**A spec edit does not reach a shipped prompt.** The generator runs diff-mode for shipped extractors.
⚠️ **89 of 109 prompts are untouched STARTER placeholders**; only 19 are hand-tuned — **and those are the
types that performed at parity.** Prompt changes go in the `.txt`, **under that prompt's own naming**
(specs and prompts diverge: `institution_name` vs `bank_name`).

**A "missing extractor" is often a routing problem.** Three real cases: EAD → passport · compensation
statements → commission_income_statement · LOX emails → general_correspondence.

**A limit applied to one call path must be checked against every call path.** Classification capped at
15pp, Tier 3 at 50pp, **typed extraction uncapped** (ADR-370). The 069 `BadRequestError` was exactly this:
the classification-side size fix didn't cover extraction.

**We measured LP-463's benefit and not its cost.** ⚠️ **The remedy was NOT to loosen declining — it was
to make the failure cheap (LP-471) and fix only evidence-backed cases (LP-475).**

**Prompt hygiene:** a tag prompt must report what the document states; the *rule* does the judging.
Two prompts were caught smuggling downstream rule concerns into tag prompts — a systematic authoring
error, not bad luck.

**Standing disciplines**
- **Fail closed.** Absent ≠ empty ≠ unknown. **Never a fabricated default.**
- **Never accuse on a missing document.**
- **`SNAPSHOT_VERSION` stays 4** — a bump breaks the committed golden fixture (74 failures, LP-421).
- **Never migrate the legacy list attributes.**
- **No deterministic rule may read Tier-3 free-extraction output** — the labels are model-chosen and the
  values uncoerced, the same reason the catch-all can't back a rule. It's for the processor to see and
  for an AI reasoner to weigh.

---

## 9. Deferred, with reasons

| item | note |
|---|---|
| **The splitter** | 066, 069, 167, 196, 204, 271 — **one file, one label.** 271 dropped ~$164k of wages. The one change that would recover the URLA package |
| **Classified-type threading** | ⚠️ **the best idea to come out of LP-472** — thread the classified type into the extractor so a shared/generic extractor anchors on what classification decided. Helps every long-tail extractor **and the Tier-3 fallback** |
| **Image preprocessing** | ADR-365 — rotated/low-res scans (266, 294, 174). **Neither the guard nor an indicator can fix these** |
| **bank_statement Option 3** | `ending_balance` is the FIRST account only — live for AS-3/AS-4/AS-10. Option 1 recovered the balances; the second account's transactions are still uncaptured. Real transaction rows were dropped on 046 and 057 — **data loss, not a missing field** |
| **The 89 untuned prompts** | long-tail quality |
| **244's Box 10** | deferred as *"needs a typed Box-10 field"*, not uncatchable — the day it exists, an accuracy check drops in free |
| **253's $224k gift** | ⚠️ genuinely uncatchable by self-consistency — a lone amount with no internal contradiction. **The boundary of that layer** |
| **`loan_number_masked` unmasked** | a live PII violation, still open |
| **Phase 7 security hardening** | MFA, rate limiting, malware scanning, audit logging — **required before any real-PII staging**, i.e. before Priya touches real files |
| **The UI** | four/five tabs, finding detail with provenance, upload + re-run, resolve/override/waive. This is the gap between an engine and something Priya can use |
| **Breadth validation** | everything is validated on **LF-6T3N** (one conventional purchase) + synthetic. No jumbo, FHA, condo, self-employed or refinance corpus |

⚠️ **LF-6T3N note:** the identities in that fixture (Akash/Bansari/BofA/Wells) are **invented test data**,
not real PII — despite the fixture calling them "the real ones."

---

## 10. If you're picking up work — the recommended next moves

1. **Land LP-475** (write-up done; commit locally when Geet approves).
2. **Rule-engine Phase 2** — deterministic tags and rules against fields the v2 bench proved populate.
   Start with the **list consumers**: 60+ lists are captured and no rule reads any of them. **37 → ~62.**
3. **Schema-gap Phase 1** in parallel (`docs/schema-gap-remediation-plan.md`) — prompt/extractor fixes,
   no schema change, and it fixes a live rule (IH-1 returns `couldnt_check` on 4 of 16 real policies that
   carry the answer). Plus one genuine extractor bug (credit_report 249: `inquiries` empty, data
   misrouted to `catch_all`). ⚠️ Don't chase `drivers_license.date_of_birth`/`address` — those nulls are
   a **bench artifact**; the harness blanked them.
4. **Make the agency/overlay call** before building CR-9, DT-1, AS-3, PC-4, PR-1 or CR-7 — it's a shape,
   not a ticket, and they get built twice otherwise.
5. **Then the extractor mountain**, one document at a time, each with its golden-file eval:
   credit report → DU/AUS → title → appraisal → MI cert.
6. **Batch Priya's labelling** rather than trickling it, and **collect real files** for the 11 rules that
   a self-authored fixture cannot honestly calibrate.

---

## 11. Doc index

| document | what it is |
|---|---|
| `docs/handoff-summary-2026-08-11.md` | the short "read this first" state-of-play |
| `docs/repo-docs/verification-architecture-v2.md` | **the current architecture** — snapshot, tags, rules, verdicts |
| `docs/extraction-schema-standard.md` | how a schema is designed; the six tests a field must pass |
| `docs/bench-v2-analysis.md` | the v2 measurement in full — wins, regressions, the accuracy ledger |
| `docs/extraction-accuracy-problem.md` | the wrong-value problem and why prompts don't fix it |
| `docs/finish-the-rule-engine-plan.md` | the four phases from 37 → ~100 |
| `docs/schema-gap-remediation-plan.md` | the three-phase schema fix (nulls → lists → fields) |
| `docs/classification-remediation-plan.md` | the three-phase classification fix (mostly executed) |
| `docs/missing-types-plan.md` · `docs/missing-extractors-plan.md` | the type/extractor workstreams (executed) |
| `docs/extractor-failure-remediation-plan.md` | executed |
| `docs/domain/priya-rulings-2026-08.md` | the domain rulings |
| `docs/phases/phase-1.md` … `phase3_bucket2.md` | the full phase history (this brief summarises them) |
| `decisions.md` | the ADR log, through ADR-373 |
| `docs/glossary.md` | mortgage domain + technical terms |
| `docs/project-structure.md` | repo layout and "where does X go?" |
| ⚠️ `docs/mortgageboss-progress-summary.md` | **SUPERSEDED — stops at LP-433**, before the generator, the 91 extractors, the tier merge, Bedrock and the whole bench exercise |
