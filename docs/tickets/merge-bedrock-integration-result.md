# Merge `bedrock_integration` → `phase3_bucket_2` — result

## What this was

A **catch-up merge**: `bedrock_integration` already contained every `phase3_bucket_2` commit (phase3 was merged
into it on 2026-08-04). Nothing from `phase3_bucket_2` goes the other way. It brings in A1 (worktree isolation),
C0 (S3 backend), C1 (Dockerfiles), and **B1 (the Bedrock provider for the AI client)** — the one that touches
rule-engine/model territory.

## It was a clean FAST-FORWARD

- `phase3_bucket_2` HEAD `32caaac` == `merge-base(phase3, bedrock)` → phase3 is an **ancestor** of bedrock, so
  `git merge --ff-only` moved the pointer to bedrock HEAD `cfe9776` with **no merge commit and no conflicts**.
- **Consequence for the "fourth-tier HARD STOP":** the fourth tier (`anthropic_model_analysis`, my `32caaac`) was
  already IN bedrock — B1's `resolve_model()` was authored with it present. So there was **nothing to
  reconcile** (no parallel-design conflict to resolve); I verified the interaction instead of merging two designs
  (see "The fourth tier vs `resolve_model()`").
- Working tree was clean before merging (the LP-457-review fourth-tier work was already committed as `32caaac`).

## Acceptance criteria — met / not-met with evidence

| # | criterion | result |
|---|---|---|
| pre‑2 | HEADs + merge base recorded | phase3 `32caaac`, bedrock `cfe9776`, base `32caaac` (= phase3 HEAD) |
| pre‑3 | ACTIVE == 37, baseline verdicts captured | ✅ 37; `/tmp/pre-merge-verdicts.json` (431 results) |
| pre‑4 | no alembic revision beyond `9f0a5f88b6f8` | ✅ head is `9f0a5f88b6f8`, nothing has it as `down_revision`; both branches 43 files |
| **1** | **ACTIVE == 37 and all 37 verdicts IDENTICAL vs baseline** | ✅ **37; 431 results; MOVED verdicts: NONE** |
| 2 | 109 extractors registered | ✅ `len(EXTRACTORS) == 109` |
| 3 | SNAPSHOT_VERSION == 4, golden fixture loads | ✅ SNAPSHOT_VERSION 4 (full suite loads the golden fixture) |
| 4 | catalog↔classifier CI guard passes | ✅ (full suite green — the guard is in it) |
| 5 | full suite green; ruff + mypy clean | ✅ (below) |
| 6 | `test_model_selection_lp457.py` passes and is UNMODIFIED | ✅ zero diff `32caaac..HEAD`; passes |
| 7 | `docker compose config` → `mortgageboss-*` on 5432/6379/1025/8025 | ✅ postgres 5432, redis 6379, mailhog 1025/8025, all `mortgageboss-*` |
| 8 | which model each tier resolves to | classification→haiku · extraction→haiku · reasoning→**sonnet** · analysis→sonnet |
| 9 | `resolve_model()` returns ANTHROPIC ids (not Bedrock) for all tiers | ✅ `ai_provider="anthropic"` → identity; all four return `claude-*` |
| 10 | guard: no caller passes a model to the SDK directly | ✅ added `tests/ai/test_model_resolution_boundary.py` |

## Verdict equivalence (the critical check)

Captured **before** the merge on `32caaac` and **after** on `cfe9776`, both offline and deterministic (LF-6T3N
in memory, `materialize_tags(only_groups=frozenset())`). Result: **ACTIVE 37 == 37, 431 results == 431, and NOT
ONE of the 37 rules moved a verdict.** Distribution identical: `couldnt_check 167 · not_applicable 233 ·
needs_review 6 · satisfied 23 · fired 2`. B1 changes the AI CLIENT and pricing, not deterministic rule
evaluation — confirmed, not assumed.

## The fourth tier vs `resolve_model()` (the addendum questions)

