# LP-MB-Admin-01 — Roles as a set (`user_roles`), the company owner, and the company audit log

Admin and roles, ticket 1 of 5. **Status: built, not committed (see Result).** Next: LP-MB-Admin-02 (permission keys).
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

## Result

**Count before changing anything:** 127 constructions of `User(role=...)` (122 in tests across 116
files, 5 in `app/scripts/`), plus 3 reads of `user.role` in `app/` (`User.__repr__`, `add_user`'s
success line, `require_role`) and 1 in tests (`test_add_user`). The 122 test sites now go through
`tests/user_factory.make_user`; the two existing wrappers (`tests/integration/factories.make_user`,
`test_dependencies._make_user`) call it.

**Built**
- Models: `UserRole.LOAN_OFFICER`; `UserRoleAssignment` (`user_roles`, unique `(user_id, role)`);
  `User.roles` (`lazy="selectin"`); `User.role_set` (the one accessor) and `User.is_owner`;
  `users.role` is `UserRole | None` with no default and is read or written nowhere in `app/`.
  `Company.owner_user_id` (FK users, RESTRICT, `use_alter`), with `foreign_keys=` on `Company.users`,
  `User.company` and the new `Company.owner` (`post_update`, since the two rows reference each other).
  `CompanyAuditLog` (`company_audit_log`, `action` VARCHAR(64) with no CHECK, index
  `(company_id, created_at DESC)`).
- Migration `0a7332974687` on `e3a9d4c7b512`: steps 1-5 as listed, backfill in SQL. It also swaps
  `ck_users_userrole` to admit `loan_officer` (restored on downgrade), because
  `test_migrated_checks_match_models` requires a migrated CHECK to match the model and the model
  shares `UserRole` with `user_roles.role`. It prints each company left with NULL `owner_user_id`.
- `app/services/company_audit.py`: `log_company_action` (flush, never commit) and `AuditAction`
  (`owner_transferred`, `role_backfilled`). The migration writes one `role_backfilled` row per company.
- `get_user_by_id` and `authenticate_user` load `User.company` with `selectinload` (login returns
  `is_owner`, so it needs the company too). `require_role` checks `role_set`.
  `UserPublic` gains `roles` (sorted) and `is_owner`; `role` is computed (`admin` iff ADMIN held).
- Scripts: `add_company` and `bootstrap_admin` make the first user an ADMIN and the owner (user flushed
  first). `add_user` takes several roles. `seed_dev` / `seed_dev_data`: the admin also holds PROCESSOR
  and is the owner, and a loan officer is added (`lo@demo.com`, `jordan@summit-demo.com`);
  `seed_dev_data --reset` clears the owner and the company's audit rows before deleting users.
  New `scripts/transfer_owner` (env vars, staging-only allowlist, refusal style of `add_user`).
- Tests: factory; role set round-trip and duplicate refused; `require_role` (ADMIN, PROCESSOR+ADMIN
  pass; PROCESSOR, LOAN_OFFICER, PROCESSOR+LOAN_OFFICER 403); `/auth/me` and login shape;
  `log_company_action`; `add_user`, `add_company`, `bootstrap_admin`, `transfer_owner`; and the
  `migrated_db` fixture (session-scoped, in `tests/conftest.py`, about 50 lines) with
  `test_user_roles_migration.py`. Three mutations were each caught: dropping `is_active` from the
  owner query, reverting `require_role` to a single-role check, and removing the company eager load.
- Full suite: 9858 passed, 2 failed, 12 skipped. The two failures were the readonly guard, now
  fixed (see below) and re-run with the migration test: 84 passed. ruff, mypy strict on `app/`, and
  pre-commit on all changed files are clean.

**Assumptions and deviations**
- `make_user` builds and does not take `db`: every call site already added and flushed its user, so
  a builder kept each test's transaction order unchanged.
- `add_user` is driven by environment variables from `./scripts/deploy add-user`, not argv, so
  "repeatable `--role`" is `ADD_USER_ROLE` as a comma-separated list (`ADMIN,PROCESSOR`); a repeat is
  dropped, an unknown or empty item refuses. The deploy stage's prompt and check accept the same.
- `migrated_db` yields the database at head plus an `alembic(...)` runner; the seeding is in the test,
  which steps back to `e3a9d4c7b512`, seeds the OLD column, upgrades, asserts, downgrades, and leaves
  the fixture empty and at head. A backfill has to be seeded before its migration runs, and
  LP-MB-Admin-05 will seed differently. Revisions are named rather than `-1` so a later migration on
  top does not move the test.
- "Active" admin for the owner means `is_active` and not soft-deleted; ties on `created_at` break by id.
- `user_roles`, `company_audit_log` and `companies.owner_user_id` are listed as excluded in
  `tests/test_readonly_query.py` (no readonly view, as the ticket says), with the reason.
- A user created without roles now holds none (there was a PROCESSOR default on the column).
- `backend/.env` in this worktree is a gitignored symlink to the main checkout's, and the tests ran
  against their own `mortgageboss_admin01_test` database via `TEST_DATABASE_URL`.

**Deferred**
- The owner guard itself: no code path deactivates a user or removes a role yet, so there was nothing
  to refuse. It lands with the role and deactivation API (LP-MB-Admin-03).
- Dropping `users.role`; readonly views for the new tables; logging the existing admin screens.
- The seed scripts have no tests of their own (they open their own session against the dev
  database); they were changed but not run.
