# Bedrock rate limit: 8 → 2000 for staging (and local dev)

**Date:** 2026-08-14
**Trigger:** AWS granted 10,000 RPM in the staging account for both models.
**Outcome:** staging tfvars 8 → 2000; local `backend/.env` 8 → 2000. Nothing was
applied or deployed; the only AWS calls were the read-only describes below.

---

## 1. What is DEPLOYED right now

```
$ aws ecs describe-task-definition --task-definition mbai-staging-worker \
    --query 'taskDefinition.containerDefinitions[0].environment[?starts_with(name, `AI_REQUESTS`)]'
[ { "name": "AI_REQUESTS_PER_MINUTE_BEDROCK", "value": "8" } ]

mbai-staging-api      -> AI_REQUESTS_PER_MINUTE_BEDROCK = 8
mbai-staging-migrate  -> AI_REQUESTS_PER_MINUTE_BEDROCK = 8
```

**Present and set to `8` on all three task definitions**, not absent. `migrate` gets
it too — it shares the API's environment map and never calls Bedrock, so it is inert
there.

`AI_REQUESTS_PER_MINUTE_ANTHROPIC` appears **0 times** in any deployed task
definition.

## 2. What TERRAFORM would set

```
infra/envs/staging/terraform.tfvars:191  ai_requests_per_minute_bedrock = 8
infra/envs/staging/main.tf:442           AI_REQUESTS_PER_MINUTE_BEDROCK = tostring(var.ai_requests_per_minute_bedrock)
infra/envs/staging/variables.tf:328      variable "ai_requests_per_minute_bedrock"
infra/envs/dev/terraform.tfvars:187      ai_requests_per_minute_bedrock = 8      (never applied)
infra/envs/dev/main.tf:317 / variables.tf:291                                     (never applied)
infra/modules/compute/variables.tf:124   (the per-process warning on desired_count)
infra/modules/compute/README.md:110  ·  infra/README.md:304
backend/app/core/config.py:143-144, 274-275, 466-475
```

⚠️ **`envs/staging/terraform.tfvars` sets it EXPLICITLY** — it does not fall through
to a module default. The module declares no default for it at all, so the tfvars
value is the only source.

**It reaches both the worker and the API.** `main.tf:442` puts it in the single
`environment_variables` map, which the compute module merges into `local.api_env`
and applies to the `api`, `worker` and `migrate` containers alike. Confirmed
empirically: all three deployed task definitions carry it (§1).

## 3. What the LIVE quota actually is

```
$ aws service-quotas list-service-quotas --service-code bedrock --region us-east-1 ...

Cross-region model inference requests per minute for Anthropic Claude Haiku 4.5                 10000.0
Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1             10000.0
Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1 1M Context   1.0
Global cross-region model inference requests per minute for Anthropic Claude Haiku 4.5            10.0
Global cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1        10.0
Global cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1 1M     1.0
```

✅ **The grant landed on the right family.** The deployed model ids are

