# Company admin page, roles and use cases

Date: 2026-11-11, reviewed same day (section 9 lists the review changes). Scope: the company-level administration surface and the permission model for staff roles, in support of the Arive-style system (`claude/arive-style-system-build-and-integrations.md`).

## 1. What exists today (from the repo)

- `companies` (name, slug, settings JSON, is_active) with `users`, `lenders`, `loan_files`, mail domains.
- `users` with roles **PROCESSOR** and **ADMIN** only; email + hashed password; no invite, no self-service creation, no deactivation UI (`is_active` exists on the model).
- Auth API: login, refresh, logout, me. No user-management endpoints. Companies and users are created by seed/scripts only.
- Admin-only surfaces already gated by `require_role(ADMIN)`: lenders and lender contacts, lender condition settings, overlay admin, evidence admin, mailbox connections, validation aid. Frontend has `/admin` with `email`, `lenders`, `validation` pages.
- Per-user preferences (density, mail client, aggression default).
- `loan_file_participants` for external parties; `loan_officer_name/email` are free-text fields on the loan file, not a user link.

So "admin" today means "can configure lenders and email"; there is no people management and no loan-officer role.

## 2. Two kinds of tenant

The current customers are **processing companies** (admin + processors, working files for broker clients). The Arive-style system adds **broker shops** (admin + LOs + processors). One admin page must serve both; the difference is which roles are in use and whether the company is a *grantor* (broker giving a processing firm access) or a *grantee* (processing firm receiving it). A company can be both.

## 3. Role model

Roles are **additive capabilities**, not a ladder. A user holds one or more of:

| Role | Who | Core capability |
|---|---|---|
| **Owner** | the account holder | everything Admin can do, plus billing and the ability to add/remove Admins; cannot be removed; at least one per company |
| **Admin** | operations lead | manage people, integrations, templates and settings |
| **Loan Officer (LO)** | NMLS-licensed originator | own loans, invite borrowers, price and structure |
| **Processor** | in-house processor | work the file: documents, needs, conditions, verification, submission |
| **Contract Processor** | processor at a third-party processing company | Processor capabilities on another company's granted files |
| **Assistant / Support** (later) | LOA, admin staff | read and data entry, no pricing, submission or PII unmasking |

Rules:
- Any user can hold several roles; an owner-operator typically holds Owner, LO and Processor. The UI shows the union.
- A loan has a **loan team**: one owning LO, one or more processors, optional assistant. Team membership decides who sees and edits a specific file; role decides which actions are available on it.
- Default visibility: LO sees own loans; Processor sees assigned loans; Admin/Owner see all company loans. Admin can grant "see all" to anyone.
- Contract processors are users of **their own** company; the broker's admin grants their company access to selected or all loan files; they appear on loan teams like any processor but under a cross-company grant.
- Guardrails: last Owner cannot be deactivated; a user cannot change their own roles; Admin cannot grant Owner.

## 4. Platform (MortgageBoss) use cases, outside the company page
- Create a company and its first Owner (sign-up flow or MortgageBoss-side onboarding).
- Suspend/reactivate a company; set plan and seat limits; feature flags per company.
- Support "view as" into a company with the customer's consent, fully logged.
These need a platform-admin role separate from company roles; they are listed so the company page is not asked to do them.

## 5. Admin / Owner use cases

### 5.1 People
- Invite a staff member by email with roles; invite expires; resend; cancel.
- Create accounts directly (no invite) for migration.
- Edit a user: name, roles, NMLS ID and licensed states, phone, title, signature block, branch.
- Deactivate / reactivate; deactivation revokes sessions, keeps history, and triggers reassignment.
- Reassign a departing user's loans and open tasks to another LO or processor in one action.
- Reset a user's password / MFA; require MFA company-wide.
- View last login, active sessions, per-user audit of sensitive actions.
- Manage contract-processing relationships in both directions: as grantor (give a processing firm access, all or selected files, dated) and as grantee (see which clients granted access).
- Manage borrower accounts on company loans: resend invite, reset borrower login, revoke access.

### 5.2 Company profile and branding
- Legal name, DBA, company NMLS ID, address, phone, logo, colours, support email.
- Borrower-facing settings: portal subdomain, application sections enabled, custom questions, consent texts and versions, welcome message, team card content.
- Default loan-team rules (auto-assign processor by LO, by branch, round robin); whether processors may create loans, invite borrowers, send disclosures.
- Branches (later) with their own NMLS IDs and addresses.

