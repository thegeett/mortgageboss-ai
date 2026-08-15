# The query stage — operating it

Two stages in `scripts/deploy` provide read-only SQL against a deployed database:
`query-setup` provisions the role once, `query` runs one `SELECT` per invocation.

This is the **operator's** side: how it is wired, how to turn it on in an environment, and
how to read a failure. What a query may and may not return — the views, the redaction, the
row and statement limits — is [`docs/querying-staging.md`](../querying-staging.md), and it
is worth reading before concluding that something is missing from the schema.

```bash
./scripts/deploy staging query -c "select count(*) from loan_files"
./scripts/deploy staging query docs/queries/why-is-in3-firing.sql
./scripts/deploy staging query -c "select ..." --max-rows 500
```

---

## How it is wired

No new infrastructure and no monthly cost. Each run is a one-off ECS task on the **existing
`migrate` task definition** — the same mechanism as `migrate`, `bootstrap-admin` and
`add-user` — with a container override that runs `app.scripts.run_query`.

The SQL arrives by **environment variable, never argv**: a task's argv is readable from
`ecs describe-tasks` for about an hour after it stops, and the whole `RunTask` call is
recorded in CloudTrail. Same reasoning as `add-user`'s password hash.

`query` takes **no confirmation prompt** — it is read-only and meant to be run repeatedly,
including by an agent. `query-setup` does prompt, because it writes.

### Authentication has no password anywhere

The task connects as `mbai_readonly` using a **15-minute RDS IAM auth token**, generated
from the task role at run time. Nothing is stored, rotated, or injected as a second secret.
Four things have to line up, and all four are already in the repository:

| Piece | Where | Note |
|---|---|---|
| Instance attribute | `infra/modules/data/main.tf` — `iam_database_authentication_enabled = true` | Instance-level, separate from the database grant |
| IAM permission | `infra/modules/compute/iam.tf` — `rds-db:connect` on `dbuser:<DbiResourceId>/mbai_readonly` | Must use the **DB resource id** (`db-XXXX…`), not the instance identifier |
| Database grant | `provision_query_role.py` — `GRANT rds_iam TO mbai_readonly` | Conditional on the `rds_iam` role existing (it does not on plain PostgreSQL) |
| SSL | `DATABASE_URL` carries `?ssl=verify-full` | IAM auth **requires** SSL; the secrets stage refuses a URL without `ssl=` |

The task role is whatever the **migrate** task definition uses — currently
`mbai-staging-api-task`. Read it, do not assume:

```bash
aws ecs describe-task-definition --task-definition mbai-staging-migrate \
  --query 'taskDefinition.taskRoleArn'
```

`AWS_REGION` must be set on the task. Fargate has no instance metadata service, so without
it botocore cannot resolve a region, the token cannot be signed, and the task dies before
opening a connection. It is set from `var.aws_region` in `infra/envs/*/main.tf`;
`run_query.py` also falls back to `AWS_DEFAULT_REGION`, `S3_REGION` and `BEDROCK_REGION`.

---

## Turning it on in a new environment

Order matters. Each step depends on the one above it, and skipping one produces an error
that looks like a different problem entirely (see the troubleshooting table).

**1. Allowlist the environment.** `QUERY_ENVIRONMENTS` in `scripts/deploy` — deliberately,
in a commit someone reviews. It is `staging` today. Both stages refuse anything not listed,
and `provision_query_role.py` refuses again on its own `PROVISION_QUERY_ROLE_ENVIRONMENT`.

**2. Apply the infrastructure.** The instance attribute and the `rds-db:connect` policy both
come from Terraform.

> `iam_database_authentication_enabled` is an **instance modification**, and
> `apply_immediately` is deliberately `false` in this module. Terraform will report success
> while RDS queues the change for the next maintenance window — up to a week away. Check it
> landed rather than assuming:
>
> ```bash
> aws rds describe-db-instances --db-instance-identifier <id> \
>   --query 'DBInstances[0].{iam:IAMDatabaseAuthenticationEnabled,pending:PendingModifiedValues}'
> ```
>
> `iam: false` with a non-empty `pending` means it is queued. To apply it now:
>
> ```bash
> aws rds modify-db-instance --db-instance-identifier <id> \
>   --enable-iam-database-authentication --apply-immediately
> ```
>
> That converges the instance to what Terraform already declares, so it creates no drift and
> needs no apply. Observed on staging: it took effect in under 15 seconds, with no reboot and
> the instance never leaving `available`.

