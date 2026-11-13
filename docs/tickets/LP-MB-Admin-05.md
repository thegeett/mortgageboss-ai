# LP-MB-Admin-05 — Loan teams, and the loan officer as a user

Admin and roles, ticket 5 of 5. **Status: Part 1 built, not committed; Part 2 surveyed only (see Result).** Needs LP-MB-Admin-02, LP-MB-Admin-03.

## What and why

A loan file has no owner today: nothing says who is working it, there is no "My files", and the loan
officer is two free-text fields. This ticket gives each file a team: at most one loan officer who is a
user, and any number of processors. That is what lets a file say whose it is, lets a departing person's
files be handed over in one action, and gives the borrower portal a real LO identity to invite under.

Two parts. **Part 1** is the team itself and is safe to ship to everyone. **Part 2** is restricting who
can open a file to its team; it is off for every existing company and is gated on a survey (below),
because it is the part that can leak.

For a processing company, the loan officer works at the broker and is not a user. The free-text loan
officer stays, permanently, for exactly that case.

## Part 1 — the team

| Rule | What happens |
|---|---|
| **Slots** | `loan_officer` (at most one per file), `processor` (any number). `assistant` is reserved in the enum and not offered. |
| **Who can be on a team** | An active user of the file's company who holds the matching role (LOAN_OFFICER for the LO slot; PROCESSOR for processor). An Admin without those roles is not added to teams; they see every file anyway. |
| **On create** | The creator joins the team: as loan officer if they hold LOAN_OFFICER, otherwise as processor if they hold PROCESSOR. |
| **Who can change it** | `loan.team.change`: Admin on any file; a loan officer on files where they are the LO. |
| **Internal LO and the text fields** | Assigning a user as LO writes their name and email into `loan_officer_name` / `loan_officer_email`, so the nine places that read those (inbound trust list, condition drafts, overview, intake) keep working unchanged, and the participants list is re-seeded. While an internal LO is assigned the text fields are read-only (422 on edit). Removing the internal LO clears them only if they still match that user. |
| **External LO** | No internal LO: the text fields behave exactly as today. |
| **Timeline** | Each change writes one `LOAN_TEAM_CHANGED` entry on the file (who, slot, from, to). |
| **Reassign** | One action moves all of a user's team places to another eligible user. Offered on the People page when deactivating someone who is on teams. Deactivation itself does not remove anyone from a team. |
| **Filter** | The file list and saved views accept `assignee = me \| unassigned \| <user id>`, added to `list_loan_files` and `SavedViewFilters` together. This is the filter LP-UI-014 could not build. |

Open question, default as the doc's matrix has it: a processor cannot change a team, so in a processing
company only an Admin can hand a file to another processor. If that is too tight in practice,
it is one cell in the LP-MB-Admin-02 table.

## Part 2 — restrict files to their team

- Company setting `restrict_loans_to_team` (stored since LP-MB-Admin-02), default **false**. Existing companies are not changed:
  everyone sees every file, as today. A new broker shop is created with it on.
- When on: a user sees a file only if they are on its team, or hold `loan.view_all` (Admin), or
  have `sees_all_loans` set (LP-MB-Admin-03). Anything else is a 404, same as another company's file.
- **Gate: stop and report before building.** First produce a list of every route and every background
  read that reaches a loan file or its children, marked by how it gets there: through
  `get_scoped_loan_file` (98 uses, one fix covers them), through `get_loan_file` / `list_loan_files`,
  or by a child id or a company-wide query (flat documents, conditions by id, findings, messages,
  inbox, reminders, timeline, saved-view counts, dashboard). The third group is where a restricted file
  would leak. The list is reviewed before any enforcement code is written.
- Mail that matched no file has no team and stays visible to the company's inbox as now (ADR-421).

Part 2 is not needed by any current customer; it waits for the first broker shop.

## Out of scope

- Tasks (there is no task model, so "reassign open tasks" has nothing to move). Auto-assignment rules
  (by LO, branch, round robin). Notifying a user that they were added.
- Borrower invites and anything in the portal: the seam is `loan_teams` LO row + `borrower.invite`.
- Cross-company team members (out of scope).

## Schema changes

`loan_teams` (one row per member): `id`; `loan_file_id` FK CASCADE, index; `user_id` FK RESTRICT,
index; `team_role` VARCHAR + CHECK (`loan_officer`, `processor`, `assistant`); `added_by_user_id` FK SET
NULL; timestamps; `deleted_at`. A file-owned child with no `company_id` (ADR-052); the service checks
the user's company against the file's.

Partial unique indexes where `deleted_at IS NULL`: `(loan_file_id, user_id, team_role)`, and
`(loan_file_id)` where `team_role = 'loan_officer'`.

