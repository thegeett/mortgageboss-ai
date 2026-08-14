# Verification Architecture v2 — AI-Evaluator Engine

**Status:** Supersedes the verification design in the V1 Build Plan (Unified v2),
specifically §3.8, §3.9, §3.10, and §3.11, on every point where they differ from this
document. Those sections remain valid as the *history* of how the design evolved; this
document is the current architecture for the verification engine.

**Supersedes (verification only):** V1 Build Plan §3.8–3.11
**Does not touch:** MISMO import (§1.5), document handling (§2), calculators (§3.5),
communication (§4), conditions (§4.5), or any non-verification phase. Those stand as
written.

**Why this exists:** the earlier plan built verification as a deterministic Python rules
spine with AI confined to perception (extraction/classification) and a cross-source
discovery pass. Real build experience showed the deterministic-per-rule approach does not
scale to the diversity of real loan files — encoding a decision path for every edge case
is not achievable, and the determinations that matter (what income qualifies, whether a
deposit is sourced, whether a story is plausible) are judgment, not arithmetic. This
document inverts the default: **AI evaluates the rules; deterministic code is demoted to a
narrow integrity check.**

---

## 1. The inversion (the core change)

**Old default (superseded):** deterministic Python is the evaluator spine; AI only
perceives. "Rules are deterministic Python; AI is not in the rules path" (§3.1).

**New default:** **AI is the evaluator for all ~130 rules.** Each rule is a *spec* — its
description, fire-condition, required inputs, and threshold parameter — and the AI reads
the frozen snapshot (and underlying documents) and renders the verdict against that spec.
Deterministic code is demoted from "the spine" to a **thin numeric-integrity check** that
re-runs only the final arithmetic comparison for threshold rules, because that single
step (comparing two already-established numbers) is the one thing LLMs do unreliably.

What stays deterministic — and *only* this:
1. **Snapshot freeze** — facts are assembled once and frozen, so a run is replayable.
2. **Numeric-integrity check** — for a rule whose verdict rests on "X compared to Y,"
   code re-runs that comparison on the values the AI surfaced. Not the income
   computation, not the sourcing judgment — only the terminal compare.

Everything else — sourcing, matching, plausibility, adequacy, consistency, income
determination, and the verdict itself — is the AI's judgment.

**Authoring model:** adding or changing a rule is writing a *spec*, never writing an
evaluator. This is the property that scales to file diversity.

---

## 2. Full pipeline (every run)

```
Documents (MISMO XML, PDFs)
      │
      ▼
1. AI EDGE — fact production
   extract PDF fields · classify docs · return UNKNOWN when unsure
      │  facts
      ▼
2. FROZEN SNAPSHOT   ← the boundary; no AI writes facts past here
      │
      ├──────────────────────────────┐
      ▼                              ▼
3a. AI EVALUATOR (all 130 rules)   3b. CROSS-SOURCE LANE (whole file)
    judges each rule vs its spec       reads everything, no fixed scope
    emits verdict + values relied on   surfaces discrepancies no rule scoped
      │                              │
      │ threshold rules              │ matches a rule → feeds it as evidence
      ▼                              │ novel → discovery finding "AI found — verify"
   NUMERIC-INTEGRITY CHECK           │ recurring → graduates into a scoped rule
   re-runs only final X vs Y         │
      │                              │
      └──────────────┬───────────────┘
                     ▼
4. FINDING LIFECYCLE — four states, (rule_id, subject_key) identity, append-only log
```

Every verification run rebuilds the snapshot from scratch and flows the whole way through
to findings. **The snapshot is stateless** (born and discarded each run); **findings are
stateful** (persist across runs, matched by identity). The run is a pure function; the
final reconciliation step is where the stateless run updates the persistent finding
history.

---

## 3. Run trigger (unchanged intent from §3.8, restated)

- **Today: manual.** A "Run verification" button. When any document changes (upload, type
  override, re-extraction) the verification is marked STALE; the processor triggers the
  run. The trigger fires the *whole* run — snapshot rebuild through findings — not a step
  after the snapshot.
