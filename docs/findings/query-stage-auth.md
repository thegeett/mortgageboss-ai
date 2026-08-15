# C7 query stage: `InvalidPasswordError` for `mbai_readonly`

Investigation of the connection failure on the first real run of
`./scripts/deploy staging query`. Read-only throughout: nothing was deployed, no Terraform
was applied, no migration was run, and no database was modified.

Investigated 2026-08-15 ~03:38 UTC, against staging image `staging-2d74409`.

---

## DATA

Everything in this section is a verbatim observation. Nothing here is interpreted.

### 1. The instance

`aws rds describe-db-instances --db-instance-identifier mbai-staging`:

```json
{
  "status": "available",
  "iam": false,
  "pending": { "IAMDatabaseAuthenticationEnabled": true },
  "resid": "db-4EMG2EPQZS5XMXEJHJMX4MXHJU",
  "engine": "16.13",
  "endpoint": "mbai-staging.c45amqau4ov5.us-east-1.rds.amazonaws.com",
  "port": 5432
}
```

- `PreferredMaintenanceWindow`: `fri:09:36-fri:10:06`
- `MultiAZ`: `false`
- A separate pending maintenance action exists: `system-update`, "New Operating System
  update is available".

In the repository:

- `infra/modules/data/main.tf:138` — `iam_database_authentication_enabled = true`
- `git log -S iam_database_authentication_enabled -- infra/` returns exactly one commit:
  `48c1b79` (the C7 commit).
- `infra/modules/data/main.tf:156` — comment: "apply_immediately is deliberately NOT set:
  parameter and instance changes wait"; `infra/modules/data/main.tf:242` —
  `apply_immediately = false`.

### 2. The `rds_iam` grant

The grant is **not** in the Alembic revision. The revision
(`20260814_2300_d4e8a1c05b73_c7_readonly_query_schema.py`) deliberately creates no role at
all; its `upgrade()` only creates the schema, the scrub functions, the 32 views, and — if
the role already exists — re-grants `USAGE`/`SELECT` on the schema.

The grant lives in `backend/app/scripts/provision_query_role.py:154-160`:

```python
# RDS only. ``rds_iam`` does not exist on a plain PostgreSQL, and the same
# script has to work in both places.
granted_iam = await conn.scalar(
    text("SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam'")
)
if granted_iam:
    await conn.execute(text(f"GRANT rds_iam TO {ROLE}"))
```

It is **conditional** on the `rds_iam` role existing, and it is silent when it does not:
the script prints `IAM authentication : not available` and exits 0.

That script runs only from `./scripts/deploy <env> query-setup`.

### 3. What has actually run against staging

`aws logs filter-log-events --log-group-name /ecs/mbai-staging/api --filter-pattern
'"mbai_readonly"'` returns exactly two events:

```
2026-08-15T03:26:28Z  INFO [alembic.runtime.migration] Running upgrade
                      c9d3f1a6b2e4 -> d4e8a1c05b73, read-only query schema +
                      masked views + mbai_readonly role (C7)
2026-08-15T03:31:09Z  Query failed: InvalidPasswordError: password
                      authentication failed for user "mbai_readonly"
```

`--filter-pattern '"Provisioned"'` returns **no events**. `provision_query_role.py` prints
`Provisioned mbai_readonly in <env> (database <db>).` on every successful run.

The three most recent one-off task streams, oldest first:

| Stream | Contents |
|---|---|
| `migrate/migrate/65a49f…` | `ALEMBIC_HEAD=c9d3f1a6b2e4` / `ALEMBIC_HEAD_COUNT=1` |
| `migrate/migrate/1c307b…` | the C7 migration running |
| `migrate/migrate/8e4055…` | `--- SQL --- select count(*) from loan_files` then the failure |

### 4. The token path (`backend/app/scripts/run_query.py`)

- It calls `boto3.Session().client("rds", region_name=_aws_region())` then
  `client.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user)`.
- `host` and `port` come from `make_url(os.environ["DATABASE_URL"])` — the same URL object
  that is then connected with, via `url.set(username=user, password=token)`. The connect
  target and the signed target are the same values by construction.
- `user` is `os.getenv("QUERY_DB_USER", "mbai_readonly")`.
- SSL: `scripts/deploy:597-602` refuses to write a `DATABASE_URL` without an `ssl=`
  parameter, and refuses `sslmode=` outright; the documented spelling is
  `?ssl=verify-full`. `url.set()` preserves the query string, so the read-only connection
  inherits whatever the master URL carries.
- A token-generation failure is **not** swallowed. `_readonly_database_url()` is called at
  `run_query.py:188`, outside the `try:` at line 191, and `main()` catches only
  `KeyboardInterrupt`. A failure there exits with a traceback; it cannot produce an empty
  password.

### 5. The IAM policy

Migrate task definition `mbai-staging-migrate:9`:

- `taskRoleArn`: `arn:aws:iam::058190633983:role/mbai-staging-api-task` — **not**
  `mbai-staging-worker-task`.
- image: `…/mbai/api:staging-2d74409`

Its inline policy `mbai-staging-api-task` contains:

```json
{
  "Sid": "ReadOnlyQueryDbConnect",
  "Effect": "Allow",
  "Action": "rds-db:connect",
  "Resource": "arn:aws:rds-db:us-east-1:058190633983:dbuser:db-4EMG2EPQZS5XMXEJHJMX4MXHJU/mbai_readonly"
}
```

The resource id in that ARN is byte-for-byte the `DbiResourceId` from §1.

---

## INFERENCE

### The instance flag is queued, not missing

`iam: false` with `PendingModifiedValues.IAMDatabaseAuthenticationEnabled: true` means the
Terraform apply during the `staging-2d74409` deploy **did** set the attribute, and RDS
deferred it because `apply_immediately = false`. The attribute reached AWS; it has not
taken effect. The next maintenance window is Friday 09:36 UTC, which is 2026-08-21 — the
window for 2026-08-15 had already passed when the apply ran at ~03:26 UTC.

With instance-level IAM authentication off, RDS never consults `rds_iam` and never treats
the supplied password as a token. It performs ordinary SCRAM/MD5 authentication against
the role's stored password. The 15-minute token arrives as a long, wrong password, and
PostgreSQL answers `password authentication failed`, which asyncpg raises as
`InvalidPasswordError`. That is exactly the observed error.

### The role has almost certainly never been created

`query-setup` has left no trace: no `Provisioned` line in any log stream, and only three
one-off tasks have run — the head check, the migration, and the failing query. The
migration deliberately does not create the role. So `mbai_readonly` most likely does not
exist in the staging database.

This is an inference, not an observation: I cannot read `pg_roles` without running a task
as the master user, which is a write action in the sense that it starts a task, and you
asked for read-only. The command to settle it is in the last section.

**PostgreSQL returns the same message for a nonexistent role as for a wrong password** —
deliberately, to prevent user enumeration. So the observed error does not distinguish
"role missing" from "IAM off"; both land in the ordinary-password path and produce
`InvalidPasswordError` identically.

### What the error rules out

The premise in the report is right as far as it goes: `InvalidPasswordError` means ordinary
password authentication was attempted, so this is not a rejected token (`PAM authentication
failed`). It rules out more than that:

- **Networking, security groups and SSL are fine.** The client reached PostgreSQL and got
  an application-level auth rejection, not a timeout or a TLS error.
- **Token generation works.** Had it failed, `_readonly_database_url()` would have raised
  outside the `try` and the log would show a traceback, not `Query failed:`. So the region
  resolves — the `AWS_REGION` addition in this deploy is doing its job. Note that
  `generate_db_auth_token` is local SigV4 signing with no API call, so its success proves
  the region and credentials resolved and nothing about the database.
- **The IAM policy is not the problem.** §5 matches §1 exactly, and a wrong ARN there
  produces `PAM authentication failed`, not this.

### Root cause

**Single root cause: instance-level IAM database authentication is enabled in Terraform
but still pending at RDS, so the token is being evaluated as an ordinary password.**

That is the one defect proven by direct evidence, and it is the one that would still fail
after everything else is corrected.

Ranked, with the second item almost certainly also true:

1. **IAM auth pending on the instance** (proven). Produces exactly this error. Blocks the
   feature on its own.
2. **`mbai_readonly` probably does not exist** (strongly inferred — no provisioning run in
   the logs). Would produce exactly this error too, and would still fail after (1) is
   fixed. Not proven, because the message cannot distinguish it.
3. Nothing else found. The `rds_iam` grant is conditional but its guard is correct for
   RDS, where the role is RDS-managed and present; the IAM policy is correct; the token,
   host/port and SSL path are correct.

One caveat on ordering that the evidence does not settle: whether `rds_iam` exists on this
instance **while instance-level IAM auth is disabled**. If RDS only creates that role when
the feature is enabled, running `query-setup` before the pending change lands would create
the role, skip the grant silently, and print `IAM authentication : not available` — a
green-looking run that leaves the feature broken. Doing (1) before (2) avoids the question
entirely, which is why the fix below is ordered that way.

---

## FIX — written, not applied

### Step 1. Make the pending IAM change take effect

This is the one action that needs a decision, because it touches the live instance.

```bash
AWS_PROFILE=mbai-staging-admin aws rds modify-db-instance \
  --db-instance-identifier mbai-staging \
  --enable-iam-database-authentication \
  --apply-immediately \
  --region us-east-1
```

**This is not a Terraform change.** Terraform already declares
`iam_database_authentication_enabled = true`; the command converges the live instance to
the state Terraform has already recorded, so it creates no drift and needs no apply. The
alternative — setting `apply_immediately = true` in `infra/modules/data/main.tf` — *would*
be a code change plus an apply, and would change deferral behaviour for every future
instance modification, which is the opposite of what the comment at line 156 intends.

