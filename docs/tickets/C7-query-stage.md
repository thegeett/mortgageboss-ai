# C7 — Read-only query access to staging

**Branch:** `bedrock_integration_with_rules_staging`
**Depends on:** C5 (deployed staging), C6 (deploy stage)
**Cost:** effectively zero — no standing infrastructure, a fraction of a cent per query

---

## What this does and why

There is no way to inspect the staging database today. Diagnosing anything requires
reasoning from CloudWatch logs alone, which has already cost real time in this
project.

The obvious answers were all rejected:

- **Public RDS + IP allowlist** — RDS is `publicly_accessible = false` in a private
  subnet with no default route, so a security-group rule changes nothing. Making it
  work means deleting the property the whole network design rests on.
- **SSM bastion + port forwarding** — correct, and the right answer if a GUI client
  matters. But ~$15/month of SSM endpoints, a new EC2 instance, an RDS security
  group change, and an unpatchable host (no NAT means no package repos).
- **RDS Data API** — Aurora only. This is RDS PostgreSQL.

This ticket uses the mechanism **already proven three times** in this environment:
a one-off ECS task on the migrate task definition, which has `DATABASE_URL`
injected and lands in the subnet with the interface endpoints. Migrations,
`bootstrap_admin` and `add_user` all run this way.

**The agent is the primary consumer.** A task-based path is better than an
interactive session for that: each query is a reviewable artifact rather than an
ad-hoc session, output lands in CloudWatch with retention, and nothing holds an
open connection.

## Acceptance criteria

1. `./scripts/deploy staging query <file.sql>` runs the file and prints results.
2. The connection is **read-only at the database level**, not by convention.
3. **Raw SSNs and TINs are unreachable** through this path.
4. Writes fail. So do DDL, and anything reaching a base table directly.
5. Every query is logged with the SQL that ran.
6. No new standing infrastructure and no monthly cost.

---

## ⚠️ The requirement that shapes the design

`borrowers.ssn` is Fernet-encrypted at rest, so a `SELECT` returns ciphertext —
genuinely protected.

**`extractions.extracted_data` is not.** It holds raw SSNs and TINs in plaintext
JSON — `employee_ssn` from W-2s, `recipient_tin` from 1099s. The §3B masking applies
at snapshot build, not at rest. A read-only role with `SELECT` on `public` reads
every one of them.

And the exfiltration path is not the network. If the agent runs a query returning
raw SSNs, those values are in the terminal scrollback, in the conversation, and
quite possibly in a result document committed to git. **No network control touches
that.** The masked view layer is the control that does.

So: the query role gets **no access to base tables at all.**

---

## Tasks

### 1. Migration — role and masked views

A **new Alembic revision**, chained from the current head.

⚠️ This branch has deliberately avoided migrations to keep merges trivial. That
constraint no longer holds — `c9d3f1a6b2e4` merged in from the rules line. Confirm
there is a single head before writing, and stop if there are two.

**Schema `readonly`**, containing a view per table the agent needs. For every table:

- Include the columns needed for debugging
- **Exclude or redact `extractions.extracted_data`.** Prefer a redacted projection —
  strip the known PII keys and keep the rest — over dropping the column, since its
  structure is often what you are debugging. Report which you chose and why.
- Exclude `borrowers.ssn` (it is ciphertext and useless anyway) and any other
  encrypted column
- Read the models to find every column that could carry an identifier. Report the
  full list you excluded, so the decision is reviewable rather than implicit.

**Role `mbai_readonly`:**

```sql
CREATE ROLE mbai_readonly LOGIN;
GRANT CONNECT ON DATABASE mortgageboss TO mbai_readonly;
GRANT USAGE ON SCHEMA readonly TO mbai_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA readonly TO mbai_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA readonly GRANT SELECT ON TABLES TO mbai_readonly;

REVOKE ALL ON SCHEMA public FROM mbai_readonly;
ALTER ROLE mbai_readonly SET search_path = readonly;
ALTER ROLE mbai_readonly SET default_transaction_read_only = on;
ALTER ROLE mbai_readonly SET statement_timeout = '30s';
ALTER ROLE mbai_readonly CONNECTION LIMIT 2;
```

