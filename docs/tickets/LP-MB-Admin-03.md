# LP-MB-Admin-03 — User management API and `/admin/people`

Admin and roles, ticket 3 of 5. **Status: built, not committed (see Result).** Needs LP-MB-Admin-01, LP-MB-Admin-02. Next: LP-MB-Admin-04.

## What and why

A company's users are created by a script today, and nothing can change them afterwards. This ticket
lets an admin see the company's people, edit their details, change their roles, and
deactivate or reactivate them, from a People page. Adding a new person is the next ticket (invites);
until then `scripts/add_user` still does it.

## The rules

| Rule | What happens |
|---|---|
| **Who** | `users.manage` (Admin). Everything is scoped to the actor's company; another company's user id is a 404, not a 403. |
| **Own roles** | Nobody changes their own roles, and nobody deactivates themselves. 409. |
| **Admins make admins** | Any Admin may add or remove any role, ADMIN included, on anyone except themselves and the owner. |
| **The owner** | The user named by `companies.owner_user_id` cannot be deactivated and cannot lose ADMIN from inside the app. 409 with "account owner: contact MortgageBoss". Everything else about the owner (name, title, phone, other roles) is editable by any admin, the owner included. Only `scripts/transfer_owner` changes who the owner is, and it refuses a target who is not an active admin of the same company, so the company always has one. No separate "last admin" rule: the owner is it. |
| **At least one role** | An active user holds at least one role. 422. |
| **Deactivate** | `is_active = false`. Access ends on the user's next request or refresh: both already read `is_active` live (LP-24), so there is no session to revoke. History, roles and authorship stay. |
| **Reactivate** | `is_active = true`, same roles as before. |
| **Audit** | Every change writes one `company_audit_log` row with before and after values. Never a password or a hash. |

## Scope

- Service `app/services/users.py` taking an `Actor`; API `app/api/users.py`; schemas.
- `users` gains profile columns and `last_login_at` (set on successful login).
- `/admin/people` page and a People link on the admin index and in the admin context column.

## Out of scope

- Creating a user (LP-MB-Admin-04). Changing a user's email (it is the global identity, ADR-042).
- Password reset by an admin, MFA, listing or revoking sessions (tokens are stateless; no session table).
- Reassigning a deactivated user's files (LP-MB-Admin-05 adds it to this page).
- Signature block, branch, company profile and branding, borrower accounts.

## Schema changes

`users`: `phone` VARCHAR(32) null; `title` ShortStr null; `nmls_id` VARCHAR(16) null;
`licensed_states` JSON not null, `server_default='[]'` (two-letter codes, validated in the schema);
`sees_all_loans` bool not null default false (read by LP-MB-Admin-05); `last_login_at` timestamptz null.

No `user_licenses` table: an NMLS ID is one per person and the states are a list. A table earns its
place when a state licence needs its own number or expiry.

## API

All under `/api/v1/users`, `users.manage` required.

- `GET /users` — the company's users, active and inactive, with roles, `last_login_at`. Filters:
  `status=active|inactive`, `role=`. No pagination until a company has more users than fit a page.
- `GET /users/{id}`.
- `PATCH /users/{id}` — `first_name`, `last_name`, `phone`, `title`, `nmls_id`, `licensed_states`,
  `sees_all_loans`. `nmls_id` and `licensed_states` are accepted for any user; the UI shows them for
  loan officers.
- `PUT /users/{id}/roles` — body `{roles: [...]}`, the full set. Applies the rules above; the audit row
  holds `from` and `to` sets.
- `POST /users/{id}/deactivate`, `POST /users/{id}/reactivate`.
- `GET /audit-log` (`audit.view`) — the company's rows, newest first, cursor-paginated, filter by
  `target_type` / `target_id`. Read-only; the People page uses it for a user's history.

## UI

**Mockups:** `docs/design/admin/png/03-people.png`, `04-edit-person.png`, `05-edit-loan-officer.png`,
`06-deactivate-reassign.png` (the file section of 06 belongs to LP-MB-Admin-05), `12-audit-log.png`. Build to
the component code (`components/ui/*`) where the PNG and the code disagree.