```
BEDROCK_MODEL_CLASSIFICATION = us.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_MODEL_EXTRACTION     = us.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_MODEL_REASONING      = us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

The `us.` prefix is a **cross-region inference profile**, which consumes the
**"Cross-region model inference requests per minute"** quota — the one at 10,000 for
both models in use. Not the "Global cross-region" family.

⚠️ **Two decoy quotas sit next to the ones that matter**, and both are three orders
of magnitude lower:

| decoy | value | when it would bite |
|---|---|---|
| **Global** cross-region, Haiku 4.5 / Sonnet 4.5 V1 | **10** | a model id gaining a `global.` prefix |
| Sonnet 4.5 V1 **1M Context Length** | **1** | switching to the 1M-context variant |

Neither is used today. Both are worth knowing about, because either change looks
like a routine model-id edit and would silently drop the effective ceiling from
10,000 to 10 (or 1) — and the symptom would be throttling, not a config error.

---

## What changed

### `infra/envs/staging/terraform.tfvars` — 8 → 2000

The old comment read *"the account is still at RPM 10 (a raise to 100 is pending)"*,
which is now three grants out of date. Replaced with the quota evidence, the
reasoning, and the per-process warning.

**Why 2000:**

- **~20% of the granted 10,000.** The headroom is deliberate: a **rejected** request
  still counts against the quota, so pacing at the ceiling turns one burst of
  throttling into a self-sustaining one.
- **8 was tuned for a ceiling of 10.** At 10,000 that made the limiter the
  *constraint* rather than the *backstop* — a full loan file spent minutes waiting
  for no reason.
- **Kept, not unset.** At 10,000 RPM it is mostly insurance, but a runaway loop is
  far cheaper to notice at 2000 than unbounded.

⚠️ **The limiter is PER PROCESS, not per environment.** At `desired_count = 1` this
value *is* the effective rate; at N worker tasks the effective rate is **N × 2000**.
That warning now sits directly above the variable, so scaling the worker cannot
silently multiply the request rate. (The same warning already exists in
`modules/compute/variables.tf:124`, `modules/compute/README.md:110` and
`infra/README.md:304` — all still accurate, none mention a number, so none needed
changing.)

### `backend/.env` — 8 → 2000 (local dev)

**Before:** `AI_REQUESTS_PER_MINUTE_BEDROCK=8`
**After:** `AI_REQUESTS_PER_MINUTE_BEDROCK=2000`

The dev account (591554480818) was granted the same 10,000 RPM, so local work has
the same headroom. The stale *"Account is at 10 RPM"* comment was replaced.

Verified the application actually reads it:

```
ai_provider                     : bedrock
ai_requests_per_minute_bedrock  : 2000
ai_requests_per_minute_anthropic: None
resolve_requests_per_minute()   : 2000
```

⚠️ **`backend/.env` is gitignored**, so this change is **not in the commit**. It is
per-worktree and lives only on this machine — another worktree, or a fresh clone,
still has whatever its own `.env` says.

### `AI_REQUESTS_PER_MINUTE_ANTHROPIC`

**Correctly unset everywhere.** Not in `envs/staging/` (0 hits), not in any deployed
task definition (0 occurrences), and `settings.ai_requests_per_minute_anthropic` is
`None`. Staging runs `AI_PROVIDER=bedrock`, so `resolve_requests_per_minute()`
returns the Bedrock value and never consults it. Nothing to change.

---

## ⚠️ Three independent settings, no relationship between them

| setting | source | scope |
|---|---|---|
| local dev | `backend/.env` (gitignored, per-worktree) | this machine only |
| staging | `infra/envs/staging/terraform.tfvars` | the staging account |
| production | `infra/envs/production/terraform.tfvars` | does not exist yet |

**Changing one never affects another.** They share a variable *name*, not a value.

`infra/envs/dev/` is a **never-applied reference template** and is the source of
nothing — its `ai_requests_per_minute_bedrock = 8` was deliberately left alone, and
local development does not read it.

---

## Verification

```
terraform fmt -check envs/staging/        clean
terraform validate  envs/staging          Success! The configuration is valid.
settings read back 2000 under ai_provider=bedrock
```

Only read-only AWS calls were made: three `ecs describe-task-definition` and one
`service-quotas list-service-quotas`. Nothing applied, nothing deployed.

---

## What you run next

The change is in `terraform.tfvars`; nothing takes effect until an apply.

```bash
./scripts/deploy staging deploy
```

That is the right vehicle even though no application code changed: it derives the
image tag from git, detects that the Alembic head is unchanged and skips the
migration, applies the tfvars change, and waits for all three services to finish
rolling.

⚠️ **The branch matters.** `allowed_deploy_branches` now permits
`bedrock_integration` and `bedrock_integration_with_rules_staging`; the deploy stage
refuses anything else.

If you would rather apply only the variable, `./scripts/deploy staging phase2` does
the plan/apply without touching images — the task definitions get the new value and
the services roll onto it.

Confirm afterwards:

```bash
aws ecs describe-task-definition --task-definition mbai-staging-worker \
  --query 'taskDefinition.containerDefinitions[0].environment[?starts_with(name, `AI_REQUESTS`)]'
```

Expect `2000` on the worker **and** the API.
