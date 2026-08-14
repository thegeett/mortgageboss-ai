# Merge `phase3_bucket_2_fast` → `bedrock_integration_with_rules_staging`

**Date:** 2026-08-14
**Purpose:** put the rule-engine line of work onto the deployed line, so it can ship
to staging.
**Outcome:** merged. One conflict, resolved. **Two moved verdicts, both explained
and neither fixed** — reported below as findings.

Nothing was deployed, no Terraform was applied, and no AWS resource was touched.

---

## The branch already existed

`bedrock_integration_with_rules_staging` was already present at `9ab2936` —
identical to `bedrock_integration`. It did **not** need creating, so nothing was
branched.

---

## Baseline

| | |
|---|---|
| merge base | `cfe9776` (2026-08-04) |
| `bedrock_integration` | `9ab2936` — 22 commits, 87 files from base |
| `phase3_bucket_2_fast` | `6d6e295` — 116 commits, 379 files from base |
| both worktrees | clean, 0 changes, before and after |

⚠️ **`bedrock_integration` IS pushed.** The brief says that line exists only on this
machine; that is no longer true. `origin/bedrock_integration` is at `9ab2936` —
**0 commits ahead** — so the remote has all of it. Only the *tracking* is
unconfigured, which is why `@{u}` still reports "no upstream". Worth correcting
because the deploy stage's divergence warning reads the same way.

---

## ⚠️ The rule count: 37 → 75, and what that does to the comparison

The brief's "37 live rules" is this branch's number. The incoming branch carries
**75**. The 38 extra rules *are* the rule-engine work being merged (LP-485…LP-498,
15 new activation groups).

That makes a single before/after comparison insufficient, so **two** baselines were
captured, both offline and both verified reproducible across two runs:

| baseline | where | rules | evaluations |
|---|---|---|---|
| `/tmp/pre-merge-verdicts.json` | this worktree | 37 | 431 |
| `/tmp/pre-merge-verdicts-INCOMING.json` | `mortgageboss-ai` worktree | 75 | 875 |

Method, per the brief: LF-6T3N built in memory from `build_lf6t3n_snapshot()`, tags
materialized with `only_groups=frozenset()` and no reasoners, `ANTHROPIC_API_KEY`
empty. Every capture ran under **`ai_provider=bedrock`**, which is what both
worktrees resolve to.

**Post-merge: 75 rules, 875 evaluations, 0 evaluation pairs lost, 0 added.** The
rule set is set-identical to the incoming branch.

---

## FINDING 1 — AS-12 moved, 15 rows (`needs_review` → `couldnt_check`)

Post-merge matches the **bedrock** baseline; it differs from the incoming branch.

**This pre-dates the merge.** Comparing the two branches *before* merging, on the
431 evaluation pairs they share, showed 17 disagreements — all AS-12, all this same
move. It is not a merge-resolution error.

**Cause.** `app/verification/rule_engine/judgment.py` is **byte-identical** between
the branches; `app/ai/client.py` differs by 93 insertions (the B1 provider work). So
the divergence is in how a *failed* AI call is classified, not in rule logic. The
merge takes bedrock's client — which is correct and intended, since staging runs
Bedrock — and AS-12's fail-closed verdict follows it.

⚠️ **This only describes the offline harness.** AS-12 is a judgment rule; the
harness forces its AI call to fail (no key). `couldnt_check` is arguably the more
honest verdict for "the call failed" than `needs_review`, which implies a judgment
was made. **In production, with a working Bedrock path, the call succeeds and this
comparison says nothing about the verdict.** The related drop in judgment-tag
subjects (15 → 0) has the same single cause.

**Not fixed**, per the brief.

## FINDING 2 — ID-5 moved, 2 rows (`satisfied` → `needs_review`)

Both borrower subjects. Post-merge matches the **incoming** baseline exactly.

**Cause.** ID-5 existed in both rule sets, but the incoming branch's additional
rules and tag producers change what it reads. In the 37-rule world it was
`satisfied`; in the full 75-rule world it is `needs_review` — and that is the
incoming branch's own behaviour, preserved faithfully.

So the merge did not invent a verdict; it adopted the rule-engine line's, which is
what merging that work means. **Not fixed**, per the brief.

**Everything else is identical.** Of 875 evaluation pairs: 15 AS-12 + 2 ID-5 moved,
858 unchanged, none lost, none added.