Doing nothing also works: the change lands by itself in the Friday 09:36–10:06 UTC window,
i.e. 2026-08-21. A week of the feature being broken is the cost of not running the command.

**Downtime:** AWS documents enabling IAM database authentication as a dynamic change
applied without an outage, and `PendingModifiedValues` carries no reboot requirement — it
lists the attribute alone. I have not run it, so that is documentation plus the absence of
a reboot flag, not an observation. The instance is `MultiAZ: false`, so if AWS were to
reboot it there would be no failover to hide it. There is also an unrelated `system-update`
maintenance action pending; `--apply-immediately` on this attribute should not trigger it,
but it is the reason to watch the instance status rather than assume.

### Step 2. Create the role

After step 1 reports `IAMDatabaseAuthenticationEnabled: true` in a fresh
`describe-db-instances`:

```bash
./scripts/deploy staging query-setup
```

Read its output. `IAM authentication : enabled` means the `rds_iam` grant landed. If it
prints `not available`, stop — that means `rds_iam` is absent and the assumption behind
the conditional grant is wrong on this instance.

### Step 3. Verify

```bash
./scripts/deploy staging query -c "select count(*) from loan_files"
```

No code change is needed for any of this. Nothing in this repository is wrong.

---

## Should IAM be abandoned for a Secrets Manager password?

**No. Keep IAM.** The ticket's "fall back if impractical" test is not met — not close.

Everything IAM needs is already built and correct: the policy ARN matches the resource id,
the token is generated with the right host, port and user, the region resolves, SSL is
enforced by the secrets stage, and the connection reaches PostgreSQL. The remaining gap is
one queued instance attribute and one provisioning command that was never run. That is a
sequencing miss in the runbook, not an impracticality in the design.

The fallback would be strictly worse on the axis C7 exists to defend. A Secrets Manager
password means a real credential for a role that can read every loan file's scrubbed data:
it has to be generated, stored, injected into the task definition, rotated, and kept out of
logs and transcripts — and the C7 design memo argues at length that the exfiltration path
here is the transcript, not the network. IAM's 15-minute token has no such artefact; there
is nothing to leak, nothing to rotate, and revocation is an IAM policy edit rather than a
password change plus a redeploy. It would also introduce a second database credential path
where there is currently one, and the `provision_query_role` script's whole shape —
`NOLOGIN`-adjacent, no password, deliberately — would have to be undone.

The only argument for the fallback is time-to-working, and step 1 collapses that to a
single API call.

---

## If you want the role question settled first (read-only)

The query stage cannot self-diagnose: it connects as `mbai_readonly` for every query, so
any question about whether that role exists fails with the same error being investigated.
`QUERY_DATABASE_URL` is not passed through by the stage, so it cannot be redirected either.

Run the query as the **migrate** task's own user (the master), with a container override:

```bash
AWS_PROFILE=mbai-staging-admin aws ecs run-task \
  --cluster mbai-staging \
  --task-definition mbai-staging-migrate:9 \
  --launch-type FARGATE \
  --region us-east-1 \
  --network-configuration 'awsvpcConfiguration={subnets=["subnet-0ea3b98b2ff1b4a92"],securityGroups=["sg-0b9f7b84add3767d9"],assignPublicIp=DISABLED}' \
  --overrides '{"containerOverrides":[{"name":"migrate","command":["uv","run","python","-c","import asyncio,os; from sqlalchemy import text; from sqlalchemy.ext.asyncio import create_async_engine\nasync def m():\n e=create_async_engine(os.environ[\"DATABASE_URL\"])\n async with e.connect() as c:\n  print(\"roles:\", (await c.execute(text(\"select rolname from pg_roles where rolname in (:a,:b)\"),{\"a\":\"mbai_readonly\",\"b\":\"rds_iam\"})).scalars().all())\n  print(\"memberships:\", (await c.execute(text(\"select g.rolname from pg_auth_members m join pg_roles r on r.oid=m.member join pg_roles g on g.oid=m.roleid where r.rolname=:r\"),{\"r\":\"mbai_readonly\"})).scalars().all())\n await e.dispose()\nasyncio.run(m())"]}]}'
```

Then read the result from the new `migrate/migrate/*` stream in `/ecs/mbai-staging/api`.

Three outcomes:

- `roles: ['rds_iam']` — the role was never created. Confirms the inference; step 2 fixes it.
- `roles: ['mbai_readonly', 'rds_iam']` with `memberships: []` — the role exists but the
  grant was skipped. Re-running `query-setup` after step 1 repairs it.
- `roles: ['mbai_readonly', 'rds_iam']` with `memberships: ['rds_iam']` — the database side
  is complete and step 1 alone is the entire fix.

This starts an ECS task, so it is not strictly read-only in the "changes nothing" sense; it
executes only `SELECT`s and does not write.
