# The Rule Engine — how verification works, and why it is built this way

The complete reference for the verification subsystem: the substrate it reads, the three
evaluators that run rules, what separates deterministic judgment from AI judgment, how a rule
earns the right to ship a verdict, how verdicts become findings a processor acts on, and the
reasoning behind each of those choices.

**Scope.** Everything behind the Verification tab. That is `backend/app/verification/`,
the `app/services/verification_*` / `finding_*` / `tag_*` services, the `app/ai/*` boundaries
they call, and `frontend/components/file/verification/`. Document classification and extraction
sit *upstream* and are only described where the rule engine depends on them.

**Measured 2026-08-21**, against `bedrock_integration_with_rules_staging`. Every count below was
re-derived from the code at that date rather than copied from a ticket:

| | |
|---|---|
| Rules in the catalogue (`rule_kinds.csv`) | 137 |
| Rules with a written spec (`rules/specs/*.yaml`) | 84 |
| Rules **active** (`ACTIVE_RULE_IDS`) | **78** |
| Fact tags in the vocabulary (`fact_tags.csv`) | 143 |
| Rule → tag edges (`rule_tags.csv`) | 214 |
| AI tag-production groups (`tag_production.yaml`) | 23 |
| Activation bars declared | 73 (14 calibratable-now · 32 no-ai-dependency · 18 ratify-pending · 5 no-ai-threshold-pending · 4 not-calibratable-yet) |
| Typical full-run wall clock | ~384 s mean (measured over 29 runs of one real file) |

---

## 1. The founding split: AI perceives, deterministic code judges

Everything else follows from one decision, taken in Phase 1 and recorded as **ADR-140**:

> **AI (perception/annotation)** reads documents and turns messy reality into structured values.
> **Deterministic Python (judgment)** compares those structured values against thresholds and
> emits auditable pass/fail.
>
> The handoff is **always structured data, never prose.** There is no step where Python
> interprets AI free text.

The reasoning, in the order it mattered:

- **Auditability.** A threshold decision has to be defensible to an underwriter or a regulator.
  "48.2% exceeds the 45% back-end limit" is defensible. "The model thought the DTI was too high"
  is not.
- **Consistency.** Rules give the same answer every run over the same inputs. An LLM does not,
  even at temperature 0.
- **Regulatory faithfulness.** Guidelines *are* rules. Fannie B3-4.2-02 says a large deposit is
  one exceeding 50% of monthly qualifying income. That is arithmetic, and arithmetic belongs in
  code.
- **Scalability of the perception half.** You cannot hand-write a Python method to catch a
  discrepancy nobody foresaw. Open-ended reading MUST be AI — but it is *one general capability*,
  not N hand-written detectors.

The corollary, **ADR-140** again: **AI fallibility is acceptable by design**, because findings are
surfaced for a human to resolve, never used as the final decision. A missed flag is backstopped by
the processor; a false flag is dismissed. What is *not* acceptable is an AI verdict that ships
without anybody knowing it was one — which is what the whole activation and ratification apparatus
in §7 exists to prevent.

### 1.1 What changed between V1 and today

V1 (LP-74 … LP-88, summarised in [`phase3-complete.md`](phase3-complete.md)) built this split
directly: a `FileFacts` snapshot of typed values, a `VerificationRule` structure with
threshold-as-data, three-layer composition (regulatory + investor + lender overlay), and a single
AI cross-source pass beside it. That machinery still exists and still runs the calculators and the
lender overlays.

What V1 could not do was **say honestly what it had not checked**. A rule whose input was missing
produced nothing, and nothing reads to a processor as "checked, clean". So the engine was rebuilt
around a different centre — the architecture the code calls **§3D** — where the unit of work is
not "evaluate a rule" but "reach an honest verdict about one subject, and say what that verdict
rested on".

The rest of this document describes that engine.

---

## 2. Architecture at a glance

Four layers, each of which can degrade without taking the run down:

```
   documents + MISMO + calculators
              │
              ▼
   ┌──────────────────────────┐
   │ 1. SNAPSHOT              │  a frozen, immutable, PII-safe artifact of the file
   │    raw facts, un-linked  │  (mismo · documents · calculations · tags)
   └──────────┬───────────────┘
              ▼
   ┌──────────────────────────┐
   │ 2. FACT TAGS             │  { value, confidence, reasoning, source_facts,
   │    the governed vocab    │    produced_by, tag_role, stage }
   └──────────┬───────────────┘  parsed | derived | ai
              ▼
   ┌──────────────────────────┐
   │ 3. RULES (specs as DATA) │  three generic evaluators, zero per-rule Python
   │    gate → evaluate       │  deterministic · judgment · consistency
   └──────────┬───────────────┘
              ▼
   ┌──────────────────────────┐
   │ 4. FINDINGS              │  one row per (rule, subject), reconciled across runs,
   │    the durable record    │  provenance inline, never silently deleted
   └──────────────────────────┘
```

### 2.1 The run, phase by phase

`app/services/verification_run.py::run_verification` owns **order, degradation and caching** —
and nothing else. It contains no tag logic, no rule logic, no finding logic.

| # | Phase | What happens | Reported as |
|---|---|---|---|
| 1 | **build** | Build the raw snapshot from the loan file: MISMO section, documents section, calculations section. Each section degrades independently. | `build` |
| 2 | **stage_a** | Per-transaction atomic tags (`txn.is_money_in`, `txn.apparent_category`) — one AI perception pass, batched. | `stage_a` |
| 2b | recurrence | `produce_recurrence_tags` — deterministic, model-free, sits with the transaction tags. | (folded into stage_a) |
| 3 | **stage_b** | Cross-entity correlation tags via candidate-then-judge (the deposit-sourcing tag). | `stage_b` |
| 3b | materialization | The generic vocabulary-driven producer: every declared `parsed` / `derived` / `ai` tag for the document / loan / borrower / liability subjects. Only the AI groups a live rule actually consumes are run. | (folded into stage_b) |
| 4 | calculators | Already built in step 1 — they read stated financials, not tags, so they have no ordering dependency. | — |
| 5 | contradiction audit | The slot exists (the gate accepts a contradiction flag); no deterministic cross-checks are wired into it yet. | — |
| 6 | **rules** | Evaluate `ACTIVE_RULE_IDS` through the generic dispatcher. Write back any `rule_judgment` tags produced. | `rules` |
| 6b | pending checks | Evaluate the **blocked** rule set separately and emit manual-review flags (§7.5). Gated by `settings.pending_checks_enabled`. | (folded into rules) |
| 7 | findings | Reconcile against the file's prior findings; mint / carry forward / resolve / revive / retire. | — |
| 8 | prose | The composer rewrites finding text from a fixed fact summary (§10.1). Gated by `settings.finding_prose_enabled`. | — |
| 9 | persist | Write the frozen snapshot as one immutable row. Best-effort. | — |
| 10 | **cross_source** | The snapshot-based AI cross-check pass (§10.3). Best-effort, inside a savepoint. | `cross_source` |

Two things deliberately **propagate** rather than degrade: a rule that produced a verdict with
empty reasoning (a verdict must say why — fail loud), and a finding-persistence collision. Every
other failure is recorded as a `Degradation` and the run continues.

The phases are reported through their own short-lived DB sessions
(`app/services/verification_progress.py`), because the run itself is one transaction that commits
at the very end — anything it wrote would be invisible to a poller until it was already over.

### 2.2 Where the work runs

The Run button enqueues the governed pass as a Celery task
(`app/tasks/verification_rules.py`). **That task is the run's completion authority**: a run reads
COMPLETED only when the rule pass reaches the end and says so. A soft time-limit is terminal (not
retried — retrying re-runs the same ~282 s of work and stacked retries would outlast the
watchdog); a hard kill leaves the run RUNNING and an independent watchdog fails it.

---

## 3. Layer 1 — The snapshot

`app/verification/snapshot/` · ADR-240, ADR-241, ADR-243…246

A snapshot is a **frozen, per-run artifact**. Building it is stateless — it is rebuilt from
scratch on every run — and the result is persisted write-once as one immutable JSONB row.

Three raw sections, plus the tags layer:

- **`mismo`** — a flat `key → Field` map of the parsed 1003/MISMO facts, on stable dotted keys
  (`loan.amount`, `property.city`, `borrower.1.income.2.monthly_amount`,
  `liability.3.unpaid_balance`).
- **`documents`** — an ordered list of `DocumentEntry`, each the extracted typed fields of one
  document plus its *resolved* `belongs_to` borrower references and its captured lists
  (transactions, tradelines, contingencies…).
- **`calculations`** — the four calculators' output as `{value, breakdown}`, each breakdown line
  keeping the calculator's own source tag. This assembler **computes nothing**; the calculators
  are the single source of truth and this is a pure invoke-and-map.

### 3.1 The three properties that make it a substrate