- **Unchanged re-runs are cache-served.** If the stated + verified inputs are unchanged, a
  re-run returns the existing findings without calling the AI (input-fingerprint cache),
  with a force-rerun escape hatch. Clicking on an unchanged file is cheap and
  deterministic.
- **Future: automated.** Re-run on document change is a later phase, as the old plan
  already anticipated.

---

## 4. The AI evaluator

Each rule spec must force the model to expose its work, because that is what makes both
the integrity check and the audit trail possible:

- **Verdict** — fired / satisfied / couldn't-check.
- **Operative values** — the specific numbers/facts the verdict rests on (e.g. deposit
  $12,000; unsourced remainder $12,000; monthly qualifying income $8,000; threshold
  $4,000). A verdict without exposed values is not acceptable — it defeats both the
  numeric check and auditability.
- **Evidence** — the documents/snippets the verdict relied on.
- **UNKNOWN discipline** — if a required input is missing, the AI must emit couldn't-check,
  not confabulate a pass. To keep this from resting on model goodwill, the harness checks
  required inputs are present *before* asking the AI to judge, so absence is caught
  mechanically and the AI is only asked to judge when the material exists.

### Rule kinds (how each verdict is treated)
- **Threshold** — verdict rests on a numeric compare → passes through the numeric-integrity
  check.
- **Match / presence / judgment** — verdict taken as the AI rendered it (sourcing,
  consistency, plausibility, adequacy).

---

## 5. The numeric-integrity check (all that remains of the deterministic spine)

For threshold rules, a single shared check re-runs the final comparison on the values the
AI surfaced — confirming, e.g., $12,000 > $4,000. It is **not** a per-rule evaluator, does
**not** recompute income or re-judge sourcing, and exists solely to catch the silent
arithmetic slip LLMs are prone to. One function, not 130.

---

## 6. Cross-source discovery lane

Structurally different from the scoped rules: its value is that it does *not* declare its
inputs. It reads the whole file and surfaces tensions no rule anticipated. Runs last, over
the same frozen snapshot. Each claimed discrepancy must name the specific documents and
values in tension (a discrepancy it can't point at is a hallucination).

Output splits three ways:
1. **Matches an existing rule** → routed *into* that rule as evidence; surfaces under that
   rule's identity, not as a duplicate.
2. **Genuinely novel** → its own finding, labeled "AI found — verify," medium-trust, source
   documents shown. Enters the same lifecycle (four states, identity, event log).
3. **Recurring across files** → graduates into a scoped rule (write it a spec). FR-5
   already made this trip.

**Caution (locked):** this lane is the least reproducible, least auditable part of the
engine, by design. It is acceptable *only* because discovery findings are labeled and
human-verified — they never block submission on their own authority the way a validated
scoped rule does. Advisory-with-teeth: loud enough a real discrepancy can't be missed,
gated enough a hallucinated one can't silently sink a file.

---

## 7. Finding lifecycle — FOUR states, FOUR tabs

> **This supersedes the §3.9 "two tabs / three states" model.** The old plan locked two
> tabs (Needs attention, Satisfied) with three states, and §3.11 kept not-applicable
> *silent*. This document consciously overrides both: four states, four tabs, and
> not-applicable is surfaced.

### Four states
| State | Meaning | Blocks submit? |
|---|---|---|
| `open` | fired, awaiting fix | **yes** |
| `satisfied` | ran and passed, evidence linked | no |
| `no-longer-applies` | the checked thing genuinely stopped existing on the file | no |
| `couldn't-check` | rule applies but a required document/fact is missing | **yes** |

### Four tabs
1. **Needs attention** — `open` + `couldn't-check`. Both block. (couldn't-check sits here,
   never disguised as a pass — the false-green guard.)
2. **Satisfied** — passed, evidence shown.
3. **History / no-longer-needed** — retired findings whose subject left the file.
4. **Not applicable** — rules whose *scope* was false for this file's nature (FHA rule on a
   Conventional loan, condo rule on a single-family home), each showing its skip reason.

### The three "not firing" cases must stay distinct
- **Stopped existing** → `no-longer-applies` (Tab 3) — was a finding, subject left.
- **Never relevant** → not applicable (Tab 4) — scope false from the first run, never a
  finding.