`ActivityType.LOAN_TEAM_CHANGED`: a constraint-swap migration that lists **every** value, copied from
the newest `*_activity.py` swap, with the guard in `tests/test_activity_type_migrations.py` passing.
The other branches may add values too; at merge the swap applied last must carry the union.

Backfill: for each file, the actor of its `FILE_CREATED` activity, if still active and a PROCESSOR,
becomes a processor on the team. Files with no such actor stay unassigned.

## API

- `GET /loan-files/{id}/team`.
- `PUT /loan-files/{id}/team/loan-officer` `{user_id | null}`.
- `POST /loan-files/{id}/team/members` `{user_id}` (processor); `DELETE /loan-files/{id}/team/members/{member_id}`.
- `GET /users/assignable?team_role=` — active users of the company eligible for a slot (any signed-in
  user; names and roles only).
- `POST /users/{id}/reassign-loans` `{to_user_id}` (`users.manage`) → count moved.
- `GET /loan-files` gains `assignee`. Loan file detail and summary gain `team`.

## UI

**Mockups:** `docs/design/admin/png/13-file-team-card.png` (A: broker shop with an internal LO; B: processing
company with the free-text LO), `14-pipeline-my-files.png`, and the file section of `06-deactivate-reassign.png`.

- File overview: a Team card (loan officer, processors) with add, change and remove for those allowed.
  The existing loan officer fields show the internal LO read-only, or the free-text inputs when there is
  none. Companies with no LOAN_OFFICER users see no LO picker, so the screen is unchanged for them.
- Intake form: same rule for the LO field.
- Dashboard: "My files" and "Unassigned" as filter values and in saved views.
- People page: deactivating a user who is on teams offers "Reassign their N files to…".

## Tests

- Each Part 1 rule, allowed and refused; one LO per file enforced by the index under concurrency.
- Write-through: assign, change, remove; text edit refused while internal; removal leaves a manually
  changed text alone; participants re-seeded.
- `assignee` filter in the list and in a saved view, with status and search combined.
- Activity entry per change; the migration guard test.
- Reassign moves every place and is tenant-scoped; target must be eligible.
- Backfill on a migrated database, using the `migrated_db` fixture from LP-MB-Admin-01.
- Part 2: with the setting off, nothing changes for anyone (the whole existing suite is the test). With
  it on: for **every route in the survey list**, a non-member processor gets 404 or an empty result; a
  member, an Admin and a `sees_all_loans` user get the file.

## ADR note (ADR-445)

**A file's staff are `loan_teams`; its correspondents are `loan_file_participants`.** They are
different things: a participant is an address that may write to the file (LP-805); a team member is a
user who works it. The internal LO is the source of truth when present and is copied into the text
fields; the text fields are the source of truth when there is none. Team membership decides who sees a
file only when the company turns `restrict_loans_to_team` on.

## Result

**Part 1: built**
- Migration `14e94a531fce` on `6316da7fe522`: `loan_teams` as the schema section (CHECK on
  `team_role`, partial unique indexes on live rows: one person per slot, one loan officer per file);
  `activity_type` CHECK swapped to all 37 values (`loan_team_changed` added; the 36 taken from the enum
  at runtime; `tests/test_activity_type_migrations.py` green before and after); the backfill (a file's
  FILE_CREATED actor, if active, not deleted, in the file's company and holding PROCESSOR, joins as
  processor, added by the system); `readonly.loan_teams` with every column. Model `LoanTeamMember`;
  `LoanFile.team` (live rows, view-only), eager-loaded by `get_loan_file` and `list_loan_files`.
- `app/services/loan_teams.py`: `can_change_team`, eligibility (`NotEligible`, 422, naming the missing
  role), `set_loan_officer` (replaces; write-through of name and email; clearing blanks only text that
  still matches that user; re-seeds participants through `inbound_participants.seed_participants`),
  `add_processor` (no-op if already there), `remove_member` (removing the LO is clearing the slot),
  `on_loan_file_created` (called on the manual and MISMO create paths), `reassign_user_loans`
  (`users.manage`; target checked for every slot before anything moves; one `loans_reassigned` audit
  row; one timeline entry per file). Every change writes one `LOAN_TEAM_CHANGED` entry. Concurrent
  writes to one slot are caught in a SAVEPOINT (409 "Someone else just changed this team").
- Text-field guard in `services/loan_files.update_loan_file`: a CHANGED `loan_officer_name` / `_email`
  while an internal LO is set is 422 "Change the loan officer on the Team card"; re-sending the same
  value with a form is not a change.
- `assignee` (`me` / `unassigned` / user id) in `list_loan_files`, `count_loan_files` and
  `SavedViewFilters` together (docstring updated); the saved-view count resolves `me` per viewer.
