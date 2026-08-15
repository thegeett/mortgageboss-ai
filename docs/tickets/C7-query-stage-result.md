# C7 — Read-only query access to staging · RESULT

**Branch:** `bedrock_integration_with_rules_staging`
**Status:** implemented, verified against the LOCAL database on port 5433. Nothing was run
against staging or any AWS resource.

---

## What this ticket is

There was no way to inspect the staging database, so diagnosing anything meant reasoning
from CloudWatch alone — which had already cost real time on this project (the same
evening, a rule-engine crash was diagnosed entirely from log lines because nothing else
was available).

C7 adds a query path with three properties: no standing infrastructure, read-only **at
the database level** rather than by convention, and unable to return a raw SSN or TIN.
The last one is the constraint that shapes the whole design, because the consumer is an
agent and the exfiltration path is the transcript, not the network.

## Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | `./scripts/deploy staging query <file.sql>` runs it and prints results | ✅ | Stage implemented; exercised end-to-end against the local DB through `app.scripts.run_query` (see Verification). Not run against staging, per instruction. |
| 2 | Read-only **at the database level**, not by convention | ✅ | `default_transaction_read_only = on` on the role; `CREATE TABLE` → `cannot execute CREATE TABLE in a read-only transaction`; `INSERT` → `permission denied for view findings` |
| 3 | **Raw SSNs and TINs unreachable** | ✅ | `readonly.scrub()` redacts dashed/spaced SSNs, bare 9+ digit runs, and card/account numbers — including inside nested list rows and under keys in no registry. Table of proofs below. |
| 4 | Writes, DDL and base-table access all fail | ✅ | 8 negative assertions, all failing correctly (table below) |
| 5 | Every query is logged with the SQL that ran | ✅ | `run_query.py` prints `--- SQL ---` and the statement *before* connecting, so a query that times out is still attributable. Task output goes to the environment's CloudWatch group. |
| 6 | No new standing infrastructure, no monthly cost | ✅ | One-off ECS task on the **existing** `migrate` task definition. No EC2, no endpoints, no security-group change. |

Two criteria are met differently from the ticket's suggestion, both deliberately —
see Decisions 1 and 2.

## What was implemented

| File | What |
|---|---|
| `backend/alembic/versions/20260814_2300_d4e8a1c05b73_*.py` | New revision from `c9d3f1a6b2e4`. `readonly` schema, `scrub`/`scrub_json`/`scrub_jsonb`, **32 views**. Does **not** create the role. |
| `backend/app/scripts/provision_query_role.py` | Creates/repairs (or drops) `mbai_readonly` and its grants. Refuses any environment outside its allowlist. |
| `backend/app/scripts/run_query.py` | Validates one `SELECT`/`WITH`, connects as `mbai_readonly` with an RDS IAM token, prints SQL → table → row count. |
| `scripts/deploy` | `query-setup` and `query` stages, `QUERY_ENVIRONMENTS="staging"` allowlist, `-c` / `--max-rows` options. |
| `infra/modules/data/*` | `iam_database_authentication_enabled = true`; new `db_instance_resource_id` output. |
| `infra/modules/compute/*` | `rds-db:connect` on the `api_task` role (which the migrate task definition uses), scoped to one dbuser ARN; disabled when `db_instance_resource_id` is empty. |
| `infra/envs/staging/main.tf` | Wires `db_instance_resource_id`. |
| `backend/tests/test_readonly_query.py` | 31 tests: scrub behaviour against real PostgreSQL, pattern-parity with the at-rest guard, column-drift guards, `validate_sql`. |
| `docs/querying-staging.md`, `CLAUDE.md` | How to use it, what it will and will not return, and a pointer telling a future session it exists. |

## Decisions, with reasoning

### 1. Redaction matches the SHAPE of a value, not a list of key names

The ticket asked for "strip the known PII keys". I did not, because a key denylist fails
open, and this layer is the last line of defence rather than one of several.

Three ways it fails open, all live in this codebase: `_PII_FIELDS` documents against
itself that *"PII inside a captured LIST row … is NOT routed"*; 121 schema specs and 99
generated extractors mean new fields arrive that no list written today mentions; and a
second hand-maintained list in a migration will drift from the first, leaving the newer
and less-tested one as the real boundary.

`readonly.scrub()` therefore matches identifier shapes over the serialized JSON, which is
recursive by construction — it never asks what a field is called. Patterns are taken
verbatim from the LP-209 at-rest guard and pinned to it by a test, so the two cannot
diverge silently. ADR-384.

Cost: deliberately over-broad. A legitimate ≥9-digit identifier is redacted too. Same
trade the at-rest guard already makes.