- **What the fourth tier is for:** decoupling the Tier-3 generic analyzer (`ai/generic_analyzer.py`, "understand
  anything" for unrecognised documents — a PERCEPTION task) from the CALIBRATED reasoning tier, so a future
  reasoning re-point for calibration never drags the analyzer along. `config.py` documents exactly this.
- **Does `resolve_model()` handle it?** **Under `ai_provider="anthropic"` (this worktree): YES** — `resolve_model`
  is the identity function, so `anthropic_model_analysis` (Sonnet) passes through unchanged. No fall-through.
- **Under `ai_provider="bedrock"`:** `resolve_model` maps only the THREE tiers (classification/extraction/
  reasoning). The analysis value is `claude-sonnet-4-5`, IDENTICAL to reasoning's — so today it would
  **coincidentally** resolve via the reasoning pair to `bedrock_model_reasoning`. That is fine while
  analysis == reasoning, but it is a **value-coincidence, not a design** — if analysis ever diverged from
  reasoning under Bedrock, `resolve_model` would raise `ModelResolutionError` (no matching tier).
- **Does `bedrock_model_*` need a fourth entry?** **Not for this worktree** (anthropic, identity). **A NEW GAP for
  the Bedrock worktree** (flagged, NOT reconciled here — B1/Bedrock is the other branch's work, which I must not
  modify): if it ever wants the analyzer on a distinct Bedrock model, it needs a `bedrock_model_analysis` (or a
  tier-aware `resolve_model`). Today it rides on the reasoning mapping by coincidence.

## What changed in this worktree (beyond the fast-forward)

- **Added** `tests/ai/test_model_resolution_boundary.py` (criterion 10): the SDK (`.messages.create/.stream` and
  the `AsyncAnthropic[Bedrock]` constructors) is invoked at EXACTLY one boundary — `ai/client.py`, which calls
  `resolve_model()` (line 334) before `messages.create` (line 366) — verified no other `app/` module touches the
  SDK. Also asserts the four tiers resolve to Anthropic ids under the anthropic default (criterion 9 as a test).
- **Updated `backend/.env`** (gitignored, per-worktree — the merge cannot touch it): it was already correct
  (`EXTRACTION=haiku`, `REASONING=sonnet` — I fixed those in LP-457 in THIS worktree, so unlike the other
  worktree it was not stale); added `ANTHROPIC_MODEL_ANALYSIS=claude-sonnet-4-5` for four-tier consistency and a
  note that `AI_PROVIDER` stays unset (this worktree is direct-Anthropic; Bedrock is the other worktree). API key
  present, satisfying B1's new validator.

## Notable B1 behaviours observed (not changed)

- **New startup validator:** `ANTHROPIC_API_KEY` is now REQUIRED when `ai_provider="anthropic"` — an empty key is
  rejected at settings construction (my baseline's empty-key trick had to become a dummy key; determinism came
  from `only_groups=frozenset()`, not the key).
- **`resolve_model()` is the sole model→provider mapping** and is keyed on the tier VALUE (not a `purpose` arg) so
  a provider swap doesn't touch 13 call sites. Under anthropic it is the identity — the default path is
  byte-identical.
- **cost.py Opus correction** (`claude-opus-4-8` $15/$75 → **$5/$25**): every Opus `cost_estimate` recorded before
  2026-08-04 was overstated 3×. **Impact here: ZERO** — **0 of 94 stored extractions used Opus** (`model_used ~
  opus` = 0), so no stored estimate in this DB was affected. The correction matters only for future Opus opt-ins.

## Assumptions / decisions

- The verdict baseline uses `only_groups=frozenset()` (no AI groups), per the brief — the most deterministic
  method; the AI-tag rules degrade to `couldnt_check` identically before and after, so the comparison is exact.
- The fourth-tier / Bedrock gap is **flagged, not fixed** — reconciling it would mean editing B1's resolver
  (the other branch's work) on a value-coincidence that is correct today. Left for the Bedrock worktree.
- `backend/.env` edited locally only (gitignored); not committed. `AI_PROVIDER` deliberately left unset.
- Did NOT run `docker compose up/down` (only `config`), did NOT run `docker-compose.images.yml`, did NOT touch
  `app/storage/`, `infra/`, `scripts/verify-*.py`, or any Dockerfile.

## NEW gaps / what remains

- **Bedrock + the analysis tier:** no `bedrock_model_analysis`; the analyzer resolves under Bedrock only by the
  coincidence `analysis == reasoning == claude-sonnet-4-5`. If the Bedrock worktree diverges them,
  `resolve_model` will raise — a `bedrock_model_analysis` entry (or a tier-aware resolver) is needed there.
- The Bedrock path itself is untested in this worktree (correctly — it stays on the direct Anthropic API).

## Full suite / lint

Full suite green; ruff clean; `mypy app/` clean (394 source files — B1 added the client/config surface). The two
model guards (`test_model_selection_lp457.py` unmodified, `test_model_resolution_boundary.py` new) both pass.
