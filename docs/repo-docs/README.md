# Project documents — index

_Suggested home: `docs/project/` in the repo. 2026-08-11._

⚠️ **Start with `handoff-summary-2026-08-11.md`** — it is the entry point and carries the key paths, the
current state, the lessons, and the plan.

---

## Current — read these

| document | what it answers |
|---|---|
| **`handoff-summary-2026-08-11.md`** | ⚠️ **Where everything stands, what is in flight, what comes next.** The entry point |
| `verification-architecture-v2.md` | How the engine works — snapshot, tags, rules, verdicts, the five gates |
| `extraction-schema-standard.md` | How a schema is designed — the six tests a field must pass, nesting rules, PII |
| `bench-v2-analysis.md` | The v2 measurement in full — 303 documents, wins, regressions, the accuracy ledger |
| `extraction-accuracy-problem.md` | ⚠️ **Why a wrong value is worse than a missing one**, and why prompts do not fix it |
| `finish-the-rule-engine-plan.md` | The four phases from 37 live to ~100 |

## Executed — kept for the reasoning, not the instructions

| document | note |
|---|---|
| `classification-remediation-plan.md` | Phases 1-2 done (LP-462/463); **Phase 3 deliberately deferred** — re-measure before adding hard-coded cues |
| `missing-types-plan.md` | 7 types added (LP-465/466/467) |
| `missing-extractors-plan.md` | ⚠️ Its headline "64 documents" was stale — most were absorbed or were routing problems |
| `schema-gap-remediation-plan.md` | 3 phases done (LP-458/460/461) |
| `extractor-failure-remediation-plan.md` | LP-473 — **none of the three was an extraction bug** |

## ⚠️ Superseded — do not follow

**`mortgageboss-progress-summary.md`** *(not included here)* stops at **LP-433** — before the generator, the
91 extractors, the tier merge, the vocabulary reconciliation, generic lists, cross-source verification,
Bedrock, and the entire bench exercise. **The handoff summary replaces it.**

---

## The shortest possible orientation

**37 rules live of ~113 real targets. 109+ extractors wired. The engine is built.**

**The remaining rule work is gated on inputs — a document corpus, Priya's time, API credit, and one design
decision (the agency/overlay structure) — not on more engineering.**

⚠️ **And the single most important discipline:** the documents are the gate of record. Every plan in this
folder that survived contact with real documents did so because someone read the PDF instead of trusting a
report about it — **and several claims that looked solid dissolved when checked.**
