# v2 "AI-Evaluator Engine" — Substrate Audit vs. `phase3_5_1`

**Type:** read-only reconnaissance / decision-support. No code changed; no branch
checked out. All `phase3_5_1` inspection was done via `git show` / `git diff` from the
current branch (`phase3_new_AI_arch_finding`), working tree untouched.

**Date:** 2026-07-09
**Author branch at time of audit:** `phase3_new_AI_arch_finding` @ `0cbeeb3` (tip of Phase 3, == `main`)

## Purpose

Measure the deterministic data-driven engine built on `phase3_5_1` (LP-117.5 → LP-125R)
against the **intended v2 "AI-evaluator" architecture** and produce a
**KEEP / REPLACE / BUILD-NEW** map, so we can pick the cheapest correct base to build v2 on.

### The v2 design being targeted (summary)

- **AI is the EVALUATOR** for each rule — not deterministic Python. Each rule is a spec;
  the AI reads the frozen snapshot and renders the verdict against that spec.
- **Applicability decided PER RULE, INSIDE the same single AI pass** as the finding
  ("does this apply? if yes, produce the finding"), three-valued: yes / no-with-reason /
  can't-tell (can't-tell → couldn't-check → blocks submit).
- **Deterministic code demoted to two narrow jobs:** (1) freeze the snapshot,
  (2) a numeric-integrity check that re-runs ONLY the final X-vs-Y comparison for
  threshold rules. It does NOT judge.
- **Whole-file cross-source discovery lane runs last** (AI, whole file, no fixed scope):
  matches feed existing rules, novel → labeled "AI found — verify", recurring → graduate
  to scoped rules.
