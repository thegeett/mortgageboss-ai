# Phase 3 Verification — Design Note

**Status: DESIGN NOTE (recorded in advance).** These decisions were settled during
Phase 1 (Epic 5) while shaping document extraction; they define how the **Phase 3
verification engine** will behave. Recorded so they're settled, not re-litigated later.
The extraction shape they depend on is built in **LP-39a** (pay stub), then replicated for
**W-2 (LP-39b)** and **bank statement (LP-39c)**.

The decisions below are also captured as ADRs — see **ADR-140…145** in
[`decisions.md`](decisions.md). This note is the consolidated narrative.

## 1. Two layers — AI surfaces facts/discrepancies; deterministic code judges thresholds

Verification has two kinds of work, split by what each tool is good at:

- **AI (perception/annotation)** — reads documents, extracts structured values, and does
  **open-ended cross-source discrepancy detection** as a *single general capability* (NOT a
  method-per-finding). It emits **structured findings** (typed fields: type, amount,
  source_doc, page, snippet, confidence, reasoning) and catches known **and** novel
  discrepancies (e.g. an undisclosed support obligation in a divorce decree) because it
  reads and compares rather than executing pre-written checks.
- **Deterministic Python (judgment)** — a finite, enumerable set of regulatory rules (DTI,
  LTV, recency, loan limits, overlays — Fannie/FHA/lender guidelines), **one function per
  rule**, consuming **structured data** (extracted values + human-confirmed AI corrections)
  and emitting auditable pass/fail findings against thresholds.

The handoff is **always structured data, never prose** — the AI writes typed records;
deterministic rules read typed fields. There is no step where Python interprets AI prose.

**Why the split:** auditability (threshold decisions are defensible to underwriters/
regulators); consistency (rules give the same answer every run); regulatory faithfulness
(guidelines *are* rules); scalability (open-ended detection is ONE capability, not N
hand-written methods, so it catches what nobody pre-enumerated). **Why not a method per
discrepancy:** you can't write a Python method to catch a discrepancy you didn't foresee —
open-ended detection MUST be AI; "method per rule" applies only to the finite regulatory rules.
(ADR-140.)

## 2. AI fallibility is acceptable — findings are for human review, not decisions

Open-ended AI detection is probabilistic (may miss or false-flag). Acceptable **by design**:
findings are surfaced for the processor to **resolve, not used as the final decision**. The
deterministic threshold decisions stay auditable. A missed flag is backstopped by the
processor's judgment; a false flag is dismissed — the same human-in-the-loop principle as
document classification. (ADR-140.)

## 3. Findings are BLOCKING — nothing is ever ignored

Every in-scope finding MUST be resolved before a file is "ready to submit":

- **APPLIED** — incorporated into the file/numbers (e.g. an $800 decree obligation added to
  liabilities, which feeds the deterministic DTI recompute), or
- **OVERRIDDEN** — explicitly dismissed by the processor **with a recorded reason**.

