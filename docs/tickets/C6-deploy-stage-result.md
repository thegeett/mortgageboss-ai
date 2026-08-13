# C6 — a `deploy` stage for shipping application code

**Date:** 2026-08-13
**Outcome:** `./scripts/deploy <env> deploy`. **Not run.** Built and verified only;
nothing was pushed, applied, registered, or migrated.

---

## The command

```bash
./scripts/deploy staging deploy
```

That is the whole thing. It prompts twice — once before migrating (only when there
*are* migrations) and once for the Terraform apply — and otherwise runs unattended.

```
./scripts/deploy staging deploy --allow-branch    # ship from a branch not in the allowlist
./scripts/deploy staging deploy --yes             # answer both confirmations
```

What it does, in order:

| | step | notes |
|---|---|---|
| 1 | refuse a dirty tree | untracked files count — see below |
| 2 | refuse a branch `allowed_deploy_branches` does not list | `--allow-branch` overrides |
| 3 | report divergence from the remote | warn-only |
| 4 | derive `<env>-<short sha>` | e.g. `staging-1923a4f` |
| 5 | ECR login; skip the build if the tag exists | tags are immutable |
| 6 | build + push both images, arm64, with OCI labels | frontend gets `NEXT_PUBLIC_API_URL` |
| 7 | compare local vs deployed Alembic head | one read-only task |
| 8 | migrate **on the new image**, only if they differ | confirmed first |
| 9 | write `image_tag`, show the diff, apply | via `phase1` or `phase2` |
| 10 | wait for all three services to finish rolling | reports each revision |

---

## The three gaps, and how each is closed

### 1. The tag is a function of the commit

`staging-$(git rev-parse --short HEAD)`, and **the working tree must be clean.**

⚠️ **Untracked files count as dirty, and that is not pedantry.** `docker build`
sends the **working tree** as its build context, not the commit. An untracked file
that `.dockerignore` does not exclude is *in the image*. Allowing it would let the
tag name a commit that does not describe the built bytes — which is the exact class
of error that produced both `CannotPullContainerError` failures, arriving by a
different door.

The refusal lists the offending paths and says what to do.

Because the tag is derived rather than typed, the two historical failure modes stop
being reachable: you cannot bump the tag without building (the tag comes from the
commit you are building) and you cannot build without bumping (a new commit is a new
tag). `image_tag` in tfvars is now written by this stage, and the variable's comment
says so.

### 2. The branch check

This machine has **four worktrees on three branches**:

```
/Users/geetthaker/…/mortgageboss-ai   [phase3_bucket_2_fast]
/Users/geetthaker/…/mbai-bedrock      [bedrock_integration]
/Users/geetthaker/…/mbai-bench        [bench-run]
```

`docker build` ships whatever is checked out where it runs, and a SHA names the
commit but not the line of work. A deploy from the wrong worktree produces a
*correctly tagged* image of the wrong code, and nothing downstream notices.

Three mitigations, deliberately layered:

**An allowlist in the environment's tfvars**, defaulting to `["bedrock_integration"]`:

```hcl
allowed_deploy_branches = ["bedrock_integration"]
```

Declared in `envs/staging/variables.tf` with a `default`, even though **no module
reads it**. Undeclared values in `terraform.tfvars` are only a warning, not an error
— verified — but it is a warning printed on every single plan and apply, and a tool
that makes Terraform noisier would get switched off. Declaring it costs nothing and
keeps the per-environment deploy policy next to the rest of that environment's
configuration. An empty list permits nothing (fails closed).

**OCI labels on both images**, so a deployed image is traceable without consulting
tfvars, git, or this script:

```
org.opencontainers.image.revision = <full sha>
org.opencontainers.image.source   = <branch>
org.opencontainers.image.version  = <tag>
```

**A remote-divergence report.** Ahead → *"shipping work that is not pushed"*; behind
→ *"N commits behind (as of the last fetch)"*.

⚠️ It does **not** fetch. A deploy command should not quietly mutate refs, and the
case that matters most — being ahead — needs no fetch to detect. The output says the
comparison is against the last fetch and suggests `git fetch` for a current one.

⚠️ `bedrock_integration` currently has **no upstream at all**, which the stage reports
loudly: *"this code exists only on this machine, so the deployed image will be the
only copy of it outside this worktree."*

### 3. Migrations — the ordering gap

**Detection.** Local head from `alembic heads`, which reads the versions directory
and does **not** execute `env.py`, so it needs no database and no app settings
(verified: it prints `9f0a5f88b6f8` with every app env var unset). Deployed head from
`select version_num from alembic_version`, read by a one-off task on the *current*
task definition — reading a table needs no new image.

