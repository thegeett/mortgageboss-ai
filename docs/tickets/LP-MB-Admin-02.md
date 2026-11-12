# LP-MB-Admin-02 — Permission keys, and replacing `require_role`

Admin and roles, ticket 2 of 5. **Status: planned, not built.** Needs LP-MB-Admin-01. Next: LP-MB-Admin-03.

## What and why

After LP-MB-Admin-01 a user holds several roles, but the code still asks "is this user an admin?". With six
roles and a matrix of who may do what, that question gets asked in more and more places and drifts.
This ticket makes the matrix one table in one module. Code asks "may this user do X?" by a named key.
Changing who may do something becomes a change to that table.

It also puts in one small piece of plumbing: a single place that answers "which company is this request
acting in?". Today the answer is always the user's own company. Cross-company access is out of scope, but
keeping this in one function costs nothing and avoids a rewrite if it returns.

No user gains or loses anything here: admins keep every admin screen, processors keep
creating loan files.

## Scope

- `app/core/permissions.py`: a `Permission` StrEnum, `ROLE_PERMISSIONS` (role → set of keys),
  `CONFIG_PERMISSIONS` (key → role + company setting that switches it), and
  `resolve_permissions(roles, company_settings) -> frozenset[Permission]`. Pure functions, no database.
- Keys in this ticket, each with a call site today or in LP-MB-Admin-03 to LP-MB-Admin-05:

| Key | Admin | LO | Processor |
|---|---|---|---|
| `users.manage` | ✔ | | |
| `company.settings.manage` | ✔ | | |
| `audit.view` | ✔ | | |
| `lenders.manage` | ✔ | | |
| `overlays.manage` | ✔ | | |
| `mail.manage` | ✔ | | |
| `evidence.manage` | ✔ | | |
| `loan.create` | ✔ | ✔ | setting |
| `loan.view_all` | ✔ | | |
| `loan.team.change` | ✔ | own files | |
| `borrower.invite` | ✔ | ✔ | setting |

  `borrower.invite` has no call site yet: it is the seam for the borrower portal session, defined here
  so that session does not invent its own. The other rows of the doc's matrix (pricing, credit, AUS,
  disclosures, billing, templates) get a key when their feature exists, not before.
- `CompanySettings`: a Pydantic model over `companies.settings` (which exists, is `{}` everywhere, and
  nothing reads). Fields: `processors_can_create_loans = True`, `processors_can_invite_borrowers =
  True`, `restrict_loans_to_team = False` (stored here, enforced by LP-MB-Admin-05 Part 2; until then it
  is written and read back and changes nothing). Unknown keys in the JSON are kept, missing keys take the default, so no data migration.
- `Actor` (frozen dataclass): `user`, `company_id` (the effective company), `roles`, `permissions`,
  `is_owner`. `CurrentActor` dependency builds it once per request from the user and their eager-loaded
  company; no extra query.
- `require_permission(Permission.X)` dependency for routes; `ensure(actor, Permission.X)` for services,
  raising a domain error the API maps to 403. New services (LP-MB-Admin-03 onward) take an `Actor`.
- Four of the five `require_role(ADMIN)` call sites move to keys: `lenders.py` → `lenders.manage`,
  `overlay_admin.py` → `overlays.manage`, `mailbox_connections.py` → `mail.manage`, `evidence.py` →
  `evidence.manage`. `validation_aid.py` keeps `require_role(ADMIN)` untouched: the validation aid is out of
  this work's scope, so `require_role` stays for that one caller and is deleted when that page is dealt
  with.
- `POST /loan-files` and the MISMO import route require `loan.create` (on by default for processors).
- `get_current_company_id` returns `actor.company_id`. It is the only place that decides the effective
  company. New code uses `CurrentCompanyId` / `Actor`, never `current_user.company_id`.
- `/auth/me`, login, refresh return `permissions: list[str]`. `role` is removed from the response.
- `GET /company/settings` and `PATCH /company/settings` (`company.settings.manage`), each change audited
  with before and after values. The three settings appear as a card on the admin overview (the mockup's
  screen 01); a separate Company page is not needed for three checkboxes.
- Frontend: `User.roles`, `User.permissions`; a `useCan(permission)` hook; `NavItem.requiredRole`
  becomes `requiredPermission`; the eight `role === "admin"` checks (admin index, lenders, lender
  detail, icon rail, header) become `useCan(...)`. The validation page keeps its `role === "admin"` check
  as an interim, reading the derived `role`. The admin index shows only the sections
  the user can open. This stays UX only; the backend is the boundary.

## Out of scope

- Moving the ~100 existing `current_user.company_id` uses in 18 API files onto `CurrentCompanyId`. It is
  mechanical, it touches the same files the other two branches are editing, and nothing needs it now. A
  follow-up ticket when a reason appears.
- Per-user permission overrides. Per-file checks beyond
  `loan.team.change` (LP-MB-Admin-05).

## Schema changes

None.

## API

- `UserPublic`: `+permissions`, `-role`.
- 403 bodies unchanged (`Insufficient permissions`).

## UI

**Mockups:** `docs/design/admin/png/01-admin-overview.png` (the overview with the company settings card);
`README.md` there explains the conventions. The amber box on each screen is an implementation note, not UI.

No new screens apart from the settings card. Gating reads permissions.

## Tests

- A table-driven test of the whole matrix: for every role and every key, allowed or not; for the two
  setting-driven keys, both values of the setting. This test is the matrix's second copy on purpose: a
  change to the table that was not meant shows up as a failing row.
- A multi-role user gets the union. No roles → no permissions.
- Each of the four migrated admin routers: 200 for ADMIN, 403 for PROCESSOR and LOAN_OFFICER.
  `validation_aid` still passes its existing role test.
- `loan.create`: processor 201 by default, 403 when the company setting is off; LO 201 either way.
- A guard test that reads `app/api` as text and fails on a **new** `current_user.company_id` (an
  allowlist holds today's files, to be emptied by the follow-up).
- Frontend: `useCan`, nav visibility, the admin index for an LO (not shown) and an admin (shown); the
  settings card saves and shows the 403 for a non-admin.

## ADR notes (ADR-442, ADR-443)

- **ADR-442 — authorization is by permission key; the matrix is data in one module.** Roles are never
  compared outside `permissions.py`. Route dependencies and services call the same resolver. Supersedes
  the role checks of LP-24.
- **ADR-443 — one function decides the effective company.** Tenant scope is `actor.company_id`, not
  `user.company_id`. Today they are equal, and nothing planned changes that; the seam exists so that cross-company
  access, if it ever returns, is one function and not a hundred call sites. The access token still carries identity only (LP-22 unchanged).