**Absent ≠ empty.** A field no source supplied is `Field.missing()`. A field a source supplied as
`null` / `""` / `0` is `Field.present(...)`. Collapsing the two would let the engine treat "MISMO
never carried this" identically to "MISMO carried a blank" — and the entire honesty model
downstream is built on being able to tell those apart. The same distinction exists one level up:
a whole section can be `absent` (not built / failed) as opposed to present-but-empty ("no
documents yet" is a present, empty list).

**No cross-section correlation, by construction (ADR-241).** There is no field anywhere in the
model that can reference another section's keys or entries. A link between MISMO and a document
*cannot be expressed*. Correlating the two is a downstream job with its own honesty rules —
excluding it here means it can never happen by accident.

**Stable content-ids (ADR-251).** Every raw fact gets `prefix + sha256(canonical-content)[:16]`.
Same content, same id, every run. Not array position — a document inserted earlier would shift
every later index and orphan every finding keyed on one. Byte-identical siblings (two identical
$50 purchases on the same day) get a deterministic occurrence tiebreak mixed into the hash so they
receive distinct ids; because they are indistinguishable, which physical row gets `#0` is
immaterial and the *set* of ids is stable either way.

The id format is `<letters><hex>` with no internal separator, specifically so a digit run inside
it can never present a `\b\d{9,}\b` word-boundary match to the at-rest PII guard.

### 3.2 PII

A `PiiField` never stores the raw value. It stores a masked display (last 4) and a **keyed match
hash** that lets rules match same-value fields across sources without the value existing in the
snapshot:

```
match_hash = "v1:" + HMAC-SHA256(key=K, msg=f"{kind}:{loan_file_id}:{normalized_value}")
K          = derive_key(b"snapshot-pii-match-hash-v1")   # app-secret keyed
```

Each piece earns its place. **Kind-bound** so an SSN and an account number sharing a digit string
do not collide. **Per-loan-file salted** so the same SSN in two files hashes differently — no
cross-file correlation. **App-secret keyed** because an SSN has ~10⁹ possibilities and
`loan_file_id` is not secret, so a bare `sha256(loan_file_id + ssn)` is trivially brute-forced by
anyone holding the hash. **Versioned**, so a construction change is a detectable migration rather
than a silent global match failure. A value that normalizes to fewer than the minimum length
returns `None`, not a hash — two blanks must never "match".

Before any snapshot is written, `persist_snapshot` scans the decoded document for raw PII (a
dashed SSN, a long bare digit run) and **refuses the write** if it finds any. The refusal names
the *path*, never the value. This guard is the last line of defence against an upstream assembler
bug; it does not re-mask.

---

## 4. Layer 2 — Fact tags

`app/verification/snapshot/tag.py`, `app/verification/tag_materialization/` · ADR-251, ADR-252,
ADR-253, ADR-266

A **fact tag** is the governed, honest unit the rules read. Every tag has the same shape:

```json
{ "value": "no",
  "confidence": 0.62,
  "reasoning": "no matching payroll credit within the window",
  "source_facts": ["txn8f21a0…"],
  "produced_by": "ai",
  "tag_role": "structural_fact",
  "tag_version": 1,
  "stage": "B" }
```

- **`value`** — the domain **always includes `"unknown"`**. A value the producer cannot determine
  is `unknown`, never a guess and never a fabricated default.
- **`confidence`** — nullable. `null` for a parsed passthrough (a deterministic read is not a
  judgment); a real number for an AI perception. Never invented.
- **`source_facts`** — stable content-ids into the raw layer. The provenance trail.
- **`produced_by`** — `parsed` | `derived` | `ai` | `spec`.
- **`tag_role`** — `structural_fact` (shared by many rules) or `rule_judgment` (one rule's verdict
  in tag shape).
- **`stage`** — `A` (per-entity atomic) or `B` (cross-entity correlation).

Tags are keyed by **subject** in `snapshot.tags.by_subject[subject_id][tag_id]`, where the subject
is a stable content-id (a transaction, a document, a borrower, a liability) or the reserved
`"loan"`.

### 4.1 Three production modes — declared, not coded

Production is a property of the **tag**, declared in `rules/tag_production.yaml`:

```yaml
txn.amount:        {mode: parsed,  subject: transaction, data: amount}
txn.is_money_in:   {mode: ai,      subject: transaction, data: txn_stage_a}
id.borrower_id_expiration: {mode: derived, subject: borrower, data: borrower_id_expiration}
```

| Mode | What it is | Confidence | Failure |
|---|---|---|---|
| **parsed** | Maps an already-extracted field to a tag, verbatim. Never AI-re-typed — re-reading a number invites hallucinated digits. | `None` | Absent field → tag absent (not `"unknown"`) |
| **derived** | A recipe key resolved against the recipe registry; reads the snapshot deterministically and returns `(value, reasoning)`. | `None` | Cannot compute → `("unknown", why)` |
| **ai** | An **AI group**: a subject, the tags it co-produces, and one prompt. Bounded batches, index-echo integrity, cache by content fingerprint. | the model's own | failure / truncation / off-vocabulary → `unknown`-with-reason |

Adding a tag family is entries in a YAML file plus (for AI) a group declaration. There is no new
producer Python. A tag with no declaration is simply not-yet-materialized; a declaration that
cannot resolve to a real producer **fails loud** — there is no such thing as a silently
unproducible tag.

The declaration lives in YAML rather than in `fact_tags.csv` because that CSV is *generated* from
`docs/snapshot-fact-tags.xlsx`; a hand-edited column there is lost on the next regeneration. This
has bitten more than once and is why the standing instruction is that new tags go in
`vocabulary_extra.yaml` or the xlsx, never in the generated CSV.

### 4.2 Why AI groups exist

The most expensive thing an LLM can do here is *search*. Stage A asks the model about **one
transaction at a time, in bounded batches** — never "find the sourcing for every deposit in this
file", which degrades with position and does not scale.

Stage B generalises that into **candidate-then-judge** (ADR-253), the pattern every correlation
tag follows:

1. **Deterministic candidate search**, pure Python, whole file. For each money-in deposit,
   mechanically find every plausible source across all transactions in all accounts — an
   own-account transfer debit of the same amount inside a date window, a payroll self-source when
   the Stage-A category says so.
2. **AI judgment on the small set.** The model sees *one deposit and its few candidates* and
   answers yes / no / unknown. It never searches; it never sees the whole file.

The critical honesty rule in that pass: a deposit with no candidate and no income signal is a real
**`no`** — "we looked and found nothing", which is the unexplained-deposit signal AS-1 fires on.
It is not `unknown`. `unknown` is reserved for "the input itself was unknown", which the
orchestrator produces by DAG propagation, not the judge.

### 4.3 The orphan guard

A live rule reading a tag nobody produces would `couldnt_check` forever with every test green.
ADR-289 makes that a load-time failure: the vocabulary orphan guard fails loud when a live
consumer reads an unproduced tag. It is one of several guards in this codebase whose entire job is
to convert a silent, permanent nothing into a noisy failure.

---

## 5. Layer 3 — Rules are specs, run by generic evaluators

`app/verification/rules/specs.py`, `app/verification/rule_engine/` · ADR-249, ADR-254, ADR-264,
ADR-265, ADR-268

**Adding a rule is a YAML spec plus a line in `ACTIVE_RULE_IDS`. It is never new evaluation
Python.** That is the single most consequential structural decision in the engine (LP-324), and it
is enforced: `as1.py` and `oc2.py` — the two rules that *were* hand-written — now contain only
spec-derived identifiers and a thin wrapper. Their decision trees live in `AS-1.yaml` and
`OC-2.yaml`.

Dispatch is by **which evaluation block the spec carries**, not by the rule's declared kind,
because a structural rule may legitimately carry either a deterministic or a consistency body:

```
spec.consistency   → the generic cross-source consistency evaluator
spec.deterministic → the generic deterministic evaluator
spec.judgment      → the generic judgment evaluator
none (out_of_scope)→ nothing evaluates; the rule resolves to not_applicable
```

### 5.1 Anatomy of a spec

Two halves. The top is the **documentation / prompt spine** — human-readable criteria, scope and
trigger, the required inputs with their snapshot paths, the guideline citation, and the reference
values with their validation-gate flags. The bottom is the **machine-readable evaluation block**.

`RuleSpec` is frozen with `extra="forbid"`: an unknown key or a missing slot fails at *load*, not
deep inside an evaluation. `load_rule_spec` additionally cross-checks the spec's `kind`,
`numeric_check` and validation-gate flags against the rule's row in `rule_kinds.csv` and raises on
any mismatch — so the CSV stays the single gate of record and a spec can never quietly mark its
own threshold "validated".

From AS-1:

```yaml
reference_values:
  large_deposit_threshold: "50% of total monthly qualifying income"   # prose, for the spine
  priya_validated: false          # must match rule_kinds.csv
  threshold_needs_signoff: true
  values:
    large_deposit_threshold_pct: "50%"      # the machine data the evaluator reads
  guideline_text: "Fannie Mae Selling Guide B3-4.2-02 — a large deposit must be sourced."

subject_enumeration: per_deposit
subject_key_fields: [account, date, amount]

deterministic:
  load_bearing_tags: [txn.is_money_in, txn.amount, txn.has_identified_source,
                      txn.source_strength, txn.date]
  gated_tags:        [txn.is_money_in, txn.amount, txn.has_identified_source]
  applicability: {tag: txn.is_money_in, op: eq, value: in}
  operands:
    amount:    {tag: txn.amount}
    threshold: {product: [{reference: large_deposit_threshold_pct},
                          {calc: [dti, gross_monthly_income]}]}
  outcomes: [ ... ordered, first match wins ... ]
```

Note `load_bearing_tags` and `gated_tags` are **different sets**. `txn.source_strength` refines a
verdict's wording but is provenance-only — its absence must never force a `couldnt_check`. That
distinction is per-rule data, not a global policy.

### 5.2 Subject enumeration

A rule declares *what it produces one verdict per*, as a key resolved by the enumerator registry
(`rule_engine/enumerators.py`):

| Key | One subject per | Notes |
|---|---|---|
| `loan` | the file | tags live under the reserved `"loan"` subject |
| `per_deposit` | bank-statement transaction | subject id = the transaction's content-id |
| `per_document` | document | its own tags, **plus** loan-level tags merged in, plus a structural `document.document_type` tag injected so applicability can be declared as data |
| `per_borrower` | borrower on the loan | borrowers are the distinct `belongs_to` refs across documents; each map is that borrower's own tags over the shared loan tags, so one borrower's facts never leak into another's |
| `per_account` | depository account | grouped from statements by (institution, masked number); statements that cannot be resolved surface as their own subjects rather than being dropped or guess-merged |
| `per_liability` | declared **or** reported debt | see below |

`per_liability` is worth its own paragraph, because it encodes **ADR-374**. Liabilities are
described by two sources for the same real debts: MISMO `liability.{n}.*` (what the borrower
declared) and credit-report tradeline rows (what the bureau reported). The enumerator **unions
them and never merges**: every row from either source is its own subject, marked with its source.
Merging would destroy exactly the signal CR-4 exists to detect — an undisclosed tradeline *is* a
debt present in one source and absent from the other.

The fields hashed into a stated liability's subject id are frozen
(`type`, `monthly_payment`, `unpaid_balance`, `holder_name`). Adding to that tuple re-keys every
liability subject on every file and orphans their findings, so it is only done deliberately. A
separate, wider tuple governs which fields are *gathered* — a processor marking a debt paid off at
closing must not change which subject it is.

### 5.3 The fail-closed gate — the safety core

`rule_engine/gate.py`. Every rule runs this **before** any of its own logic, and before any AI
call. Its contract: *a degraded input must never yield a confident "satisfied"*.

Five defences, in a fixed order; the first that applies short-circuits:

1. **A required tag is ABSENT** (never produced) → `couldnt_check`, naming the missing fact in
   mortgage terms.
2. **A load-bearing tag's value is `"unknown"`** → `couldnt_check`, with a *distinct* reason. This
   prefers the tag's own reasoning when the tag is `derived` and the sentence reads as a sentence —
   a recipe that abstains has already written why ("the binder does not state a dwelling
   loss-settlement basis"), and replacing that with a generic "present but unclear" tells a
   processor nothing. An **AI** tag's reasoning is deliberately *not* promoted here: it is model
   prose of unpredictable length written for a different audience.
3. **A load-bearing tag reads a DISTRUSTED extraction field** → `needs_review` **plus
   ratification**.
4. **A contradiction is flagged for the subject** → `needs_review`.
5. **The minimum load-bearing confidence is below the floor** → `needs_review`.

Otherwise PASS, and the rule may run.

`verdict_confidence` is the **minimum** of the load-bearing tags' non-`None` confidences. Parsed
passthroughs carry `confidence=None` and are excluded from that minimum — they are effectively
certain, and averaging a `None` into the floor check would be meaningless.

**Why defence 3 exists (ADR-377).** Defences 1, 2, 4 and 5 cannot see a *confidently wrong* parsed
value. It is present, it is not `"unknown"`, nothing contradicts it, and it carries no confidence —
which the minimum *filters out*, and skips entirely when every load-bearing tag is parsed. A rule
whose inputs are all parsed (IH-1) had no confidence defence at all. So
`rules/distrusted_fields.yaml` names the fields with a **confirmed wrong value in the corpus**,
keyed by document type, resolved to tag ids through the same production declarations the producers
use — a tag reading the same field name on a *different* document type is unaffected.

Distrust is deliberately a **fifth state**, not a fourth. It is not absent, not empty, not
`"unknown"` (the extractor was confident), and not low-confidence (there is no confidence to read).
Collapsing it into any of those would lose the reason. It is also deliberately **cruder than a
per-extraction flag**: it degrades every file's value, not just the wrong ones. That is the trade,
and the complementary precise layer — LP-474's deterministic `must_differ` self-consistency checks
at the extraction stage, which flag and never correct (ADR-372) — covers three cases this list
intentionally omits.

Every entry carries the document and the error behind it, because the list must be **prunable**: an
extractor that improves should have its entry deleted, and an entry with no evidence should not be
kept "just in case".

### 5.4 Applicability, and the honesty contract

`rule_engine/applicability.py`. This is the single most repeated correctness idea in the engine:

> **`not_applicable` (scope-false) must never absorb `couldnt_check` (data-missing).**
>
> - The predicate says the subject is out of scope → `not_applicable`. The rule was never relevant
>   to this subject (a pay stub, for a POA rule). No gate, no AI, no tag. Not a gap.
> - The predicate tag is absent or `"unknown"` → `couldnt_check`. We cannot tell *whether* the
>   rule applies. It **is** a gap, and it blocks.

Conflating them hides a real gap behind a false "not applicable", which is the most dangerous
failure this system can produce, because it is invisible.

The predicate is **data** — a `TagCondition`. No document types live in code. A rule scopes itself
to POA documents by declaring `document.document_type eq power_of_attorney`.

**Conjunctions** (LP-517) have a precedence that is not "first predicate wins". Every predicate is
evaluated, then: any predicate *definitely false* → `not_applicable` (scope-false beats
data-missing — a money-OUT transaction is out of scope for an earnest-money check whether or not
the loan purpose is known, so reporting "we could not tell" about it would be a false statement);
else any predicate absent/unknown → `couldnt_check`, carrying **that** predicate's own reason.

**Missing documents (LP-330).** The question a per-document rule must answer is not "did the filter
match anything" but "*should* this document exist for this file?". When a rule declares its
document **expected** and every subject is *confidently* out of scope, the rule emits a
missing-document `couldnt_check` keyed under a stable `missing:<type>` subject id, so cross-run
reconciliation carries it forward and retires it when the document appears. It deliberately does
*not* claim absence when any document's type is `"unknown"` (that document might *be* the one), or
when the documents section itself is absent (we could not look, so "confidently absent" would be a
lie).

### 5.5 The deterministic evaluator

`rule_engine/deterministic.py`. Per subject:

```
applicability → gate → resolve operands → ordered outcomes (first match wins) → RuleEvaluation
```

**Operands** are declared, typed, and fail closed. Five sources:

- `tag` — a subject tag's value, coerced per its declared `type` (`decimal` | `date`).
- `loan_tag` (ADR-285) — a **loan-level** tag read from a per-subject rule, without routing through
  a calculator. Unlike a calculator's opaque number, this is a governed fact carrying provenance.
- `reference` — a key in `reference_values.values`; a trailing `%` parses to a fraction, using the
  *same* function the load-time validator uses to certify it is readable.
- `calc` — `[calculator, value_key]` from the calculations section, honouring the gated flag: a
  gated calculation is not trustworthy, so it resolves to `None`.
- `product` — the product of operands (AS-1's `50% × qualifying income`).

Any operand that cannot resolve yields `None`, and a `None` operand routes the subject to
`couldnt_check`. **Never a fabricated 0, never an epoch date, never a silent default.** The
coercer registry is drift-guarded against the type set the spec loader validates, so a declared
type with no coercer fails at import rather than as an uncaught `KeyError` mid-run.

The `date` coercer is the *shared* one, so the deterministic and consistency evaluators can never
disagree about what a date is; it never guesses an ambiguous date.

**Outcomes** are an ordered list, first match wins, each with a guard (`when_tags`,
`when_compare`) or `default: true`. If none matches — which the load-time validator makes
unreachable — the evaluator fails closed to `couldnt_check` rather than emitting nothing, because
emitting nothing is a false green.

Two refinements worth naming:

- **`_reason_fields`** additionally exposes `{name_percent}` for decimal operands. A ratio
  interpolated at full `Decimal` precision produced a finding reading "falls short of documented by
  0.6256740894589456855043635497" — and on the read-only query path the identifier scrub matched
  that 9+ digit run and rewrote it, destroying the one number the sentence existed to convey.
  Formatting is a presentation concern; the verdict is always decided on the full-precision value.
- **`subject_facts`** (LP-525) is a narrow channel back to the document. A rule sees only its tags,
  which is why IH-1 could say "the binder does not state a dwelling loss-settlement basis" but not
  "…on a policy with Coverage A of $577,000". A spec names extra facts it wants **for wording
  only** — they are never gated, never compared, never load-bearing. If a rule needs to *decide* on
  a value, it must be a tag, with the gate and the distrust layer behind it.

### 5.6 The judgment evaluator — AI at rule time

`rule_engine/judgment.py`. The procedural armour lives in the evaluator, **not in the prompt**.
Per subject:

```
applicability → materiality floor → gate → reason over TAGS (never raw documents)
   → produce a rule_judgment tag keyed to that subject
   → MANDATORY human ratification → confidence-gated → provenance inline
```

Properties that make this survivable:

- **The model reasons over declared tags, never raw documents.** The context is
  `{tags: {tag_id: {value, confidence, reasoning}}}` for exactly the tags the spec lists in
  `reasoned_over`. Nothing else.
- **Every verdict is ratification-pending.** A judgment rule never auto-ships on the model's say-so.
  It surfaces to `needs_review` and a human signs it. There is exactly one exception, below.
- **Per-subject fail-closed.** One subject's gate failure, AI transport error, truncation or
  malformed response degrades *only that subject*; the others still evaluate. N subjects means N
  calls (batching would reintroduce the position degradation the whole design avoids), bounded to
  8 concurrent so a large per-document rule cannot burst into a rate limit.
- **A malformed or off-domain answer becomes an honest `unknown`**, and the model's confidence *in
  its invalid answer* is dropped rather than carried.

**The one exception — guideline exemption (LP-516).** Fannie B3-4.2-02 exempts a readily
identifiable deposit source, then adds: "however, if … the lender still has questions as to whether
the funds may have been borrowed, the lender should obtain additional documentation". So the
pattern is **ask, then suppress**: the model is still asked, and only a negative answer is
suppressed by a *deterministic* predicate. The clearing is done by the predicate, not by the
model's confidence, which is why this may ship `satisfied` without ratification. Four ways it
refuses to exempt, all deliberate: no `exempt_when` declared; the predicate tag is absent or
`"unknown"`; no listed alternative holds; the model's answer is in the declared escape hatch. And a
fifth that is not the same guard: **`"unknown"` never exempts** — a malformed response maps to
`unknown`, and without this a response the parser could not read would ship a pass with no human in
the loop.

**Materiality (LP-518)** is the opposite gate, and the contrast is load-bearing. AS-12 asked its
borrowed-funds question of every money-in deposit at any amount, so a $0.03 interest posting
produced the same review item as a $20,000 wire. `materiality` scopes **by size, before asking**,
with the floor computed rather than hard-coded (`fraction × basis`, the fraction chosen by loan
purpose). Below the floor the guideline's own definition says this is not a large deposit, so there
is no obligation for the model to have an opinion and nothing for an escape hatch to preserve —
correct *and* the entire cost saving.

Materiality has exactly two outcomes, and `couldnt_check` is deliberately not one of them. **An
unresolvable floor must not manufacture a gap.** The floor is a triage filter the rule added, not
an input its question depends on: "does this deposit suggest borrowed funds?" is still fully
answerable when nobody can say what 50% of income is. Failing the subject to `couldnt_check` would
hand the processor *less* than they got before the gate existed. So the subject proceeds, carrying
a note saying why the floor did not apply — never silently.

The **derivation** — "$2,000.00 is above the $1,316.67 (10% of $13,166.70 monthly qualifying
income) materiality floor" — is carried as a **structured field**, not folded into the reasoning
string. That is an auditability requirement: a processor who can see a threshold's derivation can
argue with the threshold, and a bare floor cannot be argued with. It is structural because the
prose composer rewrites `reasoning` freely, and on its first composed run it dropped that clause
from four of five AS-12 findings.

**Guidance (LP-522)** fixed the other half. A judgment finding used to read: *"the AI judged 'no' —
an AI verdict a human must ratify (it never auto-ships); $2,000.00 is above the … floor"*. That
explains our engine, not the loan. Guidance is three declared parts — an imperative `action` keyed
by the model's verdict, a `why` and a `how_to_fix` keyed by an **explanatory tag** rather than by
the verdict. Keying the explanation on the verdict assumes one situation and gets it wrong: "the
statement describes it as X, but no matching withdrawal appears on file" is right for a
self-asserted source and false for a deposit with no description at all.

### 5.7 The consistency evaluator — the third rule shape

`rule_engine/consistency.py` · ADR-265, ADR-267

AS-1 is per-transaction; OC-2 is loan-level. A large family is neither: "gather fact T for subject
S across all sources, compare, judge agreement" (ID-1/2/3/4, IN-5/6, CR-1, PC-3, PR-7).

The design is an **exact bookend with an AI-fuzzy residue** — deterministic code does the
mechanical part, and the model only ever sees the small ambiguous set:

```
enumerate subjects
  → GATHER tag T across the declared source scope, applying the declared filter
  → absent ≠ empty; fewer than 2 STATED instances → couldnt_check
  → the fail-closed gate over the gathered instances
  → EXACT compare after declared normalization
       all equal            → AGREE   (no AI call at all)
       differ, mode=exact   → DISCREPANCY (no AI call)
       differ, mode=fuzzy   → the AI judges ONLY the differing values → the declared outcome
```

**Absent is not disagreement.** A source that simply lacks the fact is *excluded*, not counted as a
mismatch — whether the tag was never produced, or an AI perceiver returned `"unknown"` (it looked
and states no value). A bank statement has no address; counting it would inflate the candidate
count and poison the filter gate. Fewer than two stated instances is `couldnt_check`, because a
single source is not "agreement".

**Normalization is declared data**, validated at load against a fixed registry: `strip`,
`casefold`, `collapse_ws`, `drop_punct`, `date`, `drop_entity_suffix`. The registry is
drift-guarded against the key set specs validate against, so a typo fails loud at load.

`drop_entity_suffix` (ADR-281) encodes a real domain ruling: a corporate suffix (Inc / LLC / Corp)
is *format*, not content, for matching an employer across a borrower's documents — a suffix change
is a restructuring, not an employer change. It is greedy on purpose, so a W-2's full legal name
"Acme Logistics Company LLC" and a pay stub's "Acme Logistics" both reduce to `acme logistics`. The
accepted cost, recorded rather than hidden: two genuinely different legal entities sharing a base
name then match. It is a per-rule opt-in — the **tag** keeps reporting what the document states,
and the strip is the *rule's* comparison convention.

The trust property: the **exact bookend is never ratification-pending** (no AI made that call);
only the fuzzy residue's verdict is. So the invariant is per-path, not universal — "ratification
pending implies an AI made this call" holds, but "an AI rule always ratifies" does not.

One more thing this evaluator had to learn (LP-607): its reasoning templates render `{sources}`,
and those were **content-ids**. ID-4 shipped "the borrower's current residence differs across
sources (docdbbe8db1f5a7d9ff, doc6abd650d555473b0, …)" to a processor. Gathered instances now carry
a `source_label` for display alongside the `source_id` for identity and evidence.

### 5.8 Apply specs — the only action that writes to the loan

`ApplySpec` (LP-563) declares, as data on the rule, the structured change a finding offers:

```yaml
apply:
  action: add_liability
  fields:
    monthly_payment: {tag: liab.monthly_payment}
    holder:          {tag: liab.holder_name}
    type:            {literal: mortgage}
```

Resolved per subject from that subject's tags. **A value the subject does not carry means no apply
block at all** — the button simply does not appear. A half-resolved change is the dangerous shape:
a `correct_purchase_price` with no price would write a null over a real figure, and a partially
filled `add_liability` would create a debt with no payment.

Which verdicts may carry an apply is narrowly scoped, and each exclusion has its own reason:

- **`fired`** and **`needs_review`** may. A rule that can never fire by design — DT-6 and DT-8,
  whose question is "which branch is this?" rather than "here is a defect" — surfaces
  `needs_review`, and the Apply *is* the human's answer to it.
- **`couldnt_check`** may not. CR-1's default outcome is a `couldnt_check` reading "this debt could
  not be matched against the application's stated liabilities" — and its fields resolve there
  perfectly well, so an unguarded version offered a primary Apply button that would insert a
  liability for a debt that may already be on the 1003. A duplicated debt and an inflated DTI, off
  an abstention.
- **`satisfied`** has nothing to remediate; **`not_applicable`** is out of scope.

---

## 6. The verdict model

`rule_engine/result.py`. Six verdicts. Five are what a rule can conclude; one is derived.

| Verdict | Meaning | Persists as |
|---|---|---|
| `fired` | the condition is met — a real finding | `open` / RED |
| `satisfied` | earned a pass: present, confident, non-firing | `satisfied` / GREEN |
| `couldnt_check` | a required input was absent or unreadable — **cannot judge** | `couldnt_check` / YELLOW |
| `needs_review` | a load-bearing tag is low-confidence, distrusted or contradictory; **or** an AI made the call and a human must ratify | `needs_review` / YELLOW |
| `not_applicable` | this subject is outside the rule's scope | **not persisted** |
| `pending_automation` | applicable, data present, but the rule is not activated (§7.5) | `pending_automation` / YELLOW |

`not_applicable` and `pending_automation` are **derived, never authored** — absent from
`VERDICT_BY_NAME`, so no spec can declare them.

A `RuleEvaluation` carries everything a human needs to trust the verdict without re-deriving it:
the load-bearing tags **inline** with their value, confidence, reasoning and cited raw facts; the
threshold used and whether that threshold is domain-validated; the verdict confidence; the fix; the
materiality derivation; the resolved apply; and the ratification flag.

The provenance move is the point: a verdict never cites a bare number.

---

## 7. Activation — how a rule earns the right to ship a verdict

This is the part with no analogue in a normal rules engine, and it exists because the inputs are
partly AI-produced. **A rule being written is not a rule being trusted.**

### 7.1 The kinds catalogue

`rules/rule_kinds.csv` — 137 rows, the single gate of record. Four kinds and their evaluation
paths (ADR-247):

| Kind | Count | Path | What it means |
|---|---|---|---|
| `structural` | 67 | `deterministic_only` (41) or `ai_fuzzy_match` (26) | presence / exact-match / count / date. AI only for fuzzy entity matches. |
| `calculative` | 28 | `deterministic_bookend` (14) or `+ai` (14) | arithmetic. Deterministic pre-computes, AI selects which inputs apply, deterministic re-verifies. |
| `judgmental` | 27 | `ai_judgment` | pure AI evaluation plus human ratification. No deterministic component. |
| `out_of_scope` | 15 | `static_filter` | external service / LOS-owned TRID / post-submission / unsupported program. Never routed to AI. |

Every rule starts `priya_validated=false`. A calculative rule carrying a regulatory
threshold/window/limit/factor is `threshold_needs_signoff=true`.

The catalogue is edited when the evidence says so. IH-2 moved from `ai_fuzzy_match` to
`deterministic_only` because that kind **predates typed extraction** — the perception step is
already spent by the extractor (`mortgagee_name` fills on 14 of 15 bench binders) and what remains
is a normalised string compare. TI-1 moved for the same reason. Both are recorded as catalog edits
in their activation tickets rather than done silently.

### 7.2 Activation bars

`rule_engine/activation_bars.py` + `rules/activation_bars.yaml` · ADR-305

An **activation bar** is the accuracy a rule's load-bearing AI tags must reach before that rule
ships a *trusted* verdict. Its height **cannot be computed** — it is the cost of error for that
rule, which is a domain judgment. So the bar is declared, with a written rationale, and carries
`validated: false` until the domain expert signs it off.

Six statuses:

| Status | Count | Gate |
|---|---|---|
| `calibratable-now` | 14 | validated **and** `measured_accuracy ≥ threshold` |
| `no-ai-dependency` | 32 | `input_resolves` alone — nothing to sign off |
| `no-ai-threshold-pending` | 5 | `input_resolves` **and** validated (a window/limit needs sign-off even with no AI) |
| `ratify-pending` | 18 | `input_resolves` **and** a `self_consistency_rate`, with ratification as the safety substitute |
| `not-calibratable-yet` | 4 | never eligible |
| `needs-producer` | 0 | never eligible |

`is_eligible` is fail-closed: an unmeasured tag, an unvalidated bar, a missing accuracy or an
absent input all hold the rule. **When in doubt, hold.** This is the deliberate inverse of the
run-level policy, which fails *open* by degrading — activation never trusts what it has not
measured.

The loader is aggressively strict, and each check has a story behind it. A `ships: auto` bar on a
judgmental rule is rejected as a lie, because the runtime ratifies regardless and the bar would
misstate the rule to a reader. A YAML `threshold: true` coerces to `1.0` in Python (`bool ⊂ int`),
so bools are excluded explicitly. A `no-ai-threshold-pending` bar that is validated but whose input
does not resolve is a contradiction and is rejected at load rather than silently held.

### 7.3 The self-consistency exception (ADR-378)

`ratify-pending` — 18 of the 73 bars — **inverts the gate's stated principle**, deliberately, and
the code says so in those words.

A `self_consistency_rate` is the rate at which two independent derivations of the same tag, from
the same source data in fresh contexts, agreed **with each other**. Two agreeing derivations are
*stable*, not *right*: a systematically wrong tag scores 1.0. Disagreement is a real signal;
agreement is weak evidence.

Three guards make it survivable:

1. **The two numbers may never be collapsed.** `measured_accuracy` means "a human said what the
   right answer was". `self_consistency_rate` means "the model said the same thing twice". A bar
   carrying both is rejected **at load**, so a consistency number can never later be read as an
   accuracy.
2. **A measured-and-failing tag stays held.** AS-4's `stmt.is_reserve_eligible` measured 0/5
   against real labels — a systematic domain disagreement that two agreeing derivations would score
   1.0 on *precisely because* the model is consistently wrong. `measured_accuracy is None` is
   load-bearing in the eligibility check for exactly that case.
3. **Ratification is the entire substitute for measurement.** `ratifies_every_finding()` is called
   by the deterministic evaluator itself, so every finding a ratify-pending rule produces carries
   `ratification_pending=True` and reaches a human. Enforcing it in a comment rather than in the
   code path would have shipped every `ai_fuzzy_match` rule (CR-1, CR-4, CR-5, OC-1 …) as an
   auto verdict with no human in the loop — the hole that had to close before anything activated.

There is one written escape from guard 2: `measured_accuracy_override`, added after a review found
the guard had a cheaper exit than it looked. Because a bar carrying both numbers was rejected,
*omitting* a known measurement was the only way to record a rate at all — and IN-13 shipped that
way, its 5/6 measurement living in prose while the field stayed null. The number is now recordable
alongside the rate, and getting past the guard costs a **declared justification** instead of a
deletion. The activation did not change; what changed is that it is argued in the open rather than
achieved by omission.

### 7.4 The activation history

`ACTIVE_RULE_IDS` is not a hand-list. A test pins
`ACTIVE_RULE_IDS - _BASE_ACTIVE == eligible_rule_ids()` — a rule **cannot** enter the set without
meeting the gate. The registry is organised as an append-only sequence of activation waves, each
with the evidence that admitted it:

| Wave | Added | The reason it was admissible |
|---|---|---|
| base (pre-gate) | AS-1, OC-2, ID-1/2/3/4/6/7/8/9, IN-2 | predate the gate |
| LP-389 / -A | IN-1, IN-5, ID-5 | measured 100%, bars validated; ID-5 was held on a producer/consumer **subject mismatch** and fixed by moving the rule per-borrower |
| LP-384 | AS-9, AS-10, IN-4 | deterministic; their inputs began resolving on the fixture |
| LP-390-7 | AS-2 (auto), AS-12 (ratify) | first income-wave calibration |
| LP-393-6 | IN-7, IN-10, IN-11, AS-11 | four scenario-calibrated bars signed off at once |
| LP-406→433 | AS-8, IN-6, PC-7, PC-2, IH-3, PC-3, IN-12, IN-8/9, AS-6, IN-15, IN-16 | mostly the no-AI path, each proving a known answer on a constructed scenario |
| LP-485→498 | CL-1, CR-13, PR-6, CR-12, IH-2, IH-7, MI-1, MI-4, CO-1, AU-3, CR-1/4/6/8/10, TI-1/2/6, PR-2/3/4/5/7, PC-8, CO-3/4, DT-6, LO-2, OC-1, RE-1, IN-13/14, OC-3, DT-7, PE-1, PE-3, AS-4, FR-3 | the cohort sweeps; most of the ratify-pending population arrives here |
| LP-509 / 551 / 573 | IH-9, FR-5, DT-8 | three rules written from defects found on real files |

Total: **78 active**.

The comments in `registry.py` are the real decision log for this subsystem, and several of them are
records of being **wrong**:

- **CO-3** was dropped mid-ticket and un-dropped on evidence: it is the *fidelity* leg, which
  IH-7's own spec header excludes, so it duplicated nothing — and its two inputs fill 8/8.
- **CO-4** was nearly dropped because the first search looked only at documents labelled
  `condo_questionnaire`; HOA budgets classify as HOA statements.
- **RE-1 and DT-6** were dropped in Phase A and the drop was wrong for the same reason: four
  "independent" searches all probed extractor schemas and filenames for the word "retained", and
  **not one queried the stated side**, where 135 `StatedLiability` rows sat populated across 14
  loan files. A search that finds no source for *one side* of a comparison is not proof the
  comparison is impossible.
- **PE-1 ships with a deliberate blind spot**, which is the point. The conforming limit varies by
  county, and the county does not reach the snapshot (MISMO parses `<CountyName>`; the `Property`
  model has no column for it). So the rule decides only at the two ends and **abstains in the band
  between them**. Comparing that band against the baseline alone would clear a high-cost-county
  jumbo — the exact file the rule exists to catch.
- **AS-4** was blocked on a 0/5 measurement of a tag **that is not in its chain**, and the 0/5 was
  not a model failure: the prompt asked about *account type*, while the labeller was answering
  whether those funds count as reserves for *this loan*. Both answers were right to their own
  question, which is why the disagreement was systematic rather than noisy.

Rules **dropped with a reason rather than deferred** — RE-2 (no REO/retained-property concept
exists in MISMO or the data model), PR-8 (a disaster-area reinspection needs a FEMA declaration
that no field in any of the 121 schema specs states), PC-1 (duplicates TI-1's comparison),
FR-1/2/4/6 — matter as much as the activations. So do the ones **built and held**: CO-5, whose five
inputs resolve on no document of any type; PC-5, whose derivation returned a uniform abstain, and a
rate over a single abstain value carries no information; AS-7, whose trigger does not exist in any
available data (0 NSF lines across the loaded corpus).

The standing hazard those holds guard against is stated repeatedly in the code: **a rule activated
on data that never resolves produces `couldnt_check` on 100% of files forever, with every test
green.** It has killed four live rules.

### 7.5 Pending checks — the third rule state

`rule_engine/pending_checks.py` · ADR-312

A blocked rule runs nothing, so a file that qualifies for it produces **silence** — which reads as
"checked, nothing found" when it is really "didn't look".

The pending pass evaluates every blocked candidate with the *same* dispatch the live rules use.
Where a blocked rule reaches a real verdict (`satisfied` / `fired` / `needs_review`) it is
applicable and its data is present, so its would-be verdict is **discarded** and a
`PENDING_AUTOMATION` manual-review flag ships instead. Where it `couldnt_check` (data absent) or
`not_applicable` (out of scope), it stays honestly dark — no fabricated flag it cannot support.

The line is **applicability** (safe: "this file has a gift / reserves / income trend") versus
**verdict** (uncalibrated: "this gift IS documented"). Only the former surfaces. The flag carries
no load-bearing tags at all, so the uncalibrated values that drove the discarded verdict cannot
leak.

Two refinements from real use: judgment rules are stubbed so the pass never spends a model call on
a verdict it throws away (and never rate-limits the API across a whole file's blocked set); and the
flag is **one per rule, not one per subject** — the first per-transaction blocked rule put seven
identical rows in front of a processor, each saying the same nothing. A count is the one thing a
collapsed flag can honestly add. A rule can also declare `pending_surface: false` when its
applicability carries no signal, so a flag would report normality as a finding.

---

## 8. Layer 4 — Findings

`app/models/finding.py`, `app/services/rule_findings.py` · ADR-256, ADR-263

One `Finding` row per **(rule_id, subject_key)**, on the shared model both generators feed — not a
fork. Three orthogonal axes, which is the thing to understand about this table:

| Axis | Values | Whose |
|---|---|---|
| `evaluation_outcome` | open · satisfied · needs_review · couldnt_check · pending_automation · no_longer_applies | **the engine's** conclusion |
| `status` | red · yellow · green | a coarse triage colour derived from the outcome |
| `resolution_status` | open · applied · overridden · ratified · resolved · accepted_risk · waived | **a human's** progress |

`evaluation_outcome` is also the **structural discriminator** between the governed engine and the
legacy sweep. `origin` does not work for that, because `deterministic_rule` spans both the governed
rules and the retired `xsrc.*` rules. The two systems' counts are never summed and are returned as
separate lists of separate types, so summing them is not merely discouraged — it is awkward to
express.

A finding carries its provenance inline: `load_bearing_tags` (each with value, confidence,
reasoning, cited facts), `details.verdict`, `details.threshold_used`, `details.priya_validated`,
`details.ratification_pending`, `details.derivation`, `details.apply`, and `subject_key` (the
stable content-id).

`couldnt_check` **persists a record** — "we looked and could not check this, here is why" — where
before it left none. That is the whole point of the outcome axis.

### 8.1 Cross-run reconciliation and immortality

`reconcile_evaluation_findings` matches this run's evaluations against the file's prior findings by
`(rule_id, subject_key)` and produces six transitions, each appending an event carrying the run id:

- **minted** — a new subject.
- **carried forward** — re-detected, outcome unchanged. The prior row keeps its id, its notes and
  its resolution. Before this existed, a still-detected finding was churned into a new row every
  run and lost any notes added while it was open.
- **resolved** — `open → satisfied`. The rule now passes for this subject (the gift-letter loop),
  and the resolving tags are cited in the event so the history says *why*.
- **outcome changed** — any other transition.
- **revived** — a retired subject reappeared; the same row comes back.
- **retired** — not detected this run → `no_longer_applies`. **Visible, labelled, reasoned; never
  soft-deleted.** That is the immortality rule.

Two exclusions from retirement, each protecting against a false green:

- **A resolved finding is retained**, never retired. It is a completed processor action; the
  `applied_record`, the audit trail and Undo all depend on it surviving.
- **A degraded run must not retire.** `retire_eligible_rule_ids` is the subset of rules whose
  subject domain was *healthily* enumerated. AS-1 with an absent documents section sees zero
  transactions — that is not "the subjects are gone", and retiring on it would flip real open
  findings to green. Document-derived enumerations (`per_deposit`, `per_borrower`, `per_document`,
  `per_account`, `per_liability`) are checked for emptiness; `per_liability` additionally gets a
  **mixed-source** predicate, because a file with stated liabilities returns a non-empty union even
  when the credit report failed to build — the union looks healthy while the whole document-derived
  half is missing.

### 8.2 Categories

`category_for_rule` resolves per rule, then per family. This replaced nine hand entries plus an
`ASSETS` fallback, under which **sixty-nine active rules were all filed as assets** — the appraisal
rules, every income rule, the rate-lock rule, the MI rules. On one real file that was 28 of 30
findings in one category, which makes filtering by category actively misleading rather than merely
incomplete. Nothing failed; a wrong category is silent, which is why it survived.

The family table is derived from what each family **asks** (its spec titles), not from the prefix
letters: `CO` is condo-project documents, `IH` is hazard insurance on the property, `RE-1` is an
undisclosed *mortgage* (a debt), `LO-2` is letter-of-explanation completeness. Per-rule overrides
win — the `ID` family splits, because ID-1/2/3/4 compare a fact across sources while ID-6/7/9 are
about a document.

`category_for_rule` returns `None` rather than guessing, and a test turns an unclassified rule into
a CI failure. The follow-on fix mattered too: the category is now refreshed on carry-forward, not
only on mint — the first version of the fix deployed, a run completed, and every pre-existing
finding still read "assets".

---

## 9. The human surface

`frontend/components/file/verification/`, `frontend/lib/verification/rule-findings.ts`

### 9.1 Outcomes → tabs

Six tabs, and the mapping is the architecture rather than a display choice:

| Tab | Contains | Why |
|---|---|---|
| **Needs attention** (default) | `open`, `couldnt_check`, `needs_review`, `pending_automation` | different *work*, so they are grouped and labelled within the tab, never merged. `open` first, so real findings do not drown in a pile of `couldnt_check`. |
| **Satisfied** | `satisfied` | the rule ran and passed, with evidence |
| **No longer applies** | `no_longer_applies` | archival: reachable, not advertised |
| **Not applicable** | (structurally empty) | those subjects are never persisted — the tab says so honestly rather than being dropped |
| **Cross-checks** | the snapshot AI pass (§10.3) | a different question, its own stability contract, no apply |
| **Old findings** | the legacy AI sweep, frozen | §10.4 |

The honesty contract the UI must preserve: `couldnt_check` **blocks** and lives in Needs attention —
never a pass, never Satisfied. "No longer applies" ≠ "not applicable" (the subject left, versus was
never relevant). `needs_review` ≠ `open` (a ratification-pending judgment is not a violation).

An outcome the frontend union does not recognise falls back to Needs attention and a safe label,
so a backend enum that grows degrades one row instead of crashing the panel.

The labels are processor vocabulary, deliberately. "Violation" is not said at any stage of a loan —
processors say *condition*, post-close QC says *defect* (Fannie's and FHA's taxonomies are both
Defect Taxonomies) — so `open` reads **"Must fix"**. "Ratification" is the engine's word, so
`needs_review` reads "A judgment awaiting your sign-off — not a violation."

Archival tabs show their count **only while open**. On a real file the counts read attention 26,
satisfied 34, no-longer-applies 113 — every one in an identical pill, so the largest number on the
page was the least useful fact on it.

### 9.2 Actions

Which buttons appear is driven by the **outcome**, not by a per-rule list. A rule that concluded
something is missing wants a document request; a rule that made an AI judgment wants a signature; a
rule that passed wants nothing. Offering the same six everywhere makes the common action hard to
find.

| Action | Meaning | Reason required |
|---|---|---|
| **Ratify** | sign off an AI judgment | no |
| **Apply** | perform the declared structured change on the loan | no (but see the preview) |
| **Not an issue** (override) | the system was **wrong** | **yes** |
| **Accept risk** | the system was **right**, and the file proceeds anyway | **yes** |
| **Add note** | annotate | — |
| **Request docs** | create a needs-list item (single or bulk) | optional |
| **Undo** | reverse a resolution | — |

Override and Accept risk are two actions rather than one because they tell **opposite stories to an
auditor**. "Override" named the mechanism; "Not an issue" states the claim, which is what a later
reader actually needs.

**Apply is previewed before it commits.** "View fix" runs the *real* `apply_finding` inside a
savepoint, snapshots the DTI/LTV before and after, then rolls the savepoint back — a
simulate-don't-persist dry run rather than a parallel computation that could diverge from what the
button actually does.

### 9.3 The dial

The aggression dial (Conservative 0.8 / Balanced 0.5 / Thorough 0.0) is a **read-time confidence
filter**, not a re-run. It never enqueues an AI call and costs nothing to move.

Its scope today is worth stating precisely, because it has narrowed: it filters the **legacy AI
list** for display and supplies the cutoff to the **blocking** computation over all findings. The
governed rule findings are returned in full and bucketed by *outcome*, not by confidence — and a
governed finding whose verdict confidence is `None` is stored at `1.0` specifically so a
fail-closed outcome can never be hidden by a cutoff.

The dial filters by **confidence**, never by **severity**. A finding's red/yellow is intrinsic. A
low-confidence red is *uncertain*, not *less severe*; how-sure and how-bad are orthogonal.

---

## 10. The AI passes that are not rules

### 10.1 The finding prose composer (LP-527)

Runs **after** the findings are written. It reads them, asks a model to rewrite each one's text,
and writes back **only** `message` and `how_to_fix`. Not the verdict, not the outcome, not the
tags, not the reconcile identity. A total failure of this pass leaves a fully correct run whose
findings read exactly as the templates wrote them.

Four constraints make it safe, none optional:

1. **It only ever rewrites.** No verdict depends on it.
2. **It cannot introduce a fact.** Every number, date and quoted string in the output must already
   appear in the input summary — checked deterministically, no model involved. A generation that
   invents "the 2024 W-2" is **rejected**, not repaired.
3. **It falls back to the template**, which is a real sentence. That is why the template floor was
   built first: without it, rejection would leave a hole.
4. **It is cached by the hash of its input**, so identical facts produce identical prose. Without
   that, the same unchanged problem reads differently every run — a processor re-reads it thinking
   something changed, and cross-run diffing becomes noise.

It runs **per finding, not batched**: batching is cheaper on a cold cache and worse everywhere else
— one changed finding would invalidate a whole batch (defeating the cache, which is the point), one
malformed response would cost every finding its prose, and item 17 of 25 gets less of the model's
attention than item 1.

It never logs the summary or the output; a finding's text carries borrower names, employers and
account descriptions.

### 10.2 Finding guidance (LP-96)

The "why it matters" and "suggested fix" attached per **canonical finding type**. Generated once,
stored, resolved by a dict lookup at read time — rendering a card or re-running verification makes
no model call and yields identical text every time. Marked `starter=True`: researched and grounded,
but not authoritative until the domain expert confirms it.

### 10.3 The snapshot cross-check pass (LP-586)

The current AI discovery layer. Its input is the **persisted snapshot** rather than a context
assembled from live tables, and that one difference decides everything else: the snapshot is the
same bytes on every run until the file genuinely changes, which is what makes a stable answer
possible at all.

What it looks for: a fact in one source checkable against a fact in another — **the pairings nobody
wrote a rule for**. A tax bill's assessed value beside a stated valuation with no appraisal; a tax
bill naming two owners beside an application with one borrower; W-2 totals beside a pay-stub run
rate.

**It notices; it does not judge.** No rule spec, no calibrated threshold, no guideline citation — so
a finding here may **never write to the loan**. The processor's actions are sign off, dismiss, note
and request docs, and nothing that changes a number.

The stability contract is the whole point:

- unchanged snapshot → the model is **not asked**; the stored findings are returned as they are;
- changed snapshot → the model is asked, and the result is **reconciled** against what is stored;
- a processor's disposition survives both, because identity is content.

The second and third points matter as much as the first. A pass that re-asked and replaced would
give a stable count on an unchanged file and still lose a dismissal the moment anything moved —
which trains a processor to stop dismissing things, and is worse than a drifting number.

Stability cannot come from prompting. Temperature 0 and a fixed schema do not make an LLM
deterministic. It comes from **not asking again** while the fingerprint holds — and the fingerprint
must exclude the per-run fields (`run_id`, `created_at` are fresh on every run, so hashing the
snapshot as-is would produce a new fingerprint every time and the feature would look implemented
while being inert).

It notably does **not** hash the engine, where the older pass did. Engine changes that matter reach
this pass through the snapshot itself, since the tags and calculations it reads are the engine's own
output.

### 10.4 The legacy cross-source pass — switched off (LP-614)

The original LP-78 pass had two halves, both now off.

**The AI half** spent a month being confidently wrong in ways its own text disproved: a $6,028
biweekly gross "conflicting" with $13,166.67 a month (the same money); a stated Bank of America
balance "conflicting" with a documented **Wells Fargo** one (two different accounts); an employer
mismatch over one trailing letter. Each was patched in turn and the next run found a new way.

**The deterministic half** is off on evidence, not by association. Sixteen hand-written `xsrc.*`
rules; across the two real files on staging exactly **two** ever fired — and both had already been
retired for contradicting IN-5 and ID-1, because their normalizer folds case and whitespace and
nothing else, so it cannot tell "AMERICAS" from "America". Eleven of the other fourteen map to an
active governed rule.

The change is careful about one thing: the task body is a **no-op guard**, not a "disabled" body
that marks the run completed. This task and the rule pass share one run, and the rule pass is the
completion authority — completing the run here would report a finished verification while the rules
were still running.

The rows already written are **not deleted**; they stop being displayed. The Old findings tab is now
AI-typed only and frozen.

---

## 11. The calculators

`app/verification/{dti,ltv,mortgage_insurance,reserves,self_employed,max_loan}.py`

Six deterministic calculators — DTI, LTV, MI/MIP, self-employed income, reserves, max loan — pure
`Decimal` arithmetic, no AI. They serve three consumers: the Verification tab's calculator strip,
the rule engine (via `calc` operands and the calculations snapshot section), and the finding
apply→recompute loop.

The design principles, from LP-76/77:

- **Transparency is the feature.** Every response is fully itemized: every income line, every
  housing component (PITI + MI + HOA), every debt, each with its auto value, any override, the
  effective value, a source tag, and the **explicit formula**. A black-box DTI is untrustworthy.
- **Auto-populated, override-able, audited.** Any field can be overridden; the override persists,
  takes precedence, is activity-logged with the prior value, and the endpoint returns the
  *recomputed* result so the UI updates in one round trip.
- **The subtleties are correct and visible.** LTV is the first loan over the **lesser of** purchase
  price and appraised value; HCLTV uses the HELOC **credit limit**, not the drawn balance. Those are
  what a general-purpose chatbot fumbles, and showing the basis explicitly is the trust mechanism.
- **Single source of truth across consumers.** The DTI's mortgage-insurance line **consumes** the MI
  calculator's `monthly_premium` rather than recomputing it, so the two can never disagree. Before
  that, PITI silently omitted mandatory MI — understating front-end DTI in the *qualifying*
  direction, so a borrower truly at 44% could show ~41% and appear to pass a ceiling they would
  actually fail.
- **Fail closed means gated, not smaller (ADR-329).** A DTI that cannot convert an HOA figure to
  monthly **gates** rather than assuming monthly or dropping to zero. A gated calculation resolves
  to `None` as a rule operand, so a rule reading it `couldnt_check`s rather than judging on a
  fabricated number.

One known correctness issue is recorded rather than hidden: **a refinance's payoff must not count
alongside the new PITI**, and on at least one real file the engine's 58.59% should have been 34.39%.
This affects every refinance.

---

## 12. Lender overlays

`app/verification/registry.py`, `overlays/` · ADR-188, ADR-196

The V1 three-layer composition, still live for the calculators' effective limits:

1. **Base** = all regulatory rules + the investor rules for the file's program (Conventional **or**
   FHA, never both).
2. **Patch** with the lender's overlay, applied as a **diff**: an override replaces a base rule's
   threshold *by `rule_id`* (identity and logic unchanged — only the `Condition`); a custom rule is
   appended.
3. **Output** = a flat effective set with final thresholds.

Two properties make this possible, and they are the linchpins the whole V1 rule structure was built
around: a **stable `rule_id`** (so an overlay has something to reference) and **threshold-as-data**
(so the same fixed logic evaluates a different value). Rule logic is fixed; thresholds are data.

Un-overridden rules fall through to the investor default. Overlays are diffs, not per-lender copies —
small, maintainable, auditable.

The demonstrable consequence: the same file at 48% back-end DTI **flags under UWM** (48 > 45) and
**clears under Sun-West** (48 ≤ the investor 50). Same data, different lender, different findings.

The shipped UWM and Sun-West thresholds are **starter placeholders** for domain validation, marked
as such in the module, in every `reason`, and in the design note. The mechanism is real; the values
are starter.

The governed engine (§5) does not currently route through this composition — its thresholds are
`reference_values` on the spec. Reconciling the two, so a lender overlay can move a governed rule's
threshold, is the open design question that `LP-477` was written to answer, and the standing domain
ruling constrains it: *store all agency rules and select the applicable one; never the strictest; a
lender's conservative choice is an explicit overlay; when the agency is unselected, return
comparative results.*

---

## 13. Determinism, caching and cost

An LLM is not deterministic. Everything stable about this system comes from **not asking again**.

| Layer | Cache key | Effect |
|---|---|---|
| Stage-A tags | the transaction's content fingerprint | identical transactions share one call; an unchanged transaction reuses its judgment across runs |
| Stage-B sourcing | the deposit's fingerprint | same |
| AI group materialization | subject content fingerprint | same |
| Finding prose | hash of the fact summary | identical facts → identical prose |
| Snapshot cross-check | the snapshot fingerprint (minus per-run fields) | unchanged file → no model call at all |
| Legacy cross-source (historic) | SHA-256 over the assembled context **plus** an engine fingerprint | it reasoned over live tables and could not tell which engine version produced them |

Only **successes** are cached; a failure retries next run.

Other cost controls: only the AI groups a **live** rule consumes are materialized on the normal
path (no dead structuring pass for a family whose rule has not activated); the pending-check pass
stubs judgment rules so it never pays for a verdict it discards; the judgment evaluator bounds
concurrency at 8 subjects; content-ids never reach the AI (batches address items by a 1-based index
and the id is attached afterwards).

**Models.** Reasoning is `claude-sonnet-4-5` and stays there — the live activation bars are
calibrated on it, and re-pointing reasoning would invalidate them. Classification and extraction run
`claude-haiku-4-5`. Analysis has its own knob so it is not dragged along when reasoning is
re-pointed for calibration. The provider is switchable between the direct Anthropic API and
**Amazon Bedrock**, which routes the same calls inside the AWS trust boundary — the compliance basis
for putting real borrower NPI in staging.

**PII never reaches a log.** Every AI boundary in this subsystem logs counts, token totals and
decisions only.

---

## 14. Degradation: what happens when things break

The run-level policy is the **inverse** of the activation policy. Activation fails closed and holds.
A run fails *open* by degrading, because a run that dies produces nothing, and nothing is the least
honest possible output.

- **A tag producer fails** → `unknown`-with-reason tags. Rules depending on them gate to
  `couldnt_check`; rules that do not depend on them **still run**.
- **A whole stage throws** → the pre-stage snapshot is kept, the degradation is recorded, the run
  continues. Logged at ERROR, not warning: the per-call path already fail-closes, so a wholesale
  stage failure is a transport outage or a code defect, and keeping the run alive must not bury it.
- **A section fails to build** → that section is `absent` **with a reason**, distinct from empty.
- **Snapshot persistence fails** → degraded, not fatal. The failure message names the field, because
  a version that logged only the exception class left the at-rest guard refusing every write on
  staging for six days — 22 completed runs, 0 snapshots — with no trace anyone could act on.
- **The snapshot cross-check fails** → contained in a `begin_nested()` savepoint. Without it, a DB
  error inside that call poisoned the session and the caller's commit raised, rolling back the rule
  findings, the persisted snapshot and the COMPLETED status with it. "Best-effort" was only true for
  non-DB exceptions.
- **The prose pass fails** → the findings read as the templates wrote them.

Everything that degraded is **recorded on the run** and visible. What is never allowed is a
degradation that produces a *pass*.

Two failures deliberately still propagate: an empty-reasoning verdict (a verdict must say why), and
a finding-persistence collision.

---

## 15. Calibration and evaluation

`app/verification/eval/` · ADR-257, ADR-276, ADR-279, ADR-303

A **two-level golden harness** runs the real pipeline against labelled cases and scores at both the
**tag** level and the **finding** level, plus a provenance check: a `fired` or `needs_review`
verdict must carry its load-bearing tags inline with non-empty reasoning. The harness *evaluates* —
a mismatch is a reported regression, never a reason to edit rule or tag logic.

Two metrics per tag dimension, because accuracy alone hides the failure that matters:

- **Unknown rate** — how often the tag abstains. Too high and the tag is useless (everything routes
  to `couldnt_check`). Too low, paired with poor concrete accuracy, means the model **fabricates**
  rather than admitting it cannot tell.
- **Accuracy when concrete** — when the tag commits, how often it matches the label. This is where
  fabrication shows up, and a confident wrong answer is worse than an honest unknown.

These are only meaningful in **live** mode. Keyless runs replay the labels and read as a trivially
perfect baseline — useful as a plumbing check, nothing more.

Fixture strategy, learned the hard way:

- **A frozen realism anchor** (`lf6t3n_fixture`) built in code rather than committed as a large
  JSON, reusing the real transaction content-ids so human labels stay stable.
- **Standalone scenario fixtures** for thin-n calibration (ADR-314), never merged into the anchor —
  own id namespaces, one problem per file, so each verdict is attributable.
- **Fire-path scenarios**, because several rules ship with their firing branch unexercised: a clean
  file never triggers them, and an untested fire path is a rule nobody has seen work.
- **A dormant probe** that forces never-run producers to run once on a real file, *before* domain
  expert time is spent — because calibration measures a tag's **accuracy**, which presupposes it
  **materializes**. This proves the pipe carries water, not that the water is clean.

The limits are recorded as ADRs rather than glossed:

- **ADR-332 — the limit of synthetic calibration.** Four of seven blocking tags are not labelable on
  invented fixtures without labelling our own invention. Some tags need real files.
- **ADR-313 — labels do not carry.** Name-match goldens from a de-identified fixture do not transfer
  to a real-DB worksheet; some labels have to be redone on real data.
- **ADR-354 — the standing rule.** A tag-coverage audit measured the field *surface* (does the schema
  declare it), not the field *data* (is it populated, are its values usable). Three work-steps
  under-delivered for that one reason. So: **verify a field is populated with clean values on real
  data before declaring a tag on it.**

---

## 16. What is deliberately not built

Recorded because the absences are decisions:

- **No meta-rules.** LO-1 needs the list of conditions that *require* an LOE, which is lender- and
  AUS-driven and enumerated in no document. Deriving it from this run's own findings would make it a
  rule over other rules' output, which nothing in the architecture does.
- **No list-producing tags.** Five tags declare `value_type: list`; none has a producer. FR-6 would
  be the first, and open-ended discovery has no closed vocabulary to abstain against — so nothing
  distinguishes a real discovery from a fabricated one.
- **No cross-document ordered-pairwise or set-coverage relations in the DSL** (ADR-322, ADR-323).
  The deterministic DSL expresses *all-equal* natively and nothing more. The resolution is
  consistent with the rest of the design: **derive the fact in a producer, and let a trivial rule
  branch on it.** Tags describe; rules judge.
- **No run-state store**, so AU-4 (comparing current data against last-run values) has nowhere to
  read from.
- **No county in the snapshot**, which is why PE-1 abstains in the conforming band (§7.4).
- **The tag DAG (`tag_dependencies.csv`) is empty by design**, generated and test-pinned. Filling it
  needs a generator change — and the header is arguably the wrong relation anyway: `tag → tag` is
  not "which rules unblock together", which is `rule → tag` and already lives in `rule_tags.csv`.

---

## 17. Reading the decision record

The ADR log for this subsystem runs roughly **ADR-140 → ADR-378**, and it is the real design
history. The ones to read first, by theme:

**The founding split** — ADR-140 (two-layer verification) · ADR-141 (findings are blocking) ·
ADR-142 (the dial gates display and blocking) · ADR-143 (on-demand with staleness) · ADR-144
(typed core + catch-all + source location).

**The V1 engine** — ADR-188 (uniform structure, three-layer composition) · ADR-189 (the findings
model extension) · ADR-190/191 (DTI/LTV) · ADR-192 (the AI cross-source layer) · ADR-196 (starter
overlays).

**The substrate** — ADR-240 (absent≠empty, PII match-hash) · ADR-241 (un-linkable sections) ·
ADR-246 (write-once persistence + the at-rest guard) · ADR-251 (tag model + content-ids).

**Tag production** — ADR-252 (Stage A: structure, don't conclude) · ADR-253 (candidate-then-judge) ·
ADR-266 (production is a declaration) · ADR-289 (the orphan guard) · ADR-302 (a tag that cannot
express a risk makes the risk uncatchable).

**The engine's shape** — ADR-254 (the fail-closed gate) · ADR-264 (rules become specs) · ADR-265
(the consistency primitive) · ADR-268 (declared subject enumeration) · ADR-269 (typed operands) ·
ADR-270 (`not_applicable` ≠ `couldnt_check`) · ADR-285 (the `loan_tag` operand) · ADR-322/323/324
(what the DSL cannot express, and the derived-producer answer).

**Trust and activation** — ADR-305 (activation bars) · ADR-306 (the gate, not a list edit) ·
ADR-312 (the third rule state) · ADR-327 (the third eligibility case) · ADR-336 (a live base rule
riding an unscored tag) · ADR-338 (what a multi-tag bar measures) · ADR-377 (the distrust list) ·
**ADR-378 (self-consistency activation — the principle deliberately inverted)**.

**Findings** — ADR-256 (the outcome axis) · ADR-263 (cross-run reconciliation + immortality) ·
ADR-293 (governed findings carry their own taxonomy) · ADR-294 (`couldnt_check` reasons speak
mortgage) · ADR-296 (a finding names its subject).

One integrity note for anyone navigating the log: **ADR numbers 362, 366 and 373 are each used
twice** — once by the infrastructure work stream and once by the rules work stream. Cite these by
title, not by number alone.

---

## 18. File map

**Pure engine** (`backend/app/verification/`)

```
snapshot/           the frozen artifact: model, builder, three section assemblers,
                    fields, pii, content_id, tag, traversal, persistence
tag_materialization/ producer (orchestrator) · declarations · parsed · derived · ai · subjects
rule_engine/        result (verdicts) · gate · applicability · enumerators
                    deterministic · judgment · consistency   (the three evaluators)
                    registry (ACTIVE_RULE_IDS + dispatch) · activation_bars
                    pending_checks · reasons · as1 · oc2 (thin shims)
rules/              specs.py (the DSL) · specs/*.yaml (84) · kinds.py + rule_kinds.csv
                    fact_tags.csv · rule_tags.csv · tag_production.yaml
                    activation_bars.yaml · distrusted_fields.yaml · vocabulary_extra.yaml
                    projection.py (files → DB) · schema.py (V1 rule structure) · overlays/
eval/               harness · cases · calibration · live_calibration · worksheets
                    fixtures (lf6t3n, income, owner-match, fire-path) · dormant_probe
dti.py ltv.py mortgage_insurance.py reserves.py self_employed.py max_loan.py
confidence.py  finding_guidance.py  facts.py  registry.py  engine.py
```

**DB-facing services** (`backend/app/services/`)

```
verification_run.py        the orchestrator (order · degradation · caching)
rule_findings.py           persist + cross-run reconcile
verification_progress.py   phase reporting  ·  verification_eta.py  per-file estimate
finding_resolution.py      apply / override / ratify / accept-risk / note
finding_impact.py          the simulate-don't-persist Apply preview
finding_reconcile.py finding_identity.py finding_source_matching.py finding_prose.py
tag_production.py tag_correlation.py       Stage A / Stage B orchestration
snapshot_findings.py       the snapshot cross-check pass
cross_source.py cross_source_deterministic.py   the legacy pass (off)
dti.py ltv.py mi.py calculators.py
```

**AI boundaries** (`backend/app/ai/`) — `rule_judgment` · `tag_production` · `tag_correlation` ·
`snapshot_cross_source` · `finding_prose` · `observation` · `cross_source` (legacy)

**Task + API** — `app/tasks/verification_rules.py` (completion authority) ·
`app/tasks/cross_source.py` (no-op guard) · `app/api/verification.py`

**Frontend** (`frontend/`) — `components/file/verification/*` ·
`lib/verification/rule-findings.ts` (the tab model) · `lib/types/verification.ts`

---

## 19. The design principles, in one place

Everything above reduces to about a dozen commitments. They are worth stating on their own, because
new work in this subsystem is judged against them.

1. **AI perceives; deterministic code judges.** The handoff is structured data, never prose.
2. **Absent ≠ empty ≠ unknown ≠ distrusted.** Four different states, four different consequences.
   Collapsing any pair has caused a real defect.
3. **Scope-false must never absorb data-missing.** "Not applicable" and "couldn't check" are
   opposite claims.
4. **Fail closed on a verdict; fail open on a run.** A degraded input never yields a confident pass;
   a degraded stage never kills the run.
5. **A verdict must say why, and cite what it rested on.** Empty reasoning is a hard error, and the
   load-bearing tags travel inline with the finding.
6. **Never fabricate.** No default 0, no epoch date, no coerced enum. An unresolvable value produces
   an abstention with a reason.
7. **Rules are data.** Adding a rule is a spec plus an activation line, never new evaluation Python.
8. **A rule ships only what has been measured** — or, where it has not, only behind mandatory human
   ratification, with that substitution written down.
9. **Nothing is silently deleted.** A finding that stops reproducing is retired, visibly and with a
   reason.
10. **Stability comes from not asking again**, not from prompting. Cache by content; re-ask only
    when the content moved.
11. **Say it in the processor's language.** Not tag ids, not content-ids, not "ratification".
12. **Record the reasoning where the decision lives.** The activation registry, the distrust list
    and the gate all carry their evidence in-line, because a bare list is unreviewable a month
    later and unprunable a year later.
