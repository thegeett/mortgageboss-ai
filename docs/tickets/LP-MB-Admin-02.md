# LP-MB-Admin-02 — Permission keys, and replacing `require_role`

Admin and roles, ticket 2 of 5. **Status: built, not committed (see Result).** Needs LP-MB-Admin-01. Next: LP-MB-Admin-03.

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

## Result

**Built**
- `app/core/permissions.py`: `Permission` (the eleven keys), `ROLE_PERMISSIONS`, `CONFIG_PERMISSIONS`
  (role → {key: the `CompanySettings` field that grants it}; the two PROCESSOR cells), and
  `resolve_permissions(roles, settings)`. Pure; imports only `UserRole`. `PermissionDeniedError` lives
  here too, so `app/core/errors.py` can map it without importing a service.
- `app/core/company_settings.py`: `CompanySettings` (`extra="allow"`) and `parse_stored_settings`,
  which `Company.settings_model` uses (in `app.core`, not `app.schemas`, so the model does not import
  the API layer). `app/schemas/company.py`: `CompanySettingsUpdate` (`extra="forbid"`, all optional,
  explicit `null` refused) and `CompanySettingsPublic`. No migration.
- `app/api/dependencies.py`: `Actor`, `get_current_actor` (no query; the user and company are already
  loaded), `CurrentActor`, `require_permission`. `get_current_company_id` returns `actor.company_id`.
  `require_role` is kept, documented as superseded, for `validation_aid.py` only (left untouched apart
  from a comment saying so).
- `app/services/authorization.py`: `ensure(actor, key)`. The refusal becomes the same 403 envelope as
  the route gate through a handler registered in `app/core/errors.py`, where the app's other exception
  handlers are registered.
- Routers: `lenders.manage`, `overlays.manage`, `mail.manage`, `evidence.manage` replace
  `require_role(ADMIN)`; `POST /loan-files` and `POST /loan-files/import-mismo` require `loan.create`.
- `GET`/`PATCH /company/settings` (`api/company.py`, `company.settings.manage`) through
  `services/company_settings.update_company_settings(db, actor, update)`: writes `companies.settings`
  (unknown keys kept), and one `company_settings_changed` audit row with `field_changes` output. A
  PATCH that changes nothing writes nothing.
- `UserPublic`: `+permissions` (sorted), `-role`. Built from the `User` in a before-validator, so the
  model does not import the permission module (which imports the user model).
- Frontend: `User` has `roles`, `permissions`, `is_owner` and no `role`; `useCan` in
  `lib/auth/permissions.ts`; `NavItem.requiredPermission` (Administration → `users.manage`);
  `visibleNavItems(permissions)`; `app/(protected)/admin/layout.tsx` holds the one "available to admins
  only" gate, and the admin index, lenders list and lender detail lost their copies. The admin index
  shows each section only to a user holding its key. The validation page gates on
  `useCan("lenders.manage")`. The settings card (`company-settings-card.tsx`,
  `lib/api/company-settings.ts`) uses the mockup's copy.
- Tests: the matrix cell by cell under both setting values (72 cases), union, no roles; the four
  routers for ADMIN, PROCESSOR+ADMIN, PROCESSOR, LOAN_OFFICER; `loan.create` for processor (default,
  on, off), LO (on, off) and admin; MISMO import refused with the setting off; settings GET defaults,
  PATCH audit and unknown-key survival, no-op PATCH, effect on the next request, 403 for PROCESSOR and
  LO, unknown field 422; `ensure` and its 403 body; the `current_user.company_id` guard (18 files,
  and a check that the list only shrinks). Frontend: `useCan`, nav with and without `users.manage`,
  the admin layout for an LO and an admin, admin index sections by key, the settings card (load, save,
  403 on load and on save).
- Mutations, each caught: removing the `loan.create` gate; granting processors `mail.manage`;
  `useCan` returning true for any signed-in user; `visibleNavItems` ignoring the key.
- Backend: 9970 passed, 12 skipped; ruff, mypy strict clean. Frontend: 2564 passed (208 files) with
  `CI=true TZ=UTC pnpm test`, `tsc --noEmit` and `biome check .` clean.

**Assumptions and deviations**
- The ticket's UI section has the validation page keep a derived `role`; the build brief removed
  `role` entirely, so that page uses `lenders.manage` (held by exactly the admins) as its interim gate.
- `CONFIG_PERMISSIONS` is keyed role → key → setting name rather than key → (role, setting); same
  data, and it makes "what does this role get from settings" one lookup.
- The mail router's admin case is asserted as 404 on an unknown connection (past the gate), because
  creating a connection is superseded (LP-1011) and its own test is skipped.
- `flag_modified` is called as asked, but it is not load-bearing: the service assigns a new dict, which
  SQLAlchemy already counts as a change. Removing the line leaves every test green (measured); the
  comment says so.
- The admin layout gates every `/admin/*` page on `users.manage`, the key the nav item uses. Today that
  is exactly the admins; once a role holds e.g. `lenders.manage` without `users.manage`, the layout's
  key will need revisiting.

**Deferred**
- Moving the existing `current_user.company_id` uses (18 files) onto `CurrentCompanyId`; the guard's
  allowlist is emptied by that follow-up.
- `restrict_loans_to_team` is stored and returned and enforces nothing (LP-MB-Admin-05 Part 2).
- `borrower.invite`, `audit.view`, `users.manage` (as an API gate), `loan.view_all`, `loan.team.change`
  have no call site yet (LP-MB-Admin-03 to 05, and the borrower portal).
- Deleting `require_role` with the validation aid.

**Review fixes (after `db2e9815`)**
1. The way in to a new file follows `loan.create`: the dashboard's New file button, the empty
   pipeline's "Create your first file" (and its sentence), and `/loan-files/new` itself, which now
   says who creates files instead of offering a form the API refuses.
2. The settings card no longer shows an error for one render while loading successfully: the form
   reads `draft ?? data`, so it is filled on the render the data arrives.
3. A stored setting that does not parse no longer fails every request in the company (login
   included). `parse_stored_settings` gives that setting its default and logs its name; writes stay
   strict.
4. Saving settings re-reads the company row under `FOR UPDATE`, so two saves at once, or another
   writer's key, are not overwritten by a stale copy.
6. After a save, the card re-reads the signed-in user, so that admin's permissions follow the setting
   at once. Other signed-in users pick it up on their next session refresh; the API is current for
   everyone.
7. `PATCH /company/settings` refuses an explicit `null` (422) instead of treating it as omitted.
8. `CompanySettings` moved to `app/core/company_settings.py` (models no longer import schemas).
9. A test that every `UserRole` has a `ROLE_PERMISSIONS` row.
Also: `useCan` reads a user sent without `permissions` (a backend from before this ticket, if the
frontend deploys first) as holding nothing, rather than crashing every page that asks.
Not changed: 5 (the admin layout's single key, recorded above) and 10 (settings parsed more than once
per request; small).