⚠️ **`REVOKE ALL ON SCHEMA public` is the load-bearing line.** Without it the role
reaches base tables directly and the views are decoration. Test it explicitly.

`default_transaction_read_only` and `statement_timeout` are belt-and-braces: the
first makes a write fail even if a grant is wrong, the second bounds a runaway
agent query against a table that will grow.

**Use IAM database authentication** — `GRANT rds_iam TO mbai_readonly` — so there is
no password to store, rotate, or leak. The task role generates a 15-minute token.
If that proves impractical, say why and fall back to a Secrets Manager password,
but try IAM first.

**The `downgrade()` must drop the schema and role cleanly.**

### 2. `app/scripts/run_query.py`

Reads SQL from an environment variable, connects as `mbai_readonly`, executes,
prints results as a formatted table.

- **Reject anything that is not a single `SELECT` or `WITH`** before connecting.
  This is defence in depth, not the primary control — the database enforces it. But
  a clear "only SELECT is permitted" beats a Postgres permission error.
- Reject multiple statements — no semicolon-separated batches.
- Cap output rows (default 100, overridable) so a mistaken query does not write
  thousands of lines to CloudWatch.
- Print the SQL that ran, then the results, then the row count.
- Non-zero exit on any error, with the Postgres message intact.

### 3. `query` stage in `scripts/deploy`

```bash
./scripts/deploy staging query path/to/file.sql
./scripts/deploy staging query -c "select count(*) from loan_files"
```

- Reads network configuration from the **running API service**, as `migrate` does —
  tasks are pinned to the AZ that has interface endpoints and the subnet list
  includes one that does not.
- Runs on the existing migrate task definition with `containerOverrides`.
- Passes SQL via environment, not argv. ⚠️ **argv is visible in `describe-tasks`
  for about an hour and recorded in the CloudTrail `RunTask` event.**
- Polls to completion, prints the CloudWatch logs, exits non-zero on failure.
- No confirmation prompt. This is read-only and meant to be called repeatedly,
  including by an agent.

### 4. IAM

The migrate task role needs `rds-db:connect` on the `mbai_readonly` DB user
resource ARN:

```
arn:aws:rds-db:us-east-1:058190633983:dbuser:<db-resource-id>/mbai_readonly
```

⚠️ **That is the DB *resource id* (`db-XXXX…`), not the instance identifier.** Get
it from `describe-db-instances --query 'DBInstances[0].DbiResourceId'` and take it
as a Terraform variable or data source. Getting this wrong produces a
`PAM authentication failed` that says nothing about IAM.

### 5. Documentation

`docs/querying-staging.md` — how to run one, what the agent may and may not see, the
excluded columns, and **a plain statement that this path cannot return raw SSNs or
TINs**, so nobody adds a base-table grant later to make something convenient.

Add a section to `CLAUDE.md` telling the agent this stage exists and to use it for
database questions rather than reasoning from logs.

---

## Verify

```bash
cd backend
uv run alembic upgrade head        # against LOCAL postgres on 5433, not staging
uv run pytest
uv run ruff check . && uv run mypy app
bash -n scripts/deploy
```

Then, against the **local** database, prove the boundary rather than assuming it —
connect as `mbai_readonly` and confirm each of these fails:

- `SELECT * FROM public.extractions`
- `INSERT INTO readonly.<any view> …`
- `CREATE TABLE readonly.x (i int)`
- `DROP VIEW readonly.<any>`
- A query returning a raw SSN or TIN through any view

And that a plain `SELECT` on a view succeeds.

**Do not run the migration against staging.** I run that.

---

## Stop and report — do not work around

- Two Alembic heads.
- Any table whose debugging value genuinely requires an unredacted PII column —
  that is a decision for me, not a default.
- `rds_iam` not working with the driver in use.
- Any way the role can still reach a base table after `REVOKE ALL ON SCHEMA public`.

## Do not

- `git push`. Commit locally.
- Run the migration, the query stage, or any deploy stage against staging.
- Grant the role anything in `public`.
- Add an SSM endpoint, a bastion, or a security group rule. The point of this ticket
  is that none of those are needed.
- Pass SQL or any credential through argv.
- Make the stage capable of writing, "just in case."
