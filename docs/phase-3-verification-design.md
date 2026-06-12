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
