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
query-setup`.

## Limits

- **One statement per run.** No semicolon-separated batches. Refused before connecting.
- **`SELECT` or `WITH` only.** Enforced by database grant; the script's check is a
  clearer error message, not the control.
- **30-second `statement_timeout`**, and at most 2 concurrent connections for the role.
- **100 rows** printed by default (`--max-rows` to raise). Every printed line goes to
  CloudWatch, so a wide query is expensive in log volume as well as tokens.
- **Latency.** Each run is a container start plus a CloudWatch fetch — tens of seconds.
  It suits a considered question far better than twenty exploratory ones; prefer one
  query that answers the question to a sequence that narrows in on it.