### 2. `extracted_data` is scrubbed, not dropped — and the role is not created by the migration

**Scrubbed** (the ticket offered the choice): the *shape* of `extracted_data` — which
fields filled, at what confidence — is usually the thing being debugged, and amounts and
dates survive the scrub intact. Dropping it would remove most of the column's value to
remove a risk the scrub already removes.

**Role not in the migration** (a change from the ticket's task 1, prompted by the
explicit requirement that this not exist in production): migrations run in every
environment, so `CREATE ROLE` there puts a login role into production. Gating inside the
migration was rejected — a migration that behaves differently per environment produces
databases that report the same `alembic current` with different schemas. The schema and
views are safe everywhere (a view with no grantee grants nothing); the role moved to an
environment-gated provisioning stage. ADR-385.

### 3. IAM database authentication, with no fallback password

`GRANT rds_iam` is applied where the role exists on RDS; the task generates a 15-minute
token. No password is set in any environment, so there is nothing to store, rotate or
leak. `QUERY_DATABASE_URL` exists as an override, used only for local testing.

### 4. `original_filename` is kept (scrubbed), not dropped

It is user-supplied metadata rather than document content, it is already visible in the
app UI and in API responses, and findings reference documents by filename — dropping it
would remove much of the ticket's debugging value. It passes through the scrub, so a
digit-shaped identifier in a filename is redacted. **Flagged for your review:** a
filename *can* contain a borrower's name, which the scrub cannot catch. Say the word and
it moves to the dropped list.

### 5. Three gates keep this out of production, none trusted alone

The stage refuses non-allowlisted environments before reading any SQL; the role does not
exist unless deliberately provisioned; `rds-db:connect` is granted only where Terraform's
`db_instance_resource_id` is wired. Verified resting state after the migration alone:
**`0 role, 32 views`**.

### 6. Role privileges are not tested in pytest

PostgreSQL roles are **cluster-scoped**, not database-scoped, so creating or dropping one
from a test would reach outside the test database and race any other connection to the
same cluster. The privilege boundary is verified manually (below); the drift guards in
the test suite are what keep the *view definitions* honest between those runs.

## Columns excluded from the views — the full list

Dropped entirely (no useful redaction exists):

| Table | Column | Why |
|---|---|---|
| `documents` | `full_text` | The entire document as text. A W-2's full text contains the SSN verbatim. |
| `documents` | `generic_analysis`, `summary` | Model prose over the document; quotes values. |
| `documents` | `storage_path` | Points at the stored object. |
| `mismo_imports` | `catch_all` | The raw MISMO payload — SSN, DOB, full addresses by design. |
| `mismo_imports` | `raw_file_path` | Points at the raw file. |
| `borrowers` | `first_name`, `middle_name`, `last_name` | Direct identifiers; not digit-shaped, so unreachable by the scrub. |
| `borrowers` | `ssn` | Fernet ciphertext — useless as well as sensitive. |
| `borrowers` | `date_of_birth`, `email`, `phone` | Direct identifiers. |
| `borrowers` | `declarations` | The 1003 declarations JSON. |
| `properties` | `address_line`, `address_line_2`, `postal_code` | The subject property street address. |
| `findings` | `source_snippet` | A literal quote from the document — observed carrying a full name and a street address on 2026-08-14. |
| `loan_files` | `inbox_token` | A capability: whoever holds it can post documents to the file. |
| `loan_files` | `loan_officer_name`, `loan_officer_email` | A named individual. |
| `users` | `hashed_password` | A credential. |
| `users` | `email`, `first_name`, `last_name` | Staff identifiers. |
| `companies` | `settings` | Arbitrary per-company JSON; may hold integration config. |
| `lenders` | `contact_email`, `contact_phone` | Named contacts. |
| `communications` | `sender`, `recipient`, `subject`, `body` | Outbound email to borrowers. The envelope is enough to debug the pipeline; the content never is. |

Kept but passed through `readonly.scrub()`: `extractions.extracted_data`,
`findings.message` / `details` / `applied_record` / `load_bearing_tags` /
`resolution_note`, `document_findings.description` / `details`, `finding_events.detail`,
`snapshot_records.snapshot_json`, `observations.value` / `structured` / `reasoning`,
`verifications` error text, `needs_items` text fields and `source_facts`,
`activity_logs.summary` / `detail`, `validation_verdicts.corrected_value` / `note`,
`calculator_overrides` / `dti_overrides` / `ltv_overrides` notes, `stated_assets` and
`stated_liabilities` `holder_name`, `stated_employers.employer_name`,
`documents.original_filename`, `mismo_imports.parse_warnings`, `lenders.notes`.