- Heads match → **skip**, and say so: *"the deployed database is already at the head
  this commit expects."*
- Heads differ → **migrate before the services roll**, and say so.
- Deployed head empty (fresh database) → treated as differing.

⚠️ **The migration runs on the NEW image, via one extra task-definition revision.**
This is the design decision in this ticket that most deserves scrutiny.

The migration must run the new code — the new image is what carries the new
revisions. But the deployed migrate task definition still points at the **old** tag
until Terraform applies, and *that same apply also updates the services*. Waiting for
it would put the services on new code before the migration ran, which is precisely
the failure this stage exists to prevent. ECS `containerOverrides` can override the
command and the environment but **not the image**, so the existing definition cannot
be redirected.

So the stage registers one extra revision of the same family with the image swapped,
runs that, and lets Terraform carry on managing its own revisions. Terraform tracks
the revision *it* created, so an extra one is inert — it costs a revision number, not
correctness.

The alternative considered was `terraform apply -target` on the task definition:
keeps everything in Terraform, but couples the script to a module-internal resource
address (`module.compute.aws_ecs_task_definition.migrate`) and doubles the applies
and confirmations. Registering a revision is the standard ECS pre-deploy-migration
pattern and does not reach into the module's internals.

---

## Ordering, stated plainly

```
push images  →  migrate (if needed)  →  terraform apply  →  services roll  →  wait
```

The apply is what updates the services, so everything that must precede a service
update precedes the apply.

---

## `status` — "is staging running my latest commit?"

```
  deployed tag           staging-1923a4f
  desired tag (tfvars)   staging-1923a4f
  worktree               /Users/geetthaker/…/mbai-bedrock
  worktree branch/sha    bedrock_integration@1923a4f
  deployed branch label  bedrock_integration
  in sync?               YES -- staging is running this worktree's HEAD
```

⚠️ **The deployed tag is read from what the API service is RUNNING**, not from
tfvars. tfvars is the *desired* state and is ahead of reality whenever an apply
failed or is in flight; reporting it as "deployed" would be exactly wrong at the
moment the question matters most. Both are shown, side by side, so a disagreement is
visible rather than hidden.

The branch label is read from the image config, so it is true even if tfvars or the
working tree have moved since. It degrades to `unknown (pre-label image, or no
registry access)` for images built before this change, and when docker/buildx is
unavailable.

`in sync?` distinguishes three cases: matching HEAD, matching HEAD with uncommitted
changes, and a genuine mismatch (which prints both tags).

---

## Failure and rollback

The rollback hint fires from the **exit trap**, not from each failure site, so it
also appears on Ctrl-C and on a `die()` deep inside the apply. It prints only when
the tag was written and the deploy did not complete:

```
TO RETURN TO THE PREVIOUS IMAGE

  The previous tag was: staging-3
  staging-1923a4f was written into infra/envs/staging/terraform.tfvars.

    sed -i.bak 's/^image_tag *=.*/image_tag = "staging-3"/' infra/envs/staging/terraform.tfvars
    rm -f infra/envs/staging/terraform.tfvars.bak
    ./scripts/deploy staging phase2

  ⚠️ That reverts the IMAGE. It does not revert a migration that already
     ran: Alembic downgrades are not part of this stage, and the old code
     may not tolerate the new schema.
```

That last warning is the honest part. Rolling the image back after a migration has
run leaves old code against a new schema, which may or may not work — the stage
cannot know, so it says so rather than implying the rollback is complete.

---

## Verification

Nothing was run against the environment beyond **read-only** AWS calls
(`describe-task-definition`, `describe-services`, `sts get-caller-identity`).

```
bash -n scripts/deploy, scripts/deploy-lib.sh   OK
./scripts/deploy --help                          lists `deploy` and --allow-branch
terraform fmt -recursive -check                  clean
validate: bootstrap / envs/staging / envs/dev    Success (all three)
```

**Harness 1 — git, tfvars and Alembic helpers (14 assertions, all pass):**

```
  ok  tfvar_list reads the branch list / multi-entry / empty list
  ok  deploy_apply_stage_name -> phase2 when both flags true
  ok  deploy_apply_stage_name -> phase1 when both false / when mixed
  ok  allows bedrock_integration
  ok  REFUSES phase3_bucket_2_fast        <- a real other worktree on this machine
  ok  REFUSES bench-run                   <- likewise
  ok  --allow-branch overrides
  ok  empty allowlist fails closed
  ok  local_alembic_heads -> 9f0a5f88b6f8
  ok  refuses a dirty tree                <- this tree was dirty at the time
  ok  warns when the branch has no upstream
```

