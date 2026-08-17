# Querying staging

Read-only SQL against the deployed database, for diagnosing something the logs cannot
answer. One command, no standing infrastructure, no interactive session.

```bash
./scripts/deploy staging query -c "select count(*) from loan_files"
./scripts/deploy staging query docs/queries/why-is-in3-firing.sql
./scripts/deploy staging query -c "select ..." --max-rows 500
```

Each run is a one-off ECS task on the existing `migrate` task definition — the same
mechanism as migrations, `bootstrap-admin` and `add-user`. It prints the SQL, then the
result, then the row count, and exits non-zero if anything failed. Output lands in
CloudWatch with the rest of the environment's logs.

## This path cannot return a raw SSN or TIN

That is the property the whole design exists to hold, so it is worth stating plainly
rather than leaving implied.

The query connects as `mbai_readonly`, which **has no privileges in schema `public` at
all**. Every base table is unreachable. It can read only the `readonly.*` views, and
those views either drop each column that can carry a document-derived identifier or pass
it through `readonly.scrub()`.

`readonly.scrub()` matches on the **shape of the value**, not on a list of field names:

| Input | Through the view |
|---|---|
| `123-45-6789` | `[REDACTED-ID]` |
| `123 45 6789` | `[REDACTED-ID]` |
| `987654321` | `[REDACTED-ID]` |
| `4111111111111111` | `[REDACTED-ID]` |
| `6028.02` | `6028.02` |
| `2025-04-04` | `2025-04-04` |

Shape matching is why a field that nobody has registered anywhere — a new extractor
column, or an account number buried inside a nested list row — is still redacted. A
denylist of known PII keys would let both through. The patterns are the same ones the
LP-209 at-rest guard uses, pinned together by a test so the two cannot drift apart.

It is deliberately over-broad: a legitimate identifier of nine or more digits is
redacted too. That is the accepted trade.

### How JSON columns are scrubbed

`extracted_data`, `details`, `snapshot_json`, `load_bearing_tags` and the rest come back
as **JSON, still queryable** — the scrub walks the document rather than its serialized
text, so it can only ever replace a scalar:

| In the document | Through the view | Why |
|---|---|---|
| `"employee_ssn": "123-45-6789"` | `"[REDACTED-ID]"` | A string scalar, scrubbed. |
| `"account": "4111111111111111"`, at any depth | `"[REDACTED-ID]"` | Nested objects and list rows are walked. |
| `"tin": 123456789` | `"[REDACTED-ID]"` (a **string**) | A number cannot hold the marker and stay a number, so an identifier-shaped integer changes type. |
| `"confidence": 0.8500000000000001` | unchanged | Fractional values are never identifiers, and the digit rule would otherwise eat the fraction digits. |
| `"tokens_used": 12345`, `"amount": 350000.00` | unchanged | Ordinary numbers are the debugging signal. |
| `"epoch_ms": 1755212345678` | `"[REDACTED-ID]"` | The over-broad trade again: a 9+ digit integer cannot be told apart from an identifier. |

Keys are never touched, so the shape of a document — which fields filled, at what
confidence — survives intact even where values do not.

**If you ever need a value this path will not return, that is a conversation, not a
grant.** Adding a base-table grant to make something convenient would silently undo all
of the above.

## What the views do not contain

Dropped entirely, because there is no useful redaction of them:

| Column | Why |
|---|---|
| `documents.full_text` | The whole document as text. A W-2's full text contains the SSN verbatim. |
| `mismo_imports.catch_all` | The raw MISMO payload — SSN, DOB and full addresses by design. |
| `borrowers.ssn` | Fernet ciphertext. Useless as well as sensitive. |
| `borrowers` name / DOB / email / phone / declarations | Direct identifiers. |
| `properties.address_line`, `address_line_2`, `postal_code` | The subject property street address. |
| `findings.source_snippet` | A literal quote lifted from the document — where a name or address appears verbatim. |
| `users.hashed_password`, `email`, names | A credential, and staff identifiers. |
| `loan_files.inbox_token` | A capability: whoever holds it can post documents to the file. |
| `loan_files.loan_officer_name` / `_email` | A named individual. |
| `communications.body` / `subject` / `sender` / `recipient` | Outbound email to borrowers. |
| `companies.settings` | Arbitrary per-company JSON; may hold integration config. |
| `documents.generic_analysis`, `summary`, `storage_path` | Model prose over the document, and the object path. |
| `lenders.contact_email` / `contact_phone` | Named contacts. |

The full list, with the reasoning for each, is in `docs/tickets/C7-query-stage-result.md`
and in comments beside each view in the migration.

Everything else is available, with free text and JSON scrubbed: findings and their
`details` and `load_bearing_tags`, extractions (structure and confidences intact,
amounts and dates intact), snapshots, observations, verifications, needs, stated
financials, and the rule-engine reference tables.

## Running a verification from the terminal

```bash
./scripts/deploy staging verify LF-WCHG
```