- API: `/loan-files/{id}/team` (GET with `can_change`, PUT `/loan-officer`, POST `/members`, DELETE
  `/members/{member_id}`); `GET /users/assignable` (any signed-in user, a separate router mounted
  before `/users/{user_id}`); `POST /users/{id}/reassign-loans`; list and detail carry `team`, and
  `loan_officer_display` with `external`; People rows carry `file_count`.
- Frontend: Team card on the overview (mockup 13), controls only when `can_change`, LO slot hidden
  when nobody holds the Loan officer role and none is set; LO contact read-only with "Filled from the
  loan officer's account" on the overview and on intake for a loan officer creating a file; pipeline
  "Assigned to" select, Loan officer (with "(external)") and Processors ("You") columns, "My files" and
  "Unassigned" built-in views, `assignee` in the URL; deactivate dialog's file section (move to someone,
  "N files now, M after", or leave), reassign then deactivate; People Files column.
- Tests: backend 22 API tests and a migration test (every rule allowed and refused; eligibility 422s;
  write-through, the manual-text exception, participants via `is_participant`; text PATCH 422 / 200;
  creator joins on create and MISMO import by role, nobody for an admin; `assignee` with status and
  search, in a saved view and its per-viewer count; one activity per change with its summary and
  detail; reassign moves every row, audits once, refuses an ineligible target, is tenant-scoped and
  Admin-only; 403/200 by role; one LO under a staged concurrent PUT; backfill: active processor yes,
  inactive / deleted / admin / no FILE_CREATED no). Frontend: Team card read-only and editable, LO slot
  hidden, change LO, add and remove processor, a refusal; LoanEditor read-only and free-text; the list
  query's `assignee`; columns internal / external / "You"; built-in views; the deactivate file section
  only with files, reassign before deactivate, leave; Files column.
- Mutations, each caught: 12 backend (the own-files scope, the role check, write-through, the
  manual-text exception, the participants re-seed, the text guard, the MISMO creator join, the
  unassigned filter, the per-viewer `me`, the reassign role check, the concurrency catch, the
  backfill's active check) and 8 frontend.
- Backend: 10093 passed; ruff, mypy strict clean. Frontend: 2627 passed (218 files); tsc, biome clean.

**Part 2: survey only** (`docs/tickets/LP-MB-Admin-05-survey.md`, read from `app/api` and `app/tasks`):
A (through `ScopedLoanFile`) 64 routes, B (`get_loan_file` / `list_loan_files` / `count_loan_files`,
incl. the conditions router's own `ScopedLoanFileById`) 69, C (child id, token or company-wide query)
68, D (background jobs) 16: 217, plus 6 routes this ticket adds (addendum): 223. **The ticket's "98
uses, one fix covers them" is wrong**: 64 routes use `ScopedLoanFile` and 29 more use
`ScopedLoanFileById`, which calls `get_loan_file` itself, so a fix only in `get_scoped_loan_file` would
miss them (measured by an AST count, matching the survey). Riskiest group C: the inbound queue (lists
mail on other teams' files), the 13 `/documents/{id}` routes (download by id), the 24
`/conditions/{id}` and 15 `/condition-rounds/{id}` routes, reminders and saved-view counts. Also: the
processor-copy job emails a file's mail to its last sender, who may have left the team. No
enforcement code was written and `restrict_loans_to_team` was not touched.

**Assumptions and deviations**
- WHO MAY CHANGE A TEAM. The brief's rule ("`loan.team.change` OR the actor is the file's LO") would let
  every loan officer change every file, because the matrix gives LOAN_OFFICER that key ("own files").
  It is encoded instead as data in `core/permissions.py` (`OWN_FILES_ONLY`) with one pure function,
  `may_change_team`: Admin anywhere, the LO on their own file. This also makes the brief's own test
  (LO 403 on another's file) pass.
- Eligibility compares roles (LOAN_OFFICER / PROCESSOR) in the team service: it is who may HOLD a slot,
  not an authorization decision.
- A loan officer creating a file becomes its LO, and their account overwrites any typed LO text.
- `GET /users/assignable` returns roles and a file count, as asked; the count is company-wide.
- Saved views store `assignee`; two existing saved-view tests now expect `"assignee": None` in the
  stored filters.
- The deactivate dialog's picker offers loan officers when the person holds the Loan officer role,
  else processors; the server still checks every slot and its refusal is shown.
- A concurrent second LO assignment is a 409, not silently last-write-wins.

**Deferred**
- Part 2 enforcement (gated on reviewing the survey), auto-assignment, notifications, the assistant
  slot in the UI, a team filter in saved-view creation UI (no UI creates saved views yet).