No finding may be silently ignored; **OPEN findings block submission**. While any in-scope
finding is OPEN, affected calculations (DTI/LTV, …) show an **alert** ("findings unresolved —
this calculation may be incomplete"); the calculator queries open in-scope findings for the
file. (ADR-141.)

## 4. Aggression dial = a confidence threshold gating BOTH display and blocking

The AI cross-source layer **detects and stores ALL findings**, each with a confidence. A
per-file **aggression** setting (user-level default, per-file override) sets a confidence
**cutoff applied at read time**: Conservative → high; Balanced (default) → medium; Thorough →
low (almost everything, incl. low-confidence hunches).

**Decision (2a.i): the threshold gates BOTH display AND blocking.** A finding below the active
cutoff is neither shown nor blocking; one at/above is shown AND must be resolved. So "resolve
all findings" means "resolve all findings at the chosen thoroughness." Implications:

- Detection stores **everything** (with confidence); the threshold filters at display/blocking
  time — changing the dial **re-filters instantly, no AI re-run, no new cost**.
- The **active aggression level at submission is recorded on the file** (auditable: what
  threshold was in effect when submitted). (ADR-142.)

## 5. Cross-source verification runs ON-DEMAND, with a staleness flag (V1)

When any document changes (upload, type override, re-extraction), verification is marked
**STALE** ("documents changed — verification out of date"). The processor **manually triggers**
the heavy cross-source pass — the divorce-decree case needs the decree **and** the stated
liabilities both present, so the comparison fires when the processor runs it, not piecemeal
per upload. Later phases automate verification on document change. (ADR-143.)

## 6. Per-field source location (page + snippet)

Every extracted field carries **where it was read from**: a **page number** and a **verbatim
snippet**. A processor can click a finding (e.g. the $800 obligation) and see the exact
document line that supports it — the trust/audit mechanism. Visual bounding-box highlighting is
deferred; page + snippet is the V1 form. (Built in LP-39a; ADR-144/145.)

## 7. Extraction shape — typed core + grouped catch-all (the foundation)

Extraction captures **everything** on a document (processors use all fields) while keeping the
decision-driving fields **typed** so deterministic rules can consume them:

- **Typed core** — the mortgage-decision-relevant fields, named + typed (e.g. pay stub
  `gross_pay: Decimal`, `pay_period_end: date`). Defined by what the verification **rules**
  consume; grows in Phase 3 as rules need fields (promote from the catch-all). NOT a generic
  field bag.
- **Grouped catch-all** — everything else, captured as sections → `{label, value, page,
  snippet}`. Nothing is lost; the processor sees the full document; the AI cross-source layer
  has the full material to catch discrepancies (the catch-all is what makes the divorce-decree
  case catchable — the obligation is captured even if it's not in the typed core).

Built in LP-39a (pay stub), replicated for W-2 (LP-39b) and bank statement (LP-39c). (ADR-144/145.)

## 8. The rule engine — implemented (LP-74)

LP-74 builds the **engine** that the design above describes — the mechanism, with a few
**sample** rules to prove it end-to-end. The real ~60 Conventional + ~50 FHA rules are
LP-82..85; the real lender overlays are LP-80 (the LP-68 "engine before content" pattern).
Backend only. Code lives in `backend/app/verification/` (pure) +
`backend/app/services/verification_engine.py` (DB-facing). (ADR-188.)

### 8.1 The uniform rule structure + the two linchpins

Every rule — regulatory, investor, or overlay — shares **one** structure
(`app/verification/rules/schema.py::VerificationRule`): a stable `rule_id`, a `layer`, an
`applicability` (all_loans / program / lender), the typed `reads` field path(s), a
`condition` (threshold-as-data), a `severity` (red/yellow), a finding `category`, a
`description`, and a structured `source` citation. Rules are **definitions** (config-like,
declared in code, seedable), not per-file rows.

Two properties are the **linchpins** that make overlays possible:

1. **Stable `rule_id`** (e.g. `conv.dti.back_end_max`) — a rule's identity. Overlays
   override rules *by this id*.
2. **Threshold-as-data** — the threshold is a `Condition` (`{op, value, unit}`) the fixed
   `satisfies()` logic reads, **never hardcoded**. Because it is data, an overlay can supply a
   different value and the *same* logic evaluates against it. **Rule logic is fixed;
   thresholds are data.**

### 8.2 Three-layer composition — base + overlay-diff → effective set

`app/verification/registry.py` resolves the effective rule set for a file's **program +
lender**:

1. **Base** = all regulatory rules + the investor rules for the file's program (Conventional
   **or** FHA, never both).
2. **Patch** with the lender's overlay (`app/verification/overlays/schema.py::LenderOverlay`),
   applied as a **diff**: an override replaces the base rule's threshold *by `rule_id`*
   (identity/logic unchanged — only the `Condition`); a custom rule is appended.
3. **Output** = a flat effective set with final thresholds.

**The investor rule is the default** — un-overridden rules fall through; no overlay → all
investor defaults. **Overlays are diffs, not full per-lender copies** (small, maintainable,
auditable). The overlay value, where specified, wins.

### 8.3 Deterministic evaluation — read → compare → emit

`app/verification/engine.py::evaluate` takes a `FileFacts` snapshot
(`app/verification/facts.py` — a typed field-path → value mapping) and the effective rules,
and for each rule reads the typed field → compares to the (possibly overlay-patched)
threshold → emits a pass/fail result. **Pure, deterministic, no AI** — the structured-data
handoff of §1 ("AI surfaces, deterministic code judges"). A datum the file does not carry yet
→ the rule is **not evaluated** (the engine never invents a verdict). The service
(`verification_engine.py`) builds the facts from the file's stated/extracted data, resolves
the rules, evaluates, and persists — **per file**, **tenant-scoped** (loan_file → company).

> The fact computations in `build_file_facts` are intentionally minimal **sample** calcs;
> the transparent DTI/LTV calculators are LP-76/77, and more typed fields get promoted as the
> real rules land (LP-82..85).

### 8.4 Two generators, one findings model

The engine emits into the **shared** LP-66 `Finding` model in a **uniform shape** (rule_id,
observed value, severity-derived status, the condition, structured source, source-location
placeholder, reasoning), marked with a new minimal `origin` field (`deterministic_rule`). The
AI cross-source layer (LP-78) feeds the **same** model as `ai_cross_source` — the findings
path is **not** engine-exclusive. LP-75 does the fuller findings-model extension (confidence /
resolution / blocking / source-location — §§3-4, 6); `origin` is the minimal field needed to
emit in the uniform shape now.

## 9. The findings model extension — implemented (LP-75)

LP-75 turns the shared `Finding` into the full **verification finding** by **extending the
LP-66 model in place** (not forking it) — the one model both generators feed (LP-74
deterministic, LP-78 AI) and the human resolves uniformly. It realises §§3-4, 6 as data +
logic. Code: `backend/app/models/finding.py`, `app/services/finding_resolution.py`,
`app/services/finding_blocking.py`, `app/verification/confidence.py`. (ADR-189.)

### 9.1 The four extensions

- **Confidence** (`confidence: float` in [0, 1], DB-checked) — the aggression dial's substrate
  (§4) and the blocking input. Deterministic threshold findings are **certain**
  (`DETERMINISTIC_CONFIDENCE = 1.0` — the comparison is exact); AI cross-source findings (LP-78)
  vary. `app/verification/confidence.py` also defines the `AggressionLevel` cutoffs
  (Conservative 0.8 / Balanced 0.5 / Thorough 0.0) — LP-79's dial picks the level.
- **Resolution states** — `FindingResolutionStatus` gains **APPLIED** + **OVERRIDDEN** beside
  the default **OPEN** (the legacy LP-17 states remain for the document flow). APPLIED
  incorporates the finding into the structured data; OVERRIDDEN dismisses it with a **required
  recorded reason** (reused `resolution_note`). **No finding is silently ignored**; resolutions
  are activity-logged (§3).
- **Blocking** — `is_file_blocked` (`finding_blocking.py`): a file is blocked from ready-to-submit
  while it has any **open in-scope** finding (actionable, open, confidence ≥ the active cutoff).
  Green findings (passes) never block. Wired into the ready-to-submit transition (a 409). LP-75
  owns the computation + a Balanced default; LP-79's dial sets the cutoff (§§3-4).
- **Source location** — `source_page` + `source_snippet` (page + verbatim snippet): the
  trust/audit anchor (§6). The LP-74 engine now populates these from the fact's source location.

### 9.2 One uniform shape across three generators

`FindingOrigin` gains `DOCUMENT_ANALYSIS`, so deterministic_rule / ai_cross_source /
document_analysis findings share **one** shape — type, amount, source document, page, snippet,
confidence, reasoning, severity (`status`), resolution, and the origin provenance marker. The
dial, the UI (LP-81), and the resolution flow treat findings uniformly — they don't care *how* a
finding was generated. The LP-74 engine emits in this full shape (certain confidence + source
location).

### 9.3 The APPLY → recompute hook

APPLYING a finding **changes the structured data** — `apply_finding` performs the change the
finding declares (the canonical `add_liability`: an undisclosed obligation is added to
liabilities), records it on `applied_record`, and calls `mark_recompute_needed` (the explicit
seam). That structured-data change is the trigger of the **AI↔deterministic interlock**: the
changed data should drive the deterministic recompute. The **full** loop is LP-78 (cross-source
+ the loop) + the calculators (LP-76/77); LP-75 builds the hook and the observable change.

## 10. The DTI calculator — implemented (LP-76)

LP-76 builds the **DTI calculator** — the headline "replace ChatGPT" surface. It is a *recompute
consumer* of §9.3's apply hook and a *reader* of the same structured data the rules engine (§8)
evaluates. Code: `app/verification/dti.py` (pure math), `app/services/dti.py` (auto-populate +
override + couple), `app/api/dti.py`, `frontend/components/file/dti/`. (ADR-190.)

### 10.1 Transparent, deterministic math

Front-end DTI = housing ÷ income; back-end DTI = (housing + monthly debts) ÷ income — **pure
deterministic arithmetic, no AI**. The monthly principal+interest is amortized from the loan
terms (not stored). The response is **fully itemized** — every income line, every housing
component (PITI + MI + HOA), every debt — each with its auto value, any override, the effective
value, and a source tag, plus the **explicit formula**. The transparency is the feature (§1's
"deterministic code judges"; a black-box DTI is untrustworthy). `Decimal` throughout; ratios
round half-up to 2 dp.

### 10.2 Auto-populated + effective limit side-by-side

Auto-populates from the structured data (stated income, stated liabilities, computed P&I,
extracted taxes/insurance/HOA) — the calculator opens *already filled* (no re-entry). The
computed back-end DTI is shown against the **effective** limit — LP-74's investor rule patched by
any lender overlay, via the same registry — with a pass/over status.

### 10.3 Override-with-audit + real-time recalc

Any field is override-able (a `DtiOverride` row, persisted, taking precedence over the auto
value); every set/clear is audited (`DTI_OVERRIDDEN`, with the prior value). The override
endpoints return the **recomputed** calculation, so the UI updates from one round-trip.

### 10.4 Coupled to findings (LP-75)

(1) The **unresolved-findings alert** queries open in-scope findings (Balanced default) and warns
when the calculation may be incomplete. (2) **Recompute on applied findings** — because the
calculation reads the structured data live, applying a finding (§9.3 adds a liability) makes the
next calculation recompute higher. The interlock landing in the calculator.

## 11. The LTV calculator — implemented (LP-77)

LP-77 builds the **LTV calculator** — the second qualification pillar (equity / risk), the parallel
to the DTI calculator (§10). It **reuses LP-76's model** (transparent breakdown + explicit formulas,
auto-population, override-with-audit, real-time recalc, the findings coupling, deterministic) applied
to the three LTV ratios. Code: `app/verification/ltv.py` (pure), `app/services/ltv.py`,
`app/api/ltv.py`, `frontend/components/file/ltv/`. (ADR-191.)