Enqueues a verification run for one loan file and then **follows the worker log** until it
finishes, so the deploy → run → read loop never needs the UI. Same one-off task mechanism as
`query`: the migrate task definition, inside the VPC, with the task role — no token to mint,
refresh, or paste into a terminal.

Two behaviours worth knowing, both deliberate:

**It forces by default.** The API caches on an *input* fingerprint: when the stated and verified
data hash the same as the last completed run it returns those findings without re-calling the AI.
That is right for a user and wrong here, because this loop changes *code*, not inputs — with the
cache honoured a deploy would hand back the old findings and look like it did nothing. `VERIFY_FORCE=0`
opts out.

**It supersedes a stuck run, but only a genuinely stuck one.** A `RUNNING` run older than the API's
own 25-minute threshold is marked failed and replaced; a younger one is left alone and the stage
refuses, telling you how long is left. The threshold is imported from the API rather than restated, so
"stuck" has one definition — the one the UI already acts on. That matters because a run six minutes
into its AI calls looks identical to a wedged one from the outside, and killing it would destroy real
work and real spend.

The tail follows for 25 minutes (`DEPLOY_VERIFY_TAIL_TIMEOUT_SECONDS`), above the worker's own
20-minute hard limit, so a run that dies is seen dying rather than abandoned a moment before its
failure is logged. Ctrl-C stops the tail, not the run.

## Staging only

The `query` and `query-setup` stages refuse any environment not listed in
`QUERY_ENVIRONMENTS` in `scripts/deploy`, which is `staging`. Three independent gates
keep this out of production:

1. **The stage** refuses a non-listed environment before reading any SQL.
2. **The role does not exist.** The migration creates the schema and views — harmless
   everywhere, since a view with no grantee grants nothing — but *not* the login role.
   That comes from `./scripts/deploy <env> query-setup`, which has the same allowlist.
3. **IAM.** `rds-db:connect` for `mbai_readonly` is granted only where Terraform's
   `db_instance_resource_id` is wired, which is staging.

In production the result is `readonly.*` exists and nothing on earth can select from it.

## Setting it up in a new environment

Once, after `migrate`:

```bash
./scripts/deploy <env> query-setup     # creates the role + grants; refuses non-allowlisted envs
```

Add the environment to `QUERY_ENVIRONMENTS` in `scripts/deploy` first — deliberately, in
a commit someone reviews. To remove it again: `QUERY_SETUP_DROP=1 ./scripts/deploy <env>
query-setup`. Only `1`, `true`, `yes` or `on` mean drop; anything else, including `0` and
`false`, provisions as normal.

The ordered version of this — the instance attribute, the IAM policy, why `query-setup`
must come after both, and how to read each failure signature — is
[`docs/deploy/query-stage.md`](deploy/query-stage.md).

The task also needs a region: the connection uses an RDS IAM auth token, and signing it
is an AWS API call. `AWS_REGION` is set on the task definition from `var.aws_region`
(`infra/envs/*/main.tf`), with `S3_REGION` and `BEDROCK_REGION` as fallbacks. Fargate has
no instance metadata service, so with none of them set the task fails with `NoRegionError`
before it reaches the database. `QUERY_DATABASE_URL` bypasses IAM auth entirely and is the
escape hatch if that is ever the problem.

## Limits

- **One statement per run.** No semicolon-separated batches. Refused before connecting.
  A `;` inside a string literal or a comment is not a second statement — the check reads
  SQL structure, so `where message like '%;%'` and `-- count things; fast` both run.
- **`SELECT` or `WITH` only.** Enforced by database grant; the script's check is a
  clearer error message, not the control. It also refuses a write verb *anywhere* in the
  statement, not only at the start, because `with x as (delete from … returning 1)
  select * from x` opens with a perfectly legal `with`.
- **30-second `statement_timeout`**, and at most 2 concurrent connections for the role.
- **100 rows** printed by default (`--max-rows` to raise). The cap is applied as the rows
  arrive, over a server-side cursor, so `select * from readonly.snapshot_records` does not
  drag every JSONB document into the task to print the first hundred. Every printed line
  goes to CloudWatch, so a wide query is expensive in log volume as well as tokens.
- **Latency.** Each run is a container start plus a CloudWatch fetch — tens of seconds.
  It suits a considered question far better than twenty exploratory ones; prefer one
  query that answers the question to a sequence that narrows in on it.

## The views constrain future migrations

The 32 `readonly.*` views cover nearly every base table, and PostgreSQL refuses
`ALTER TABLE … ALTER COLUMN … TYPE` or `DROP COLUMN` while a view depends on the column:
`cannot alter type of a column used by a view or rule`. A migration that changes such a
column has to drop the views, make the change, and recreate them.

The C7 migration exposes `drop_readonly_schema()` and `create_readonly_schema()` for
exactly that; its `drop_readonly_schema` docstring carries the copy-paste recipe for
loading them from another revision (by path — a revision filename is not an importable
module name). If the changed column is one a view SELECTS, edit the view text in the same
change: recreating the old definition over a renamed column fails on the recreate.
