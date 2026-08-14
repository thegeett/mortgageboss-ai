# Command reference

Copy-paste runbook for the commands that are easy to get wrong: local services,
AWS/Bedrock, and the extraction bench. **This file is the single source of truth for
these commands** — if a command lives here, it does not live in a second cheatsheet.

Deeper background lives in the docs that own each subject, linked from each section
rather than repeated here.

1. [Local dev](#1-local-dev) — backend, frontend, docker workers
2. [AWS](#2-aws) — SSO login, token lifetime, Bedrock check
3. [Extraction bench](#3-extraction-bench) — run a corpus through the live pipeline
4. [Worktree for a long run](#4-worktree-for-a-long-run) — isolate a run from your edits

---

## 1. Local dev

### Backend → http://localhost:8100

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8100
```

> `--reload` restarts the server on **any** `.py` save — which kills an extraction-bench
> run started from the UI. Long runs belong in the CLI ([§3](#3-extraction-bench)).

### Frontend → http://localhost:3100

```bash
cd frontend
pnpm dev --port 3100
```

### Docker workers

```bash
docker compose ps                          # running services
docker ps --format '{{.Names}}' | sort     # container names only
docker compose up -d --build worker        # rebuild + restart the worker
```

Reset the images stack — bring it down, bring the worker up **last**:

```bash
docker compose -p mbai-images -f docker-compose.images.yml down
docker compose up -d worker
```

Can the worker reach Bedrock?

```bash
docker exec mbai-bedrock-worker python -c "
import boto3
c = boto3.Session().get_credentials()
print('credentials:', 'OK' if c else 'NONE')
print('region:', boto3.Session().region_name)
"
```

Running two stacks side by side: [`../worktree-setup.md`](../worktree-setup.md).

---

## 2. AWS

### SSO login (mbai-dev)

```bash
export AWS_PROFILE=mbai-dev && aws sso login
aws sts get-caller-identity --query Account --output text   # confirm it took
```

Alternative profile: `aws sso login --profile mbai-dev-admin`

### How long is the session good for?

Run this **before** a long job — the bench preview prints its estimated minutes, and
the token has to outlive them.

```bash
grep -l startUrl ~/.aws/sso/cache/*.json | xargs grep -ho '"expiresAt": *"[^"]*"' | sort | tail -1
date -u '+%Y-%m-%dT%H:%M:%SZ'
```

First line is when the SSO token dies (UTC), second is now — subtract. The role
credentials underneath are ~1h and refresh themselves; it is **this** token that ends
a long run.

| Event | Effect on a running job |
| --- | --- |
| Browser login to the console as another account | none |
| Signing out of the SSO portal, or `aws sso logout` | breaks it |
| Token expiry | breaks it |
| `aws sso login` in another terminal | fixes it, at the next credential refresh |

If it does lapse, the bench aborts on auth failures and you resume ([§3.5](#35-resume-an-interrupted-or-aborted-run)) — no work is lost.

### Bedrock reachability

One real call, a fraction of a cent.

```bash
aws bedrock-runtime converse --region us-east-1 \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say OK"}]}]' \
  --query 'output.message.content[0].text' --output text
```

Sonnet: same command with `--model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0`.

Against **staging** (the worker's account), swap the profile in:

```bash
export AWS_PROFILE=mbai-staging-admin && aws sso login
aws sts get-caller-identity --query Account --output text   # 058190633983

AWS_PROFILE=mbai-staging-admin aws bedrock-runtime converse --region us-east-1 \
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say OK"}]}]' \
  --query 'output.message.content[0].text' --output text
```

### Bedrock model access (the 403 that looks like a code bug)

A model the account has not been granted access to fails with **403** and this message,
which names IAM but is really about the account's Marketplace subscription:

> Model access is denied due to IAM user or service role is not authorized to perform
> the required AWS Marketplace actions (`aws-marketplace:ViewSubscriptions`,
> `aws-marketplace:Subscribe`) to enable access to this model.

The app surfaces it as `ai_call_failed error_type=PermissionDeniedError transient=False`,
so the pass that needed the model fails while everything on an already-granted model keeps
working — on 2026-08-14 staging ran Haiku fine while every Sonnet call 403'd. **Check access
per model before reading it as a bug in the pipeline.**

Check (read-only, per region — the `us.` profile can route to any of the three):

```bash
export AWS_PROFILE=mbai-staging-admin
for r in us-east-1 us-east-2 us-west-2; do
  for m in anthropic.claude-sonnet-4-5-20250929-v1:0 anthropic.claude-haiku-4-5-20251001-v1:0; do
    printf '%s %s ' "$r" "$m"
    aws bedrock get-foundation-model-availability --region "$r" --model-id "$m" \
      --query 'authorizationStatus' --output text
  done
done
```

`AUTHORIZED` everywhere means access is granted and a 403 is coming from somewhere else
(the task role's `bedrock:InvokeModel*` resources, or entitlement still propagating —
grants take a couple of minutes to take effect, and the error says so).

Grant it where the status is **not** `AUTHORIZED` — take the offer token, then accept it.
The model id here is the **base** model, never the `us.` inference-profile id:

The offer token is per region too, so both calls take the same `$r` — grant and token must not
come from different regions. Edit the region list down to the ones the check above reported as
not `AUTHORIZED`:

```bash
export AWS_PROFILE=mbai-staging-admin
MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0   # or anthropic.claude-haiku-4-5-20251001-v1:0

for r in us-east-1 us-east-2 us-west-2; do
  OFFER=$(aws bedrock list-foundation-model-agreement-offers --region "$r" \
    --model-id "$MODEL" --query 'offers[0].offerToken' --output text)

  aws bedrock create-foundation-model-agreement --region "$r" \
    --model-id "$MODEL" --offer-token "$OFFER"
done
```

Then wait ~2 minutes and re-run the converse smoke test above — the console's
**Bedrock → Model access** page does the same thing.

Note this is an **account-wide** grant, not a per-role one: the ECS task role only needs
`bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` on the inference-profile ARN
plus the underlying foundation-model ARN **in every region the profile can route to**
(`infra/modules/*` task-role policy). It does not need the `aws-marketplace:*` actions the
error message names — those are for the principal performing the grant.

---

## 3. Extraction bench

Runs a folder of real documents through the **live** classification + extraction
pipeline and reports what the schemas actually capture.

> Measures **COVERAGE** (was a field populated), **not accuracy**. Persists nothing to
> the database. Output holds **real PII** — never commit, share, or move it off this
> machine.

Every command below runs from the backend dir:

```bash
cd ~/Geet/project/loan-processing/mortgageboss-ai/backend
```

Full documentation: [`../tickets/extraction-bench-cli.md`](../tickets/extraction-bench-cli.md).

### 3.1 Preview first — free, no model call

```bash
uv run python scripts/extraction-bench.py ~/path/to/corpus --preview-only
```

Prints file counts, unreadable files, pacing, estimated minutes and cost. Check that
estimate against your SSO token ([§2](#how-long-is-the-session-good-for)).

> The walk is recursive and name-blind: a folder called `_excluded_from_run` is still
> processed and still billed. Move it out first if you mean it.

### 3.2 Run it (pick one)

**(a) Attached** — short corpus, live progress bar, you watch it:

```bash
uv run python scripts/extraction-bench.py ~/path/to/corpus
```

Confirms after the preview; add `--yes` to skip that prompt. The terminal **owns** this
run — closing the window kills it.

**(b) Detached** — long corpus, survives a closed terminal. *Default for a full run:*

```bash
caffeinate -is nohup uv run python scripts/extraction-bench.py ~/path/to/corpus --yes \
  > ~/bench-run.log 2>&1 &

tail -f ~/bench-run.log
```

- `--yes` is **required** (no terminal to prompt on).
- `caffeinate` blocks idle sleep; it does **not** block lid-close sleep — leave the lid open.
- Ctrl-C out of `tail` stops the tailing only, never the run.

**(c) tmux** — detached *and* keeps the live progress bar:

```bash
tmux new -s bench
caffeinate -is uv run python scripts/extraction-bench.py ~/path/to/corpus --yes
# Ctrl-B then D to detach; tmux attach -t bench to come back
```

### 3.3 Watch a detached run

```bash
tail -f ~/bench-run.log              # live progress
tail -5 ~/bench-run.log              # just where it is at
grep "run id" ~/bench-run.log        # the run id, for resuming
pgrep -fl extraction-bench.py        # is it still alive
```

### 3.4 Stop it gracefully

Finishes the in-flight document, **then** writes the report.

```bash
# attached
Ctrl-C

# detached
pkill -f "python scripts/extraction-bench.py"
```

`pgrep` also lists the `caffeinate` wrapper, so `pkill -f` on the python command is what
hits the run itself. A second signal hard-kills — per-document JSON is written as it
goes, so at most the in-flight document is lost and the run id resumes the rest.

### 3.5 Resume an interrupted or aborted run

```bash
uv run python scripts/extraction-bench.py ~/path/to/corpus --resume <run-id> --yes
```

Same root path, plus the id. Documents already done are skipped; throttled and failed
ones are re-run.

### 3.6 Read the results

`BENCH_OUTPUT_DIR` in `backend/.env`:

```bash
open ~/Geet/project/loan-processing/mortgageboss-batch-bench-out/<run-id>/_SUMMARY.md
open ~/Geet/project/loan-processing/mortgageboss-batch-bench-out/<run-id>/_FINDINGS.csv
```

Per-document JSON: `<run-id>/<document_type>/*.json`

### 3.7 When a run aborts itself

Five consecutive failures. These are **infrastructure** failures, never coverage findings.

| `aborted_reason` | What to do |
| --- | --- |
| `rate_limited` | **Lower** `AI_REQUESTS_PER_MINUTE_BEDROCK` in `backend/.env`, then resume. To go faster instead, raise the account's Bedrock quota. |
| `ai_error` | Fix the cause — usually AWS credentials ([§2](#2-aws)) — then resume. |

### 3.8 Same bench from the UI

http://localhost:3100/dev/extraction-bench

Shares the output dir with the CLI, so either can resume the other's run id. Fine for a
short corpus; for a long one use [3.2(b)](#32-run-it-pick-one), because a refresh, a
closed tab, or any `.py` save (`--reload`) ends a UI run.

---

## 4. Worktree for a long run

**Why:** Python code is frozen at process start, so editing `.py` files mid-run is
harmless. **Prompts are not** — `load_prompt` caches on first use, so editing a prompt
for a document type the run has not reached yet mixes old and new prompts into one
report. A separate worktree makes that impossible.

Setup, ports, Docker isolation, and the full gitignored-files caveat live in
[`../worktree-setup.md`](../worktree-setup.md). What's specific to a bench run:

```bash
git worktree add --detach ~/Geet/project/loan-processing/mbai-bench phase3_bucket_2
```

`--detach`, **not** a branch name: a branch can only be checked out in one worktree, so
naming the branch you are already on fails with *"already used by worktree at …"*. Use
`-b <new-branch>` if you actually want a branch.

```bash
cp ~/Geet/project/loan-processing/mortgageboss-ai/backend/.env \
   ~/Geet/project/loan-processing/mbai-bench/backend/.env

cd ~/Geet/project/loan-processing/mbai-bench/backend
uv sync    # first run builds a .venv: minutes, ~1GB
```

Without that `.env` copy, startup dies with
`Field required: database_url / redis_url / jwt_secret_key / encryption_key`.

Then run as in [3.2(b)](#32-run-it-pick-one). `BENCH_OUTPUT_DIR` lives outside the repo,
so both checkouts share one output root and run ids resume across them.

```bash
git worktree list
git worktree remove ~/Geet/project/loan-processing/mbai-bench
```

## 5. Backend worker ECS log

```bash
AWS_PROFILE=mbai-staging-admin aws logs tail /ecs/mbai-staging/worker --follow
```