`/admin/people`: a table (name, email, role chips, status, last login) with an "Inactive" toggle. A row
opens a side sheet: details form, role checkboxes, deactivate or reactivate, and that user's audit
history. Controls the actor may not use are disabled with the reason in a tooltip (own roles, the owner): the server enforces; the UI only explains. Role classes and
radii follow the palette and radius conventions in `CLAUDE.md`.

## Tests

- Each rule in the table: the allowed case and the refused case, with the status code.
- Tenant isolation: list, get, patch, roles, deactivate against another company's user → 404, and
  nothing changes.
- Owner: deactivate → 409; remove ADMIN → 409; name, title and other roles on the owner may change;
  the owner editing their own name → 200, their own roles → 409 like anyone else.
- `transfer_owner` to an inactive user or a non-admin → refused; to a user of another company → refused.
- A deactivated user's access token → 401 on the next request; refresh → 401.
- Audit: each action writes exactly one row; the row for a role change holds both sets; no row contains
  `hashed_password`.
- `last_login_at` set on login, not on refresh.
- Frontend: table renders, sheet saves, disabled states for the two guardrails, 409 shown inline.

## ADR note

None new. Applies ADR-440 to ADR-442.

## Result

**Built**
- Migration `c5874fbee899` on `0a7332974687`: `users.phone` VARCHAR(32), `title` VARCHAR(100),
  `nmls_id` VARCHAR(16), `licensed_states` JSON default `[]`, `sees_all_loans` default false,
  `last_login_at`. `readonly.users` gains `title`, `licensed_states`, `sees_all_loans`,
  `last_login_at`; `phone` and `nmls_id` are excluded (each identifies one person) and listed in
  `tests/test_readonly_query.py`. `docs/querying-staging.md` updated.
- `last_login_at` is set in the login endpoint on success (a commit there now), not on refresh.
- `app/services/users.py`: `list_users`, `get_user`, `update_user_details`, `set_user_roles`,
  `deactivate_user`, `reactivate_user`, each `ensure(actor, users.manage)` and scoped to
  `actor.company_id`. The rules as the table, no "last admin" rule. `set_user_roles` deletes removed
  rows and inserts added ones with `granted_by_user_id`. One audit row per change
  (`user_details_changed`, `user_roles_changed`, `user_deactivated`, `user_reactivated`), nothing for a
  no-op (a PATCH that changes nothing, the same role set, deactivating someone already inactive).
- Refusals: `SelfRoleChange`, `SelfDeactivation`, `OwnerProtected` (409) and `NoRoles` (422) in
  `app/core/errors.py`, under one `UserRuleError` base with one handler that sends each class's status
  and sentence in the standard envelope.