---

## The one conflict: `decisions.md`

Both lines appended ADRs and **both continued numbering from 361**:

- **C-series** (deployment/Bedrock): ADR-362…ADR-377, 16 entries
- **LP-series** (rule engine): ADR-362…ADR-383, 22 entries

⚠️ **ADR-362 through ADR-377 now name two different decisions each.**

**Resolved by keeping both blocks in full, unrenumbered**, under a header that
states the collision and tells readers to cite the series alongside the number.

**Why not renumber.** Both sets are cited from code and docs — `ADR-377` has 12
references, `ADR-362` has 7. Renumbering either side silently invalidates comments
that point at a decision by number. That is a deliberate reconciliation with
reference updates, not something to do inside a merge. **Flagged for a follow-up.**

Everything else auto-merged: 379 files, no other conflict.

---

## ⚠️ FINDING 3 — the fourth model setting is wired only by coincidence

`anthropic_model_analysis` **is present** (hazard A's "there may now be a fourth"),
and `config.py` is **byte-identical on both branches** — so hazard A produced no
conflict at all this time.

But the brief also asks that it be wired through `resolve_model()` "the same way as
the other three". **It is not, and doing that mechanically would break staging at
boot.** I did not make the change.

Today it resolves correctly:

```
analysis   claude-sonnet-4-5  -> us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

— but only because `anthropic_model_analysis == anthropic_model_reasoning` by value,
so it matches the *reasoning* pair in `resolve_model`'s three-tier loop. The config
comment even says "Same default value, distinct knob."

⚠️ **The moment that knob is re-pointed — its entire purpose — `resolve_model` raises
`ModelResolutionError` under Bedrock**, which is what staging runs.

**Why the mechanical fix is unsafe.** The boot validator refuses an *ambiguous*
mapping: tiers sharing one `ANTHROPIC_MODEL_*` value whose `BEDROCK_MODEL_*` ids
differ. Adding a fourth pair `(analysis, bedrock_model_analysis)` with
`bedrock_model_analysis` unset makes the Sonnet key map to
`{<reasoning id>, ""}` → **ambiguous → `ValueError` at startup.** Adding it to the
*required* list is worse: staging's task definition sets only three
`BEDROCK_MODEL_*` variables, so every task would fail to boot.

**Recommended (not applied):** add `bedrock_model_analysis` as optional, add the
pair to `resolve_model` only, leave both the required list and the ambiguity check
alone. Inert today, correct when the knob moves. It is a config change with a boot
risk, not a merge resolution — your call.

---

## Migrations

**One inbound revision**, and this branch had none of its own, so there is a single
head and no `alembic merge heads`:

```
c9d3f1a6b2e4  (head)   down_revision: 9f0a5f88b6f8
20260811_1500_c9d3f1a6b2e4_lp_474_consistency_finding_type.py
```

**What it does.** Adds `consistency` to the `document_findings.finding_type` value
set (LP-474). The enum is VARCHAR + CHECK (ADR-037), so it drops
`ck_document_findings_documentfindingtype` and recreates it with the value added.
**No data changes.**

**ADDITIVE — safe against the live staging database.** The new value set is a strict
superset of the old, so every existing row still satisfies the recreated constraint;
it cannot fail on data. Alembic runs it in a transaction (Postgres has transactional
DDL), so the window with no constraint is not observable.

⚠️ Two notes for the deploy. It takes an `ACCESS EXCLUSIVE` lock on
`document_findings` — instant on staging's single loan file, but not free on a real
table. And it chains from `9f0a5f88b6f8`, which is exactly where staging's database
sits, so the deploy stage will detect the difference and run it before the services
roll.

---

## Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Rules produce identical verdicts | ⚠️ **2 findings** — AS-12 ×15, ID-5 ×2. 858/875 unchanged, none lost |
| 2 | Extractors ↔ catalog Tier-1 | ✅ **bijective, 121 ↔ 121** (163 catalog types total) |
| 3 | `SNAPSHOT_VERSION == 4`, golden fixture loads | ✅ 4; golden eval tests pass in the clean run |
| 4 | Catalog ↔ classifier guard | ✅ 62 passed |
| 5 | `test_model_selection_lp457.py` passes, unmodified | ✅ 3 passed; byte-identical to **both** branches |
| 6 | Full suite, ruff, mypy | ⚠️ **7 failed, 4847 passed** — all pre-existing (below). ruff ✅, format ✅ (927 files), mypy ✅ (415 files) |
| 7 | `terraform fmt -check` + validate ×3 | ✅ clean; bootstrap / envs/staging / envs/dev all valid |
| 8 | Model tier resolution | ✅ below |
| 9 | Bedrock-line files present and unmodified | ✅ all, one correction below |

### 8 — model resolution after the merge (`ai_provider = bedrock`)

```
classification  claude-haiku-4-5   -> us.anthropic.claude-haiku-4-5-20251001-v1:0
extraction      claude-haiku-4-5   -> us.anthropic.claude-haiku-4-5-20251001-v1:0
reasoning       claude-sonnet-4-5  -> us.anthropic.claude-sonnet-4-5-20250929-v1:0
analysis        claude-sonnet-4-5  -> us.anthropic.claude-sonnet-4-5-20250929-v1:0   (via reasoning — see Finding 3)
```

All three calibrated tiers intact; reasoning is still **Sonnet**, so the 75 rules'
bars are unchanged.

### 9 — bedrock-line files, `git diff` vs `bedrock_integration`

`app/storage/s3.py`, `alembic/env.py`, `backend/Dockerfile`, `frontend/Dockerfile`,
`backend/.dockerignore`, `frontend/.dockerignore`, `scripts/deploy`,
`scripts/deploy-lib.sh`, `scripts/hash-password`, `app/scripts/bootstrap_admin.py`,
`app/scripts/add_user.py` — **all unchanged**. `infra/` is byte-identical apart from
the one permitted allowlist line.

`alembic/env.py` confirmed still using `create_async_engine` with no
`set_main_option` — the `ValueError` fix is intact.

⚠️ **`scripts/sso-status` does not exist and never did** — 0 hits on *either*
branch. The brief lists it as something this line carries; it does not. Nothing was
lost in the merge.

### 6 — the 7 failures

All in `tests/ai/generator/test_generator.py`. **Pre-existing on the incoming
branch**: the same 7 fail there (`7 failed, 16 passed`) with no merge involved.

⚠️ **The ~21 failures the brief predicted did not occur, and cannot.** That
divergence was `backend/.env` setting `AI_PROVIDER=bedrock` while tests asserted the
anthropic default. This worktree's `.env` no longer sets `AI_PROVIDER` at all. Both
provider settings now produce the **identical** 7 failures, so that defect is gone
and the tests never reach the API.

**Per your instruction, `bedrock` is the only provider used** — every capture, the
suite, and the model resolution above all ran under it. (The one `AI_PROVIDER=anthropic`
run consumed no credits: identical results, no API call.)

---

## Changed in this merge

| | |
|---|---|
| `decisions.md` | conflict resolved — both ADR series kept, collision documented |
| `infra/envs/staging/terraform.tfvars` | `allowed_deploy_branches` gains `bedrock_integration_with_rules_staging` |
| everything else | auto-merged, 379 files |

`image_tag` was **not** touched — it is script-owned. `variables.tf` was not touched:
`allowed_deploy_branches` was already declared.

---

## Decisions

1. **Two baselines, not one**, because the rule count changes 37 → 75. One baseline
   could not distinguish "the merge broke a rule" from "the merge added rules".
2. **Both baselines verified reproducible** before use — a non-deterministic baseline
   would make every comparison meaningless.
3. **Both moved verdicts reported, neither fixed**, per the brief.
4. **`decisions.md`: keep both, renumber nothing** — the numbers are load-bearing in
   code comments.
5. **`resolve_model` left alone** — the requested wiring would break boot. Reported
   with a safe alternative instead.
6. **Nothing in `infra/` beyond the allowlist line.**
7. **No Alembic revision created.**
8. **The other worktree was never switched, staged, or written to** — verified clean
   and still on `phase3_bucket_2_fast` afterwards. Its read-only baseline run wrote
   only to `/tmp`.

## Follow-ups (none blocking)

- Reconcile the ADR-362…377 collision, updating references.
- Decide on `bedrock_model_analysis` (Finding 3).
- The 7 generator failures — pre-existing on the rule-engine line, own ticket.
- Configure upstream tracking for `bedrock_integration` so `@{u}` stops reporting
  "no upstream" for a branch that is fully pushed.