### 11.1 Three ratios, the subtleties correct + visible

* **LTV = first loan ÷ the LESSER OF** purchase price and appraised value (purchase) — the lender
  won't lend against a price above the appraisal. The basis is shown explicitly.
* **CLTV = (first + second + HELOC drawn) ÷ value.**
* **HCLTV = (first + second + HELOC CREDIT LIMIT) ÷ value** — the full line, not the balance (a
  $0-balance / $40k-line HELOC pushes HCLTV above CLTV). Pure `Decimal` math, half-up to 2 dp.

The lesser-of and credit-limit subtleties are the trust mechanism (what ChatGPT fumbles).

### 11.2 Refinance-aware

The loan purpose drives the denominator + the limit: purchase → lesser-of; rate/term refi →
appraised value; cash-out refi → appraised value + a **stricter** limit. A nullable `refinance_type`
(rate_term / cash_out) carries the cash-out distinction.

### 11.3 Reuses the DTI model + the appraised-value graceful handling

Auto-populates the loan + property inputs; the **appraised value** comes from the MISMO valuation
(else the estimated value) and is **override-able** where absent (the appraisal isn't Tier-1 yet).
Every input is override-able with an audit log (`ltv_overridden`); the override endpoints recompute
in the response. The effective limit (purpose-varying) resolves via LP-74's registry (sample LTV
rules; overlay-patchable). The unresolved-findings alert + recompute-consumer reuse §9.3 / §10.4.