- `company_audit.list_audit_log`: `audit.view`, newest first, cursor `(created_at, id)`, filters
  `target_type`, `target_id`, `actor_user_id`, plus `since` (for the page's "Last 30 days"), and a
  `total`. Actor and target names resolved in one query with `resolve_user_names`; a company target
  takes the company's name.
- API: `app/api/users.py` (`/users`, `users.manage` on the router) and `app/api/audit_log.py`
  (`/audit-log`, `audit.view`); schemas in `app/schemas/users.py` (with the state-code check) and
  `app/schemas/audit.py`.
- Frontend: `lib/types/users.ts`, `lib/api/users.ts`, `lib/api/audit-log.ts` (infinite query on the
  cursor), `lib/admin-time.ts`; `/admin/people` and `/admin/audit`; People and Audit log in the admin
  column; "What you can manage" rows for both on the overview. `components/admin/people-table.tsx`,
  `person-sheet.tsx`, `deactivate-dialog.tsx`, `audit-table.tsx`, built to the mockups' copy.
- Tests, backend (36 in `tests/api/test_users_lp_mb_admin_03.py`, one migration test): 403 for
  PROCESSOR and LO on every endpoint; another company's user 404 everywhere with nothing changed; list
  and its filters; details PATCH (only what is sent, audited, no-op writes nothing, bad input 422,
  clearing an optional field); self, owner, at-least-one-role, admins make and unmake admins; role
  audit with both sorted lists; deactivation ends access on the next request and on refresh;
  reactivation keeps roles; no audit row holds a password or any user's hash; log order, names,
  cursor, filters, bad cursor; `last_login_at` on login and not on refresh; migration defaults on an
  existing row and the view's columns. Frontend: table rows, inactive toggle, search and role filter;
  Licensing only with Loan officer ticked; the three disabled states with their reasons; only changed
  fields PATCHed; roles PUT with the full set; the 409 inline; deactivate dialog through to an inactive
  row; audit from → to, system rows, Load more, a filter refetch; overview rows by key.
- Mutations, each caught: removing the self check, the owner deactivate check, the owner ADMIN check,
  the tenant scope, the at-least-one-role check; not setting `last_login_at`; dropping the cursor
  (backend). Removing the own-row and owner disables, sending every field, always showing Licensing,
  not writing a change into the list, and ignoring the cursor (frontend).
- Backend: 10019 passed, 12 skipped; ruff, mypy strict clean. Frontend: 2587 passed (212 files);
  `tsc --noEmit` and `biome check` clean.

**Assumptions and deviations**
- `audit_value` now keeps a list as a JSON list (each item encoded) instead of `str(list)`, so a role
  change holds two sorted lists. The full suite showed no caller relied on the old repr.
- "At least one role" is enforced for every user, not only active ones: reactivation keeps the roles a
  person had, so an inactive person with none could not be brought back usefully.
- Deactivation is audited as `status: active → inactive`, matching the mockup's Change column.
- `licensed_states` accepts the 50 states, DC, PR, GU and VI, stored sorted.
- `phone`, `title` and `nmls_id` may be cleared by sending `null`; the names, the states list and
  `sees_all_loans` may not.
- The People page filters (search, role, show inactive) work on the one list the server returns; the
  API's `status` and `role` filters exist and are tested but the page does not need them.
- The mockup's deactivate copy says "he"; the dialog says "they".
- A disabled control's reason is a tooltip on hover and an `sr-only` sentence beside the control. It
  is not reachable by keyboard focus (Biome refuses a `tabIndex` on the wrapper); the server's message
  still appears inline if a refused change is attempted another way.
- The existing LP-MB-Admin-01 migration test queried `information_schema` without a schema and passed
  or failed depending on order once `readonly.users` had a `role` column again after a downgrade; it now
  names `public`.
- During the first mutation run, one run with the self check removed hung in a later test rather than
  failing; with `-x` it fails at `test_self` as expected. Not investigated further.

**Deferred**
- Invitations (LP-MB-Admin-04; the tab is a disabled stub), the Files column and the deactivate
  dialog's file section (LP-MB-Admin-05), email change, password reset, export, folding the lender,
  overlay and email audits into this log.

**Review fixes (after `21a32911`)**
1. The owner rule and the audit log's company name read the EFFECTIVE company (ADR-443) by query,
   not the actor's own loaded company; so do the company-settings GET and PATCH from LP-MB-Admin-02,
   which had the same read. No test can fail on this today: the two companies are always the same.
   The test named for it pins that an ownership change is honoured, and measured: a stale cached read
   passes it too. It says so in its docstring.
2. Each change locks the person's row and re-reads it (`FOR UPDATE`, `populate_existing`), so two
   admins acting at once cannot both decide from the old state (a duplicate role row's 500, a second
   deactivation row). Side effect, documented on `_locked`: re-reading the actor's own row unloads
   `actor.user.company`, so nothing after a change reads it.
4. Login writes `last_login_at` with a Core UPDATE that leaves `updated_at` alone.
5. Names are stripped and must keep a character: `" "` is a 422.
6. The audit log counts only on its first page; later pages carry `total: null`.
8. Audit times carry the year once it is not this year.
9. The sheet checks a licensed state against the same list as the server as it is typed, and keeps
   a bad code in the box with the reason instead of failing the whole Save.
Mutations: removing the lock, the `updated_at` guard, the first-page count, the year and the state
check are each caught.

Not changed, by decision:
- 3. An admin may tick "Sees all company loan files" on themselves. Only admins hold `users.manage`,
  and admins already hold `loan.view_all`, so it grants nothing. Revisit if a non-admin role ever
  gets `users.manage`.
- 7. Audit names come from users whether or not soft-deleted. No code path soft-deletes a user today
  (deactivation is `is_active`); revisit with user deletion.
- 10. `GET /users`'s `status` and `role` filters stay: the brief asked for them and they are tested,
  though the page filters its one list client-side.