- **Lost visibility** → `couldn't-check` (Tab 1) — rule applies, thing might exist, we
  can't see it. Blocks.

Collapsing any of these into another is the core failure mode. In particular,
not-applicable (Tab 4, scope-false) must never absorb couldn't-check (data-missing) — the
distinction between "doesn't apply to this file" and "we couldn't verify" is the whole
honesty contract.

### Tab 4 toggle
The Not-applicable tab is dev/debug transparency, gated behind a `show_not_relevant_tab`
frontend flag. The flag is **purely presentational** — the engine always computes and
stores the not-applicable classification in every environment (audit record); the flag
only controls whether the UI renders the tab.

---

## 8. Identity, immortality, reconciliation

- **Identity = `(rule_id, subject_key)`.** `rule_id` = the check (~130, fixed).
  `subject_key` = the specific deposit/borrower/tradeline/property (or `whole_file`).
  Derived from durable attributes, never array position, so it's stable across runs.
- **Uniqueness:** `(loan_id, rule_id, subject_key)` — one live finding per
  check-per-subject-per-file. Enables per-borrower scoping (IN-5 on borrower A and
  borrower B are distinct findings with independent states).
- **Reconciliation each run:** for each firing result compute `subject_key`; match against
  the prior run's live findings; found → carry forward (keep id + history, update state);
  not found → mint a new finding.
- **Immortality:** once a finding fires it never leaves the surface silently — it only
  moves to a visible, labeled state with a reason string + timestamp. No "gone" state.
  Append-only event log per finding answers "where did this go, and why?"
- **Retire / revive:** a retired (`no-longer-applies`) finding stays retired; only an exact
  `subject_key` match revives it; a genuinely different subject → new finding. Retiring a
  finding never suppresses future firing of that rule class.

---

## 9. Action buttons on findings (retained from §3.7–3.8)

Per-finding actions remain as the old plan locked them:
- **Override** (with reason), **Accept risk** (with reason), **Add note**
- **Request docs** — creates a needs-list item; the finding stays `open` until satisfied.
  This is the self-heal seam: finding → spawns a need → need satisfied → finding
  re-resolves on the next run.
- **View fix** (for findings with an apply-spec) — opens an itemized before/after preview
  (affected lines, totals, recomputed DTI/LTV, any status change) before confirming.
- **Undo** on resolved findings — reverses an applied data change and recomputes, or flips
  an accept-risk/override back to `open`.

---

## 10. What did NOT change

- **AI edge / perception** (extraction, classification) — same role, still produces the
  snapshot facts.
- **Snapshot as an immutable per-run frozen artifact** — same (§3.11), with
  `absent ≠ empty` and provenance on every fact.
- **Rules-as-data** — `verification_rules` table, git-tracked seed, `rule_change_audit`,
  threshold params editable live and Priya-validated before go-live. What changed is that
  the `evaluator` a rule points to is now an AI-judged spec kind by default, not a
  deterministic Python class.
- **Calculators** (§3.5) — DTI/LTV/MI/reserves stay deterministic; they own computed-ratio
  conclusions, and the cross-source lane stays out of their territory.
- **AU-2 keystone** — "whatever DU findings require" (reserves, statement months, which
  deposits need sourcing, student-loan treatment) still routes through AUS reconciliation.
- **Blocked rules + golden-file eval set (LP-143)** — still gated on blocker-doc
  extractors. Now *more* load-bearing: since AI evaluation is probabilistic, the eval set
  is the primary guarantee against silent regressions, not an optional QA step.

---

## 11. The three risks this architecture must manage

Inverting the default moves the hard problems rather than erasing them:

1. **Values must be exposed.** If the AI returns a bare verdict, both the numeric check and
   auditability are lost. The spec format must *require* structured operative values.
2. **UNKNOWN discipline is on the AI.** A false pass on missing data is invisible.
   Mitigation: the harness checks required inputs are present before asking the AI to
   judge, keeping the one reliable part of the old deterministic design.