## 12. The AI cross-source layer + the APPLY→recompute loop — implemented (LP-78)

LP-78 builds the **"AI surfaces"** half of §1 (§8 built the deterministic judge) and **closes the
APPLY→recompute loop** (§3 / §9.3 / §10.4). Code: `app/ai/cross_source.py` (the AI boundary),
`app/services/cross_source.py` (assemble + emit), `app/tasks/cross_source.py` (the worker pass),
`app/api/verification.py`, `frontend/components/file/verification/`. (ADR-192.)

### 12.1 One general capability → structured findings

The cross-source layer is **one general AI capability, not a rule per check**: it reads the stated
MISMO data against the verified document extractions and surfaces whatever "doesn't line up" — guided
toward high-value comparisons (income variance, employer, gift) but not limited to them, so it catches
**known and novel** discrepancies (the undisclosed obligation no rule covers). The full ~15-20 set is
LP-86. It emits **structured findings only** (typed) into LP-75's shared model
(`origin=ai_cross_source`, confidence, source-location) — generator two of "two generators, one model"
(§1). Findings land **OPEN** — the AI surfaces candidates for human review (§2), never auto-applied.

### 12.2 The APPLY→recompute loop closes

For recognized remediable types the emit attaches an **apply spec**; applying a finding (LP-75's hook)
changes the structured data → the DTI/LTV calculators (which read it live) recompute. End-to-end: an
**undisclosed obligation** → apply → added to liabilities → DTI **higher**; an **income variance** →
apply → stated income corrected → DTI **higher**. LP-78 extends the apply hook with `correct_income`
and makes applying mark verification stale.

### 12.3 Manual trigger + staleness (§5)

The pass runs on a **manual trigger** (the worker runs the AI call — it compares two sides and is a
real cost). `LoanFile.verification_stale` is set on any document change (upload / type override /
replace) and when a finding is applied, and cleared when the pass re-runs — a visible "re-run"
indicator. Auto-re-run is deferred (the dial re-filters without re-running — LP-79). PII is assembled
for the AI call and **never logged**.