- **Finding lifecycle: four states** (open / satisfied / no-longer-applies / couldn't-check);
  open + couldn't-check block submit. Identity = `(rule_id, subject_key)`, unique per
  `(loan_id, rule_id, subject_key)`, append-only event log.
- **Human-in-the-loop already exists** (processor review + Accept-risk / Waive / Override)
  and is the accuracy backstop; AI must expose reasoning + operative values + evidence.

---

## Part A — Branch topology & mechanics

1. **Divergence point.** `git merge-base phase3_new_AI_arch_finding phase3_5_1` = **`0cbeeb3`**,
   which is *also the current HEAD* and the tip of `main`. The current branch is the
   merge-base itself — it has **zero** commits `phase3_5_1` lacks; `phase3_5_1` is strictly
   **18 commits ahead**.

2. **The 18 commits (`0cbeeb3..phase3_5_1`), grouped:**

   | LP | Commit(s) | What it built |
   |----|-----------|---------------|
   | LP-117.5 | `6235883`, `c3170aa` | Phase-3.5 architecture ADR + rule reference docs + `playbook_id`; fact-namespace foundation audit |
   | LP-118 | `95de1a8` | **DB rule registry**: `verification_rules` + `rule_change_audits` tables + 140-row seed (`rule_seed.json`) |
   | LP-118.6 | `3c37d7a`, `a3df733`, `42a066d` | **Fact-namespace**: frozen typed per-run snapshot + canonicalization + reference docs |
   | LP-118.7 | `40ef93a` | **Store-everything**: persist parsed-but-dropped MISMO fields (borrower current address+type, property county) |
   | LP-118.8 | `b87151b` | **Borrower↔document linking** (deterministic name matcher + link table) |
   | — | `3fb1448` | Adds `phase3_5_2.md` plan |
   | LP-119 | `8df33cb` | **Applicability filter engine** (Ternary + ApplicabilityState), thin slice on AS-5 |
   | LP-120 | `3872301` | **Evaluator framework** (Protocol + registry) + DET-FUZZY confidence |
   | LP-121 | `1d44006` | **Runner** (snapshot → classify → evaluate → four buckets) |
   | LP-122R…125R | `dd20e9b`,`8209e94`,`a8310be`,`a8654d6`,`a5971cb`,`308fac1` | Four concrete deterministic evaluators: AS-5 gift-letter, AS-8 bank continuity, employer-count, AS-1 large-deposit; honesty-contract fixes |

3. **Is `phase3_5_1` merged anywhere?** **No.** `git branch --contains 308fac1` → only
   `phase3_5_1` and `origin/phase3_5_1`. It is **not** an ancestor of `main`/`origin/main`.
   Local == origin (0/0). Last commit **2026-07-08**. → It is **live, authoritative, but
   unmerged** work — the most-advanced branch in the repo, not a stale spike, but not yet
   integrated into trunk.

4. **Trunk situation.** Nothing is ahead of `phase3_5_1`
   (`git rev-list --count phase3_5_1..<every branch>` = 0 for all). There is **no
   integration branch**; `main` still sits at the Phase-3 tip. `phase3_5_1` *is* the
   de-facto frontier. The current branch `phase3_new_AI_arch_finding` is a fresh cut at the
   Phase-3 tip — behind `phase3_5_1` — and the new-arch `.pyc` in its working tree are
   leftovers from a prior checkout of `phase3_5_1` (untracked, gitignored).

---

## Part B — What `phase3_5_1` provides as substrate (per component)

**1. Frozen `FactNamespace` snapshot (+ absent/empty sentinels, `FactSource`) — KEEP-AS-IS.**
`fact_namespace/snapshot.py` — frozen Pydantic graph (`borrowers[]`, `property`,
`liabilities[]`, `assets[]`, `transactions[]`, `bank_statements[]`,
`computed{ltv,cltv,dti,mi,reserves}`, `documented{}`), `Fact.present()`/`Fact.missing()`
+ a 10-value `FactSource` enum distinguishing three `ABSENT_*` reasons. This *is* v2's
deterministic job #1 ("freeze the snapshot"). Extend only if the AI evaluator needs fields
the snapshot doesn't yet carry.

**2. `verification_rules` table + seed/migration (LP-118) — KEEP-BUT-EXTEND.**
`models/verification_rule.py` + migration `d4b8f1a63c27`; 140 seeded rows
(`docs/rules/rule_seed.json`: 18 `xsrc.*` live + 122 `pb.*` playbook stubs; 19 enabled,
4 validated). Already carries `evaluator`, `applicability` JSON, `params` JSON,
`message_template`, `canonical_type`, `severity`, `confidence_mode`, `playbook_id`,
`validated`, `enabled`. **Extend:** it has **no natural-language criteria/spec column**
(the crux — see Part C). `rule_change_audits` (change history) → KEEP-AS-IS.

**3. Rule record shape — KEEP columns, but REPLACE the semantic center of gravity.**
Today a rule = structured data-condition: `evaluator` dispatch key + `applicability.triggers`
(`op/value`) + numeric `params` (e.g. `{large_deposit_pct:50}`) + `message_template`
(output wording). The judging logic is **not in the row** — it's Python. v2 moves the
judgment into a prose spec the AI reads, so the row's authoritative content shifts from
"condition" to "criteria_spec + evidence_required," with `params`/`condition` demoted to
the numeric-integrity check's inputs. Columns survive; their meaning changes.

**4. `evaluators/` registry + `rule_id` dispatch — KEEP-BUT-EXTEND (dispatch); REPLACE (bodies) → but repurpose, don't discard.**
`evaluators/contract.py` defines an `Evaluator` Protocol
`evaluate(snapshot, params) -> EvaluationResult`; `registry.py` dispatches by `rule_id`
(hardcoded bootstrap, 4 evaluators built). v2 adds an **AI evaluator implementing the same
Protocol** — the seam is clean. The four existing deterministic evaluators
(large_deposit/gift_letter/continuity/employer_count) + LP-74's `satisfies()` comparator
are exactly the "**numeric-integrity re-check**" v2 wants (deterministic job #2) — so they
get **repurposed as the verifier**, not deleted.

**5. `EvaluationResult` contract — KEEP-BUT-EXTEND.**
Already models almost everything v2's AI evaluator must return: `verdict`
(`finding`/`satisfied`/`couldnt_check`), `confidence` + `confidence_mode`,
`provenance: list[{path, observed}]` (the evidence trail), `message`, and an `apply_spec`
hook. **Extend:** an explicit applicability decision (or fold `doesnt_apply` in), first-class
**operative values**, an AI **reasoning** field, and an `ai/judged` confidence-mode. This is
the single most reusable piece for v2.

**6. `applicability/` engine + Ternary / ApplicabilityState — REPLACE as decision authority; KEEP the vocabulary; optionally KEEP the engine as a cheap pre-filter.**
`applicability/schema.py` gives `Ternary{true,false,unknown}` and
`ApplicabilityState{DOESNT_APPLY, COULDNT_CHECK, READY_TO_RUN}` — v2's exact vocabulary,
**keep it**. But the *engine* is a **separate, up-front, deterministic** scope/trigger pass
— precisely the structure v2 inverts ("applicability decided inside the same AI call"). So
the engine is REPLACED as the authority; it can survive only as an optional cheap
deterministic **pre-filter** (skip obviously-out-of-scope rules before spending an AI call).

**7. `runner.py` — KEEP-BUT-EXTEND (restructure).**
Orchestration skeleton is the right shape and already yields **exactly four buckets**
(`findings`/`satisfied`/`couldnt_check`/`doesnt_apply`) with a `provisional` flag when
`rule.validated=False`. **Extend:** swap the evaluate step to per-rule AI calls
(async/parallel), insert the numeric-integrity post-check, add the whole-file discovery
lane, and add **persistence + API/Celery wiring** — which `phase3_5_1` explicitly deferred
(runner is orphaned; persist = LP-140/162, retire-live-path = LP-161).

**8. Canonicalization layer (+ `canonicalization_map.json`) — KEEP-AS-IS.**
On `phase3_5_1` the map **is committed** (`fact_namespace/canonicalization_map.json`) — the
file that was missing as bytecode-only on the current branch. Feeds the frozen snapshot; v2
keeps deterministic snapshot construction.

**9. Reconciliation + finding identity — KEEP the logic; BUILD-NEW the persistence.**
`finding_reconcile.py` and `finding_identity.py` are **byte-identical to the current branch**
(`git diff` empty) — same KEEP/ADD/DROP(soft-delete)/RETAIN, same normalized
`(type/rule, subject)` identity. But `subject_key` is a **JSON field, not a column**, there
is **no DB uniqueness**, and **no event-log table**. v2's persisted identity model is a
build (Part C).

**10. Store-everything (LP-118.7) — KEEP-AS-IS.** Migration `e2d5b8c1f4a9` persists borrower
`current_address_line/city/state/postal/`**`type`** + `properties.county`. The
`current_address_type` column is the **address-type-trap fix** (lets a future rule avoid
comparing a Mailing/Prior address as Current). Pure snapshot-enrichment for the AI.

**11. Borrower↔document linking (LP-118.8) — KEEP-AS-IS.** `document_borrower_links` table
(unique `(document_id, borrower_id)`, `confidence`+`method` provenance, joint-doc capable)
+ `documents.borrower_match_note`. Matching is **deterministic fuzzy name matching,
explicitly NOT AI**. Feeds `borrowers[].documents[]` into the snapshot.

---

## Part C — Gap analysis: what v2 needs that NEITHER branch has

- **The AI evaluator itself** (rule-spec + snapshot → verdict + operative values + evidence
  + applicability, one pass). **Absent on both.** `phase3_5_1`'s evaluators are 100%
  deterministic Python — a grep across `evaluators/`, `applicability/`, `runner.py` for
  `anthropic|llm|client.complete` returns **zero**, and the contract forbids "call AI at
  evaluation time." The only AI in the whole `verification/` tree is `finding_guidance.py`
  (post-hoc prose, not in the verdict path). **BUILD-NEW.**
- **Rule-as-SPEC format** (prose criteria + evidence-required the AI judges against).
  **Absent on both.** Today specs live in *ticket markdown* (LP-123R/124R/125R "## The
  spec"), unreachable by the engine; the DB row has only `name` (label) and
  `message_template` (output). Adding `criteria_spec`/`evidence_required`/`spec_version`
  columns is a **schema change (new Alembic migration)** — no existing column cleanly holds
  it (the only migration-free hack is abusing `params` JSON, which violates its "numeric
  dials" contract). **BUILD-NEW.**
- **Applicability-inside-the-AI-call.** **Absent on both** (current design is a separate
  deterministic pass). The deterministic engine is reusable only as an *optional cheap
  pre-filter*; the per-rule fused decision is new. **BUILD-NEW.**
- **Numeric-integrity post-AI verifier.** **Absent as a stage on both**, but its guts already
  exist — the deterministic evaluators + LP-74 `satisfies()` comparator can be lifted into
  it. **BUILD-NEW (assemble from existing parts).**
- **Persisted four finding states** (open/satisfied/no-longer-applies/couldn't-check) +
  submit-blocking on couldn't-check. **Absent on both.** `finding.py` is byte-identical
  across branches: severity `red/yellow/green` × resolution
  `open/applied/overridden/resolved/accepted_risk/waived`; **no `satisfied`, `couldnt_check`,
  or `no_longer_applies`** persisted. `phase3_5_1`'s four buckets are **runtime-only**
  (`VerificationRunResult`), never written to `findings`. Submit-blocking today keys on open
  red findings; extending it to block on couldn't-check is new. **BUILD-NEW.**
- **`(loan_id, rule_id, subject_key)` DB uniqueness + append-only event log.** **Absent on
  both** — `subject_key` is JSON, findings indexes are all non-unique, and there is no
  `finding_events`/history table (audit is mutable status + `activity_logs`). **BUILD-NEW.**
- **Whole-file cross-source discovery lane with graduate-to-rule loop + "AI found — verify"
  labeling.** **Partially present:** the AI `cross_source` pass already surfaces novel
  discrepancies and `canonical_type` is the graduation dedup key — but the
  *recurring→scoped-rule graduation automation* and the labeling are not built. **BUILD-NEW
  (seed from the existing AI cross-source pass).**
- **Golden-file eval set (LP-143).** **Absent on both** (no `golden/`, no eval harness, only
  3 MISMO XML fixtures, no PDFs; LP-143 is a deferred line in `phase3_5_2.md`, no ticket
  file). Now **load-bearing** because AI evaluation is probabilistic and the human backstop
  needs a regression corpus. **BUILD-NEW.**

---

## Part D — Decision-support table

| Component | On this branch? | On `phase3_5_1`? | v2 verdict | One-line rationale |
|---|---|---|---|---|
| Frozen `FactNamespace` snapshot + absent sentinels | ❌ (bytecode only) | ✅ source | **KEEP-AS-IS** | Exactly v2's "freeze the snapshot"; frozen, typed, provenance-bearing |
| Canonicalization + `canonicalization_map.json` | ❌ (map missing) | ✅ committed | **KEEP-AS-IS** | Deterministic snapshot-building v2 retains |
| Store-everything (LP-118.7) | ❌ | ✅ | **KEEP-AS-IS** | Richer snapshot (current address+type, county) for the AI |
| Borrower↔document linking (LP-118.8) | ❌ | ✅ | **KEEP-AS-IS** | Deterministic link table feeds `borrowers[].documents[]` |
| `verification_rules` table + `rule_change_audits` + seed | ❌ | ✅ | **KEEP-BUT-EXTEND** | Good rule home; needs prose `criteria_spec` columns |
| Rule record shape (evaluator/applicability/params/template) | ❌ | ✅ | **KEEP-BUT-EXTEND** | Columns survive; judgment moves from condition → spec |
| `EvaluationResult` contract (verdict/confidence/provenance) | ❌ | ✅ | **KEEP-BUT-EXTEND** | Already models verdict+evidence+confidence; add operative-values+reasoning |
| `evaluators/` registry + `rule_id` dispatch | ❌ | ✅ | **KEEP-BUT-EXTEND** | Protocol seam clean; add an AI evaluator implementing it |
| Deterministic evaluator bodies (AS-1/5/8, employer-count) + `satisfies()` | ❌ | ✅ | **REPLACE→REPURPOSE** | Demoted from judge to the numeric-integrity re-check |
| `applicability/` engine (scope/trigger deterministic pass) | ❌ | ✅ | **REPLACE** | v2 fuses applicability into the AI call; keep only as optional pre-filter |
| Ternary / ApplicabilityState / Verdict enums | ❌ | ✅ | **KEEP-AS-IS** | v2's exact three-valued vocabulary |
| `runner.py` orchestration (four-bucket output) | ❌ | ✅ (orphaned) | **KEEP-BUT-EXTEND** | Right skeleton + four buckets; swap eval step, add persist/wire |
| Reconciliation logic (keep/add/drop/retain) | ✅ | ✅ (identical) | **KEEP-AS-IS** | Cross-run reconcile reusable unchanged |
| Finding identity `(rule_id, subject_key)` | ✅ (app-layer) | ✅ (identical) | **KEEP-BUT-EXTEND** | Logic keeps; promote `subject_key` to a column |
| **AI evaluator (spec+snapshot→verdict)** | ❌ | ❌ | **BUILD-NEW** | The core inversion; no AI-eval path exists |
| **Rule-as-prose-SPEC + evidence-required** | ❌ | ❌ | **BUILD-NEW** | Specs live in ticket markdown; needs schema columns |
| **Applicability-inside-the-AI-call** | ❌ | ❌ | **BUILD-NEW** | Current design is a separate deterministic pass |
| **Numeric-integrity post-verifier stage** | ❌ | ❌ | **BUILD-NEW** | Assemble from existing deterministic evaluators |
| **Persisted 4 finding states + block-on-couldn't-check** | ❌ | ❌ | **BUILD-NEW** | Only runtime buckets exist; nothing persisted on `findings` |
| **DB unique `(loan,rule,subject)` + append-only event log** | ❌ | ❌ | **BUILD-NEW** | subject_key is JSON; no unique index; no event table |
| **Discovery-lane graduation + "AI found — verify" labels** | 🟡 (AI cross-source only) | 🟡 (same) | **BUILD-NEW** | Surfacing exists; graduation/labeling loop does not |
| **Golden-file eval set (LP-143)** | ❌ | ❌ | **BUILD-NEW** | Load-bearing under probabilistic AI eval |

### Recommended base

**Option (a) — branch from `phase3_5_1` and swap the evaluator layer — is the cheapest
correct path.** `phase3_5_1` already delivers every "KEEP" row above: the frozen snapshot
(deterministic job #1, done), the rules table, the four-bucket runner skeleton, the
`EvaluationResult` contract that already models verdict/confidence/evidence, canonicalization,
store-everything, and borrower↔document links. The evaluator is isolated behind a `Protocol`
+ `rule_id` registry, so replacing deterministic bodies with an AI evaluator is a
**contained** change, and the deterministic evaluators + `satisfies()` are *reused* as the
numeric-integrity checker rather than thrown away.

**What (a) still forces you to build** (unavoidable on any base — see Part C): the AI
evaluator, the prose-spec columns, the fused applicability, the persisted four-state finding
model + `(loan,rule,subject)` uniqueness + event log, the discovery-lane graduation, and the
golden eval set. Note the runner is orphaned on `phase3_5_1` — the persist + API/Celery wiring
is v2's work regardless of base.

**Risks of (a):**
- **Building on unmerged history.** `phase3_5_1` is not on `main`; if it later needs rework to
  integrate, v2 inherits that. You'd merge/rebase `phase3_5_1` forward (or onto the current
  branch) first — the current `phase3_new_AI_arch_finding` starting point is *behind* it.
- **Dead-code drift.** The deterministic applicability engine and evaluator bodies must be
  *deliberately* repurposed (pre-filter / integrity-check) or deleted; left as-is they read
  as a second, contradictory judge.
- **Schema churn.** New migrations for rule spec columns *and* the finding
  identity/state/event-log — and `phase3_5_1`'s seed is **insert-only**, so rule-row shape
  changes ship as **data migrations**, not re-seeds.

**Why not (b)** (keep only snapshot/rules-table, discard evaluators/applicability/runner):
conceptually cleaner but throws away the runner skeleton, the four-bucket result type, the
`EvaluationResult` contract, and the free numeric-integrity checker — all of which v2 keeps —
so it's *more* rebuild for less reuse.

**Why (c) is the alternative worth naming** (cherry-pick only the substrate commits — LP-117.5,
LP-118, LP-118.6/.7/.8 — onto the current branch, then build the AI engine fresh): this cleanly
separates "keep" substrate from the "replace" deterministic-engine commits
(LP-119/120/121/122R–125R), and history favors it — the snapshot/table/store-everything/linking
commits all land **before** the applicability/evaluator/runner commits, so they're separable in
order. Choose (c) only if the team wants to avoid depending on unmerged `phase3_5_1` history; the
cost is cherry-pick conflict risk and re-deriving the runner skeleton + contract you'd otherwise
inherit for free.

**Net recommendation:** merge/branch from `phase3_5_1` (option a), keep the substrate + contract
+ runner skeleton, replace the evaluator *bodies* with an AI evaluator behind the existing
Protocol, repurpose the deterministic evaluators as the integrity checker, demote (or drop) the
deterministic applicability engine, and treat the persisted four-state finding model + prose-spec
columns + golden eval set as the net-new build.

---

## Appendix — key evidence paths (all `phase3_5_1:`)

- `backend/app/verification/fact_namespace/{snapshot,builder,canonicalize,projection,transaction_kind}.py`, `canonicalization_map.json`
- `backend/app/models/verification_rule.py`; `backend/app/services/rule_registry.py`; `docs/rules/rule_seed.json`
- `backend/app/verification/evaluators/{contract,registry,large_deposit,gift_letter,bank_statement_continuity,employer_count}.py`
- `backend/app/verification/applicability/{schema,engine,authoring}.py`
- `backend/app/verification/runner.py`
- `backend/app/models/{finding,document_borrower_link,borrower}.py`; `backend/app/services/{finding_reconcile,finding_identity,document_borrower_matching}.py`
- Migrations: `d4b8f1a63c27` (LP-118 rule registry), `c8e1a4f9d2b7` (LP-118.6 fact snapshot), `e2d5b8c1f4a9` (LP-118.7 store-everything), `f3a9c2d5e8b1` (LP-118.8 doc-borrower links)
- Plans/tickets: `docs/phases/phase3_5_2.md` (LP-143 deferred); `docs/tickets/LP-118.md`, `LP-118.7.md`, `LP-118.8.md`, `LP-122R…125R.md`
- Prior audits: `docs/audits/LP-115-live-rule-inventory.md`, `docs/audits/LP-116-extractor-schema-registry.md`

*Method note: `phase3_5_1` was never checked out. Its source was read with
`git show phase3_5_1:<path>` and `git diff phase3_new_AI_arch_finding phase3_5_1 -- <path>`.
The orphaned `.pyc` under `backend/app/verification/{fact_namespace,applicability,evaluators}/`
in the working tree are untracked build artifacts from a prior checkout and are not the source
of truth for this audit.*
