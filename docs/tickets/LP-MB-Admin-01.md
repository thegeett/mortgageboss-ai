# LP-MB-Admin-01 — Roles as a set (`user_roles`), the company owner, and the company audit log

Admin and roles, ticket 1 of 5. **Status: planned, not built.** Next: LP-MB-Admin-02 (permission keys).
Use cases: `docs/design/admin/company-admin-and-roles-use-cases.md` (section 12 is the current state; earlier sections are the original brief).

## What and why

Today a user has exactly one role (`users.role`: processor or admin). A broker shop's owner is also a
loan officer and often processes files, so a user has to be able to hold several roles at once. This
ticket stores roles as a set, adds the loan-officer role, and marks one admin per company as the
**owner**: the account holder created at onboarding, who cannot be deactivated or demoted from inside
the app. Owner is not a role and grants nothing extra; it is a guardrail. It also adds
the table that admin actions are logged to, because the existing activity log cannot hold them: every
`activity_logs` row must belong to a loan file, and inviting a user has no loan file.

Nothing a user can see changes in this ticket. Every existing admin can still do what they could.

## Scope

- `UserRole` gains `LOAN_OFFICER` (stored value `loan_officer`). No OWNER role (decided 2026-11-11: owner and
  admin are the same in capability) and no contract-processor role (cross-company access is out of scope).
- `companies.owner_user_id` (FK users, RESTRICT, nullable only for the migration). The owner is always an
  ADMIN; the service layer refuses to remove ADMIN from, or deactivate, the owner. Changing the owner is a
  platform script (`scripts/transfer_owner`), run by MortgageBoss on the customer's request, never an API.
- New table `user_roles`; `User.roles` relationship, loaded with the user (`lazy="selectin"`, the app is
  async and `get_current_user` must not lazy-load). `get_user_by_id` also eager-loads `User.company`:
  LP-MB-Admin-02 reads company settings on every request and must not lazy-load either.
- `companies.owner_user_id` and `users.company_id` point at each other, so both relationships declare
  `foreign_keys=` explicitly or SQLAlchemy refuses to map them. The migration adds the column after the
  tables exist; `add_company` flushes the user before setting it.
- `users.role` stops being read or written by the app, including `User.__repr__` and the
  `add_user` success line. The column stays in the database for one release
  so the migration can be rolled back; a later ticket drops it.
- `require_role` checks the set (interim rule; LP-MB-Admin-02 replaces `require_role` altogether).
- `/auth/me`, login and refresh return `roles` (list). `role` stays in the response, derived: `admin`
  if the user holds ADMIN, else `processor`. `is_owner: bool` is added. The frontend is not touched here.
- Provisioning scripts and seeds write `user_roles`: `add_company` and `bootstrap_admin` create the
  first user as ADMIN and set `owner_user_id` to them; `add_user` takes one or more roles; `seed_dev` / `seed_dev_data` add a
  loan officer and an owner who also holds PROCESSOR so later tickets have data.
- New table `company_audit_log` and one helper, `log_company_action`, next to `log_activity`.

## Out of scope

- Permission keys and the matrix (LP-MB-Admin-02). Any API to change roles (LP-MB-Admin-03). Frontend.
- Dropping `users.role`. A `readonly.*` view for the new tables (add when someone needs to query them).
- Logging the existing admin screens (lenders, overlays, email) to the new audit log. Follow-up.

## Schema changes

`user_roles`
| Column | Type | Notes |
|---|---|---|
| id | UUID pk | |
| user_id | FK users, CASCADE, index | |
| role | VARCHAR(32) + CHECK (`str_enum(UserRole)`) | |
| granted_by_user_id | FK users, SET NULL, nullable | null = system or migration |
| created_at | timestamptz | |

Unique `(user_id, role)`. No soft delete: revoking a role deletes the row, and the audit log keeps the
history.

`company_audit_log`
| Column | Type | Notes |
|---|---|---|
| id | UUID pk | |
| company_id | FK companies, RESTRICT, index | the company the action happened in |
| actor_user_id | FK users, SET NULL, nullable | null = system |
| action | VARCHAR(64), **no CHECK** | `AuditAction` StrEnum in code; see ADR note |
| target_type | VARCHAR(32) | `user`, `invite`, `company`, `loan_file` |
| target_id | UUID, nullable | |
| summary | VARCHAR (MediumStr) | human-readable |
| detail | JSON | `{"changes": field_changes(before, after)}` and action-specific keys |
| created_at | timestamptz, index `(company_id, created_at desc)` | |

Append-only: no `updated_at`, no `deleted_at`, no update or delete code path.

Migration (one revision, on the current head `e3a9d4c7b512`):
1. Create both tables.
2. Backfill `user_roles` from `users.role`, one row per user (deleted and inactive users included).
3. Per company, `owner_user_id` = the earliest-created active ADMIN. A company with no active admin
   keeps NULL and is printed by the migration; nothing fails. `scripts/transfer_owner` fixes those by hand.
4. `users.role` becomes nullable (it has no server default, so an insert that no longer sets it would
   otherwise fail).
5. Downgrade: copy back (`admin` if the user holds admin, else `processor`), restore NOT NULL, drop the
   column and both tables.

Branch note: `mbai-arive` and `improve_communication_feature` sit on the same Alembic head. Whichever
merges second needs a merge revision.

## API

No new endpoints. `UserPublic` gains `roles: list[UserRole]`; `role` becomes a computed field.

## UI

None. The series' screens are in `docs/design/admin/` (README there); this ticket has no screen.

## Tests

- Migration backfill, run against a database built by migrations (not `create_all`): one row per user;
  one owner per company with an active admin, and the owner holds ADMIN; downgrade restores `users.role`.
  **No such harness exists yet**: every migration test in the repo reads the revision files as text, and
  `conftest` builds the schema with `create_all`. This ticket adds a `migrated_db` fixture that runs
  `alembic upgrade head` against a scratch database once per session. LP-MB-Admin-05 reuses it for its own
  backfill. Budget it as half the ticket.
- `require_role(ADMIN)` passes for ADMIN and for a user holding PROCESSOR + ADMIN; 403 for
  PROCESSOR, LOAN_OFFICER.
- `/auth/me` returns `roles` and the derived `role`.
- `log_company_action` writes one row with `field_changes` output in `detail`, flushes, does not commit.
- Scripts: `add_company` produces an ADMIN who is the owner; `add_user` accepts several roles;
  `transfer_owner` moves `owner_user_id` to another active admin of the same company and writes an audit row.
- First step of the build: count the tests and fixtures that construct `User(role=...)` and report the
  number before changing them; move them to one factory helper.

## ADR notes (ADR-440, ADR-441)

- **ADR-440 — roles are an additive set.** A user holds one or more roles; capability is the union.
  Owner is NOT a role: `companies.owner_user_id` names one admin whom the app refuses to deactivate or
  demote. Owner and admin have identical capability; the owner is the account the platform created at
  onboarding and the one guaranteed to remain. Admins may make and unmake other admins freely; the
  company must always keep at least one active admin, which the owner guarantees. Supersedes the single
  `users.role` of LP-12.
- **ADR-441 — admin actions go to `company_audit_log`, not `activity_logs`.** The activity log is a
  loan file's timeline (ADR-052, ADR-071): owned by the file, deleted with it, no `company_id`. A
  company-level action has no file. `action` deliberately has **no CHECK constraint**, a stated
  exception to ADR-037: every ticket in this series adds values, and the CHECK-swap pattern has already
  caused two incidents on `ActivityType` (LP-637, LP-UI-033). The StrEnum is the only writer.