### 5.3 Integrations and credentials
- Lenders: add, approve-with, contacts, condition settings, overlays (exists).
- Email: mail domain, mailbox connections, sending enabled (exists).
- Credit vendor accounts, DU/DO and LPA credentials, pricing engine account, disclosure/e-sign account: per-company, encrypted, test-connection, rotation, audit of who changed them.
- SMS sender settings; API keys and webhooks (later, Zapier-style).

### 5.4 Templates and catalogs
- Needs templates (company additions), condition vocabulary, email/SMS templates, pre-approval letter template, disclosure form sets.
- Stage and tracker configuration (rename, hide, add).

### 5.5 Compliance and reporting
- Activity and audit log across the company, including PII unmasking events; export.
- Consent text versions and effective dates.
- Data retention policy for withdrawn/abandoned applications; borrower data-access and deletion requests.
- NMLS call report data export; pipeline and revenue reports.
- Legal hold, archive, withdraw and purge of a loan file (Admin only; purge blocked under legal hold).

### 5.6 Billing (Owner, later)
- Seats by role, usage (files verified), invoices, plan changes.

## 6. Loan Officer use cases
- Create a loan file (manual, from lead, from MISMO import) and own it.
- Invite borrower and co-borrower; resend, revoke; take over the application; reopen a section with a reason.
- Share a personal "apply now" link that creates a loan under this LO.
- Edit the 1003 before submission; view borrower progress and the submitted snapshot.
- Order credit (under stored consent) and view the report.
- Price, select product and lender, request lock, track expiry.
- Run DU/LPA and read findings.
- Generate pre-approval letters and loan quotes.
- Assign or change the processor; add business contacts (agent, title).
- Communicate with borrower and agent from the loan's email address; SMS.
- See own pipeline, tasks, dashboard; cannot see other LOs' loans unless granted.
- Cannot: manage users, change integrations, edit company settings, see company-wide reports (unless also Admin).

## 7. Processor use cases
- Work the assigned pipeline; filter by stage, tracker, due dates.
- Review the application; flag discrepancies back to the LO or borrower.
- Generate and send needs (auto from the file, from the catalog, custom); track status; accept or reject uploads with reasons.
- Review documents: classification, extraction, findings, evidence; run verification; work Needs Attention.
- Maintain conditions: import lender sheets, match to documents, build the round package, mark sent, track rounds to clear-to-close.
- Order third-party items: VOE, title, HOI, flood, appraisal; maintain trackers and dates.
- Run calculators (DTI, LTV, MI, reserves); request LO changes to structure.
- Prepare the lender package and submission; record lender loan number and status.
- Communicate with borrower, lender, title and agent from the loan's address; tasks and reminders.
- Cannot: price or lock, change the LO, manage users or integrations. Creating loans, inviting borrowers and sending disclosures are company settings (default on).

**Contract Processor** adds: switch between client companies; see only granted files; their own company's admin manages their account; the broker admin controls the grant.

## 8. Shared use cases (all staff)
- Own profile: name, phone, signature, password, MFA, preferences.
- Search loans and borrowers within visibility.
- Notes, tasks, timeline on files they can see.
- Notification settings per event type.
- Unmask a borrower's SSN/DOB on a file they can see: explicit action, logged.

