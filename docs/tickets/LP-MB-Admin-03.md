# LP-MB-Admin-03 — User management API and `/admin/people`

Admin and roles, ticket 3 of 5. **Status: planned, not built.** Needs LP-MB-Admin-01, LP-MB-Admin-02. Next: LP-MB-Admin-04.

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