**3. Migrate.** `./scripts/deploy <env> migrate`. The migration creates the schema, the
scrub functions and the 32 views — but deliberately **not** the login role, because
migrations run everywhere and this role must not exist in production. A view with no grantee
grants nothing, so the schema half is safe in every environment.

**4. Provision the role.** `./scripts/deploy <env> query-setup`, after step 2 has actually
landed. Read the output:

```
Provisioned mbai_readonly in staging (database mortgageboss).
  IAM authentication : enabled          <-- the line that matters
  password           : none, deliberately
  reachable schemas  : readonly only (no privileges in public)
```

`IAM authentication : not available` means `rds_iam` was not found and the grant was
**skipped silently** — the script still exits 0. That is a green-looking run that leaves the
role unusable. Fix step 2 and re-run; every statement is idempotent, so a re-run repairs
drift rather than failing.

**5. Verify.** `./scripts/deploy <env> query -c "select count(*) from loan_files"`.

To remove it again: `QUERY_SETUP_DROP=1 ./scripts/deploy <env> query-setup`. Only `1`,
`true`, `yes` and `on` mean drop.

---

## When a query fails

**Read the RDS error log, not just the client error.** The client sees one line from
asyncpg; PostgreSQL logs the `pg_hba` rule that matched and the reason the role lookup
failed, which is what distinguishes causes that otherwise look identical:

```bash
aws rds describe-db-log-files --db-instance-identifier mbai-staging \
  --query 'sort_by(DescribeDBLogFiles,&LastWritten)[-3:].[LogFileName]' --output text

aws rds download-db-log-file-portion --db-instance-identifier mbai-staging \
  --log-file-name error/postgresql.log.<date>-<hour> --output text --query LogFileData \
  | grep -iE "mbai_readonly|PAM|authentication"
```

| Client error | What it means | Where to look |
|---|---|---|
| `InvalidPasswordError: password authentication failed` | Ordinary password auth was attempted — so the token was never evaluated as a token. Either instance IAM auth is off, **or the role does not exist**. PostgreSQL returns the same message for both, to prevent user enumeration. | The log's `DETAIL:` line says `Role "…" does not exist.` when that is the cause. Otherwise check the instance attribute (step 2). |
| `InvalidAuthorizationSpecificationError: PAM authentication failed` | IAM auth **was** attempted and the credential was rejected. If the log shows `Connection matched … "hostssl all +rds_iam all pam"`, then SSL, the `rds_iam` membership and the instance flag are all correct — the problem is the credential itself. | `aws iam simulate-principal-policy` for `rds-db:connect` on the dbuser ARN; then whether what was sent is actually the token. |
| `NoRegionError` / a traceback before any SQL runs | No region on the task. | `AWS_REGION` in the task definition's environment. |
| `REFUSED: …` | A guard in the script declined and nothing ran. | The message names the guard. |
| `Refused: 'delete' is not permitted…` | The statement carried a write verb, including inside a CTE. | Rewrite as a plain `SELECT`. |

A worked example of all of this, including three defects stacked so that each masked the
next, is [`docs/findings/query-stage-auth.md`](../findings/query-stage-auth.md). The lesson
from it: **each fix produced a different error, and the change of error was the signal that
the previous layer was genuinely fixed** rather than that everything was still broken.

### The stage cannot diagnose itself

`query` connects as `mbai_readonly` for every statement, so any question about whether that
role exists or what it is granted fails with the same error being investigated.
`QUERY_DATABASE_URL` is not passed through by the stage, so it cannot be redirected either.

To ask the database something as the **master** user, run a one-off task with a container
override on the migrate task definition — the recipe, with the cluster, subnet and security
group already filled in for staging, is at the end of the findings document above.

---

## Related

- [`docs/querying-staging.md`](../querying-staging.md) — what a query returns: the views,
  the scrub, the dropped columns, the limits. Read this before adding a grant.
- [`docs/findings/query-stage-auth.md`](../findings/query-stage-auth.md) — the auth
  investigation, separated into data and inference.
- [`docs/deployment-runbook.md`](../deployment-runbook.md) — the full stage sequence.
- `decisions.md` (ADR-384) — why the redaction matches value shape rather than key names.