**Harness 2 — rollout and rollback (10 assertions, all pass):**

```
  ok  all steady -> returns 0
  ok  two deployments -> keeps waiting     <- mid-roll is not "done"
  ok  running<desired -> not steady
  ok  rolloutState FAILED -> not steady    <- circuit breaker rolling back
  ok  rollback hint names the previous tag, gives a runnable sed,
      warns migrations are not reverted, and is silent on success
```

**Harness 3 — the request builders.** Both run-task payloads are valid JSON with the
embedded Python program intact; the head comparison yields skip / migrate / migrate
for same / different / empty.

**The task-definition transform, verified without registering anything.** Against the
real `mbai-staging-migrate` definition:

```
fields describe returns:  compatibilities containerDefinitions cpu executionRoleArn
                          family memory networkMode placementConstraints registeredAt
                          registeredBy requiresAttributes requiresCompatibilities
                          revision runtimePlatform status taskDefinitionArn
                          taskRoleArn volumes
fields after my transform: containerDefinitions cpu executionRoleArn family memory
                          networkMode placementConstraints requiresCompatibilities
                          runtimePlatform taskRoleArn volumes

every remaining key accepted by register-task-definition:  yes (compared against
                                                           --generate-cli-skeleton)
image swapped:  …/mbai/api:staging-1923a4f
content preserved:  secrets DATABASE_URL, ENCRYPTION_KEY, JWT_SECRET_KEY, REDIS_URL
                    logGroup /ecs/mbai-staging/api · 14 env vars · command intact
```

**The steady-state query, against the live API service:** `1  COMPLETED  1  1`,
parsed as `count=1 state=COMPLETED running=1 desired=1` → steady. Correct.

**The tfvars rewrite, on a copy:** `image_tag = "staging-3"` → `"staging-1923a4f"`,
with a diff confirming **every other line is byte-identical**, and the value reads
back through the parser.

### ⚠️ What is NOT verified

`register-task-definition` and `run-task` were never **called** — that would have
created a task-definition revision and run a container, which this ticket forbids. So
the payloads are proven well-formed and complete, but the round trip is unproven. The
first real deploy that introduces a migration exercises it.

Everything else — the git logic, the head comparison, the rollout wait, the rollback
hint, the tfvars rewrite, the request construction — is exercised directly.

---

## Decisions

1. **The tag is derived, not an argument.** No `--tag`. An override would restore the
   failure mode the derivation removes.
2. **Untracked files block the deploy**, because the build context is the working
   tree. Stricter than `git diff --quiet`, and deliberately so.
3. **The allowlist lives in tfvars**, declared in `variables.tf` so Terraform stays
   quiet. Per-environment policy belongs with the environment.
4. **No automatic `git fetch`.** A deploy should not mutate refs. The report says
   what it is comparing against.
5. **Migrations run on a registered revision**, not `-target`. Standard ECS pattern;
   no coupling to a module-internal address; one apply instead of two.
6. **Detection costs one extra task only when migrations are needed.** The read is
   always one task; the migration is zero or one. Always-migrate would also be one —
   but would not let the stage *say* which happened, which is the requirement.
7. **The apply reuses `phase1` / `phase2`** rather than a private apply path, chosen
   by the current flags, so `deploy` works before and after TLS and inherits both
   stages' existing guards (phase1 refuses if an ACM certificate appears; phase2
   refuses without DNS delegation).
8. **`status` reads the running task definition**, not tfvars, for "deployed".
9. **The rollback hint lives in the exit trap** so Ctrl-C is covered.
10. **`build_and_push` gained one hook** (`IMAGE_EXISTS_ADVICE`) so the "tag already
    exists" advice can differ between `images` ("bump image_tag") and `deploy`
    ("make a commit"). The rest of that function is unchanged and still used by
    `images`.

---

## Files changed

| | |
|---|---|
| `scripts/deploy` | the `deploy` stage, its helpers, the `status` block, `--allow-branch` |
| `infra/envs/staging/variables.tf` | `allowed_deploy_branches`; note on `image_tag` ownership |
| `infra/envs/staging/terraform.tfvars` | the branch allowlist; note that `image_tag` is now script-owned |

`envs/dev` is untouched: it is a never-applied reference template with no ECR
repositories or services to deploy to.