## 9. Review changes (2026-11-11)
Added after a second pass: the two tenant kinds; an **Owner** role with guardrails (last owner, no self-role-change, admins can't grant owner); platform-level use cases kept out of the company page; grants in both directions; borrower-account management by staff; licensed states on LO profile; PII unmasking as a logged permission; archive/withdraw/purge with legal-hold interaction; data-access and deletion requests; API keys and webhooks; task reassignment on deactivation; processor defaults set to "on".

## 10. Permission matrix

| Action | Owner | Admin | LO | Processor | Contract Proc. |
|---|---|---|---|---|---|
| Billing, add/remove Admins | ✔ | – | – | – | – |
| Manage users, roles, grants | ✔ | ✔ | – | – | – |
| Company settings, branding, portal config | ✔ | ✔ | – | – | – |
| Integrations and credentials | ✔ | ✔ | – | – | – |
| Templates and catalogs | ✔ | ✔ | – | – | – |
| Create loan file | ✔ | ✔ | ✔ | config | – |
| Invite / revoke borrower | ✔ | ✔ | ✔ | config | – |
| Edit 1003 pre-submission | ✔ | ✔ | ✔ | ✔ | ✔ |
| Order credit | ✔ | ✔ | ✔ | ✔ | ✔ |
| Price, select product, lock | ✔ | ✔ | ✔ | – | – |
| Run AUS | ✔ | ✔ | ✔ | ✔ | ✔ |
| Needs, documents, verification | ✔ | ✔ | ✔ | ✔ | ✔ |
| Conditions and package | ✔ | ✔ | ✔ | ✔ | ✔ |
| Disclosures (send) | ✔ | ✔ | ✔ | config | – |
| Submit to lender | ✔ | ✔ | ✔ | ✔ | ✔ |
| Unmask SSN/DOB (logged) | ✔ | ✔ | ✔ | ✔ | ✔ |
| Change loan team | ✔ | ✔ | own | – | – |
| Archive / withdraw / purge, legal hold | ✔ | ✔ | – | – | – |
| See all company loans | ✔ | ✔ | grant | grant | granted files |
| Company reports and audit | ✔ | ✔ | own | – | – |

"config" = company setting decides (default on). Every row is a permission key checked in the service layer, so the matrix is data, not code.

## 11. Build notes
- Roles: add **OWNER**, **LOAN_OFFICER**, **CONTRACT_PROCESSOR**; move to a `user_roles` table.
- Tables: `user_invites` (email, roles, token hash, expiry, invited_by, accepted_at), `loan_teams` (loan_file_id, user_id, team_role), `company_grants` (grantor company, grantee company, scope, dates), `user_licenses` (user_id, nmls_id, states).
- `permissions` resolution in `dependencies.py` alongside `require_role`; services check permission keys, not roles; the matrix lives in one module.
- Replace free-text `loan_officer_name/email` on loan files with the loan-team LO link (keep the text for imports).
- Admin UI: `/admin/people`, `/admin/company`, `/admin/portal`, `/admin/integrations` (credentials), `/admin/templates`, `/admin/audit`; existing lenders, email and validation pages move under it.
- Every admin action writes to the activity log with actor, target and before/after values (reuse `field_changes` / `audit_value`).
- Sequencing: people management, roles and loan teams first (the borrower invite flow needs an LO identity on the loan); company grants second (existing processing-company customers need them); integration credentials arrive with each vendor; templates, reports, billing later.

## 12. Decisions after checking the repo (2026-11-11, updated 2026-11-13 after the build)

Where this section and sections 3 to 11 disagree, this section is current. Tickets: `docs/tickets/LP-MB-Admin-01.md` to `LP-MB-Admin-05.md`; screens: `docs/design/admin/` (README there). ADRs reserved: ADR-440 to ADR-445. Tickets committed as `bb678090`; the build as `da020dcd` … `8dbabe01`.

**Roles and the owner**
- Roles are an additive set in `user_roles`: Admin, Loan officer, Processor. No Owner role and no Contract processor role.
- Owner and Admin are identical in capability. Any admin can give or remove any role, Admin included, on anyone but themselves. A company can have many admins.
- `companies.owner_user_id` marks the admin created at onboarding. The app refuses to deactivate that user or remove Admin from them ("account owner: contact MortgageBoss"); everything else about them is editable. Only `scripts/transfer_owner`, run by MortgageBoss on request, changes it, and it refuses a target who is not an active admin of the same company. That is the whole guarantee that a company keeps an admin; there is no separate "last admin" rule.
- Nobody changes their own roles or deactivates themselves.
- Billing (section 5.6) is unassigned: with owner and admin equal it is an admin capability or a later decision when billing exists.

**Audit and settings**
- Admin actions go to a new `company_audit_log` table, not the activity log, because `activity_logs` rows must belong to a loan file. Loan-team changes still go to the file's timeline.
- Three company settings live in `companies.settings`: processors may create loan files (on), processors may invite borrowers (on), restrict loan files to their team (off). They are edited from a card on the Administration overview; no separate Company page.
- Team-only visibility is off for existing companies and on for new broker shops. No assignment data exists today, so a default-on rule would hide every file from every processor.

**Loan officers and files**
- The free-text loan officer stays permanently for processing companies, whose LOs are not users. An internal LO is copied into the text fields.
- Team changes: admins on any file, a loan officer on their own files. Processors cannot reassign (open: one matrix cell if that proves too tight).
- No `user_licenses` table: `nmls_id` and `licensed_states` are columns on `users`.

**Out of scope**
- Contract processing (`company_grants`, the Contract processor role, ticket 06): removed 2026-11-11. Sections 2, 3, 5.1, 7, 10 and 11 still describe it; treat those parts as not planned. The one-function "effective company" seam stays in ticket 02 because it costs nothing.
- The validation aid: stays as it is behind `require_role(ADMIN)`, not moved to permission keys or given a nav entry. It inventories the older rule set (`conventional`/`fha` Python rules), which does not run on files; retargeting it to the YAML specs is its own decision. Likewise lender overlays: the editor is kept and gated, and the engine still does not read overlays.
- The Email admin page: `/admin/email` is a 404 stub and nothing mounts the mailbox-connections component or the mail-domain state. Screen 11 shows what it should become; it needs a small wiring ticket outside the five.
- Not possible without new infrastructure: listing or revoking sessions (tokens are stateless; deactivation takes effect on the next request), MFA, task reassignment (no task model).

**Numbering**: `LP-MB-Admin-NN` ticket ids and ADR-440 onward, because `mbai-arive` and `improve_communication_feature` branch from the same commit (last LP-1015, ADR-421).

**Build state (2026-11-13)**: all five tickets built and committed on `mbai-admin-panel` (`da020dcd` … `8dbabe01`), not pushed. Backend 10093 tests, frontend 2627, ruff/mypy/biome/tsc clean. Each ticket's Result section records what was built, assumptions and review fixes.

**Decided during the build** (each recorded in its ticket):
- A loan officer may change the team only on files where they are the LO; "holds `loan.team.change`" alone is not enough. Encoded as data (`OWN_FILES_ONLY`) plus one pure function `may_change_team` in `core/permissions.py`.
- A role a person still uses on files cannot be removed (409 naming the file count); move their files first.
- Renaming a person updates the locked loan-officer text on every file they are LO of. Replacing an LO soft-deletes the old LO's participant row unless it was hand-trusted.
- A creator holding Loan officer becomes the file's LO only when the file names no other loan officer.
- Invite tokens travel in the URL fragment and request body (never a path), unlike upload links; ADR-444 says why. The raw token sits in the Celery broker until sent.
- Invite addresses are stored the way login looks them up (domain lowercased, local part as typed).
- `readonly.users` no longer exposes `role`; `readonly.user_roles` and `readonly.loan_teams` exist. `phone`, `nmls_id`, `user_invites` and `company_audit_log` have no readonly view (identifiers or prose).
- A `migrated_db` test fixture runs the real Alembic migrations against a scratch database; the repo had none before.

**Part 2 of loan teams (restrict files to team) is parked, with a measured cost.** The survey (`docs/tickets/LP-MB-Admin-05-survey.md`) found 223 doors to a loan file: 68 through `ScopedLoanFile`, 69 through `get_loan_file` directly (29 of them in the conditions router's own dependency), 70 by child id or company-wide query, 16 Celery tasks. The original "98 uses, one fix" estimate was wrong. Part 2 needs about ten enforcement points, a signature change to `get_loan_file`, a decision on the processor-copy job, and a per-route test. It is groomed as `LP-MB-Admin-06` (2026-11-13): visibility carried by a `FileScope` type that replaces `company_id` at every file gate, so a forgotten door is a type error; a per-route test generated from the survey. To be built before the LOS track adds routes.

**Loose ends outside the five tickets**:
- Staging sends from `noreply@mortgageboss.ai`, which is not a verified SES identity, and `MAIL_TRANSPORT=ses` there, so invites on staging neither send nor show a link. Fix: `SMTP_FROM_EMAIL = "noreply@mail.staging.mortgageboss.ai"` in `infra/envs/staging/main.tf` (an INFRA change), or verify the root domain.
- `/admin/email` is still a 404 stub; the mail-domain state and mailbox-connections component need a small wiring ticket.
- Deploy order: for 01, migrate the database before deploying the code (older code requires `users.role`); for 02, deploy the frontend with or before the backend (`UserPublic` lost `role`).
- Before merging: run `alembic upgrade head` against a copy of the real staging database and read the list of companies left with no owner; reconcile the Alembic head with whichever of `mbai-arive` / `improve_communication_feature` merges first.

**Build order** (as built): 01 roles, owner and audit log → 02 permission keys and company settings → 03 user management and `/admin/people` → 04 invites → 05 loan teams Part 1 + Part 2 survey.

**Still open**: whether a processor may hand a file to another processor; whether `noreply@mortgageboss.ai` is a verified SES identity in staging (invite email; copy-the-link mode until then).