3. **Reproducibility is now probabilistic.** The golden-file eval set (LP-143) becomes the
   spine of trust — every rule spec needs golden files with known verdicts, run
   continuously, so a spec or model change that breaks a rule is caught. In the old design
   the code was the guarantee; here the eval set is.

---

## 12. Extraction gaps blocking written rules (revise list — added 2026-07-28)

A recurring class of blocker, found repeatedly once rules started being written against real
inputs: **a rule is well-specified and its logic is trivial, but the field it reads is not
extracted.** These are not rule-design problems — they are **extractor scope problems**, and
they cluster enough to be worth tracking as one list.

### The three failure shapes

| shape | what it means | example |
|---|---|---|
| **Not solicited** | the extraction prompt never asks for the field, so it appears nowhere — not even in the catch-all | `loss_settlement_basis` on the homeowners binder (IH-1) |
| **Catch-all only** | the AI returns it, but into the free-form `additional_sections` blob — untyped, uncoerced, varies per document | seller credit, addenda, personal property, contingency dates (PC-4/6/8/9) |
| **Extracted but not surfaced** | typed in the extractor, then dropped at the snapshot boundary because `_scalar()` discards nested structures | Schedule C / Schedule E on the tax return (fixed by LP-421) |

**The rule that governs all three (LP-405):** a rule may only depend on a **typed-core** field.
The catch-all is free-form, per-document, and uncoerced — nothing built on it can be trusted.

### The open list

| rule(s) | field needed | shape | notes |
|---|---|---|---|
| **IH-1** *(insurance adequacy)* | `loss_settlement_basis` (`replacement_cost` / `actual_cash_value`), **plus per-item granularity** for the roof | not solicited | Priya's rule is a boolean check, not the retired coverage-vs-loan arithmetic (ADR-340). A roof settled on ACV must **not** fail a replacement-cost dwelling. A guard test turns red when the field is added. |
| **PC-4, PC-6, PC-8, PC-9** *(contract terms)* | seller credit, addenda, personal property, contingency dates | catch-all only | Confirmed catch-all by LP-407-1. Needs typed extraction + golden files. |
| **IH-2, IH-8** *(mortgagee clause, wind/hail)* | the respective policy clauses | catch-all / unknown | LP-415 classified both as needing an extension. |
| **The child-support rule** *(from Priya's IN-13 notes)* | the youngest child's **age** | free text only | Today it exists only inside `other_income_description`. Once extracted, the rule is pure arithmetic (`18 − age >= 3`) and needs no calibration (ADR-334/337). |
| **IN-12 / IN-13 scope confidence** | — | resolved, but **unvalidated** | The tax-return extractor is a self-declared `STARTER` prompt, never run against a real return (ADR-333). IN-12 is **live** on it; golden files remain a prerequisite for trusting the scope gate. |

### Scoping indicators that do not exist

Several rules need a *what-kind-of-thing-is-this* signal that no tag provides:

- **`property.type`** (condo / co-op / PUD) — IH-1 must exclude condos, since a master policy takes a different test (**IH-7**, ≥100% of project replacement cost).
- **`loan.purpose`** — built by LP-424, but the predicate is **deferred**: applying it would regress PC-2/PC-7 on LF-6T3N (which carries no `loan.purpose`), and no refinance fixture exists in the snapshot path.

### Why this list matters

**Extraction is now the constraint, not rule-writing.** ~55 of the remaining in-scope rules sit
behind absent extractors (credit, title, condo questionnaire, MI certificate, appraisal, flood),
and the list above adds a second, cheaper tier: **fields missing from extractors that already
run.** Those are bounded extensions rather than new builds — and each one is a useful rehearsal
for the golden-file discipline the absent extractors will require.

**Every extension needs golden files.** These documents have no independent source-of-truth: a
misread field produces a confident wrong verdict with nothing to contradict it. The LP-143 eval
set is the only structural defense, which is why an extension is never "just wiring."

### The tripwire pattern (worth reusing)

LP-431 left a **guard test that fails when the blocker is removed** — it passes while
`loss_settlement_basis` is absent, and turns red the moment someone adds it, signalling that
IH-1 is now buildable. This beats a note in a document: it puts the "this is now unblocked"
signal in front of whoever does the unblocking, at the moment they do it.