Exposed unchanged: ids, foreign keys, enums, amounts, dates, counts, confidences, and
the rule-engine reference tables (`rules`, `tags`, `rule_tags`, `tag_dependencies`,
`graduation_candidates`) which hold no loan data at all.

## Verification

Local database on port 5433 (`docker compose`), never staging.

**The privilege boundary**, as `mbai_readonly`:

| Attempt | Result |
|---|---|
| `SELECT count(*) FROM public.extractions` | `ERROR: permission denied for table extractions` |
| `SELECT ssn FROM public.borrowers` | `ERROR: permission denied for table borrowers` |
| `SELECT full_text FROM public.documents` | `ERROR: permission denied for table documents` |
| `SELECT full_text FROM readonly.documents` | `ERROR: column "full_text" does not exist` |
| `INSERT INTO readonly.findings …` | `ERROR: permission denied for view findings` |
| `CREATE TABLE readonly.x (i int)` | `ERROR: cannot execute CREATE TABLE in a read-only transaction` |
| `DROP VIEW readonly.findings` | `ERROR: cannot execute DROP VIEW in a read-only transaction` |
| `CREATE TABLE public.y (i int)` | `ERROR: cannot execute CREATE TABLE in a read-only transaction` |
| `SELECT count(*) FROM readonly.loan_files` | `30` ✅ |
| unqualified `SELECT count(*) FROM extractions` | `99` — resolves to the **view** via the `search_path` pin ✅ |
| session settings | `default_transaction_read_only=on`, `statement_timeout=30s`, `search_path=readonly` |

**The redaction**, through `readonly.extractions` on a row carrying every shape:

| Field | Stored | Returned |
|---|---|---|
| `employee_ssn` | `123-45-6789` | `[REDACTED-ID]` |
| `recipient_tin` | `987654321` | `[REDACTED-ID]` |
| `spaced_ssn` | `123 45 6789` | `[REDACTED-ID]` |
| `brand_new_field_no_registry` | `555443333` | `[REDACTED-ID]` ← in **no** registry |
| `tradelines[0].account_number` | `4111111111111111` | `[REDACTED-ID]` ← inside a **nested list row** |
| `gross_pay` | `6028.02` | `6028.02` ✅ |
| `pay_date` | `2025-04-04` | `2025-04-04` ✅ |

The last four rows are the point: the two cases a key denylist cannot cover are covered,
and the debugging signal survives.

**Environment gating:** `staging → ALLOWED`, `production → REFUSED`, `dev → REFUSED`;
`provision_query_role` refuses `production` and refuses to run with no environment set.
After the migration alone: `0 role, 32 views`.

**Suite:** `4885 passed, 5 skipped, 1 xfailed` (was 4854 — 31 new). `ruff check` clean,
`mypy app` clean over 418 files, `bash -n scripts/deploy` clean, `terraform validate`
succeeds.

## A bug the drift guard caught

`test_no_model_column_drifts` failed on first run and was right to. I had built the views
by introspecting my **local** database, which carries four columns that exist in no model
and no migration in this repo — `borrowers.current_state`, `borrowers.current_address_type`,
`properties.county`, `verifications.fact_snapshot`. They are drift in my dev database from
another branch.

Staging does not have them, so `CREATE VIEW` would have failed on first contact. The views
were rebuilt against the models, which are the source of truth.

A second bug surfaced from end-to-end testing rather than unit tests: `_strip_leading_noise`
was unanchored, so it stripped whitespace *everywhere* and collapsed `select status` into
`selectstatus`, which then failed the `\b` check and refused every valid multi-word query.
Only the refusal cases had been exercised until then. Both the fix and a regression case
are in the suite.

## Not done, and why

- **Nothing was run against staging.** Migration, `query-setup`, `query` and every deploy
  stage are yours to run.
- **`terraform plan` was not run** — it reads live state. `terraform validate` passes.
- **IAM auth is untested against real RDS.** The code path (`generate_db_auth_token`) and
  the grant are in place, and `GRANT rds_iam` is applied conditionally because the role
  does not exist on local PostgreSQL. First real exercise is your `query-setup` run — if
  it fails there, that is the ticket's "rds_iam not working" stop condition and
  `QUERY_DATABASE_URL` plus a Secrets Manager password is the documented fallback.

## To run it, in order

```bash
./scripts/deploy staging migrate        # creates readonly schema + 32 views
./scripts/deploy staging query-setup    # creates mbai_readonly + grants (staging only)
./scripts/deploy staging query -c "select count(*) from loan_files"
```

Terraform must be applied before `query-setup` for IAM authentication to work — the
`rds-db:connect` grant and `iam_database_authentication_enabled` both come from it.
