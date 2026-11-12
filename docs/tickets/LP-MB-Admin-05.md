# LP-MB-Admin-05 — Loan teams, and the loan officer as a user

Admin and roles, ticket 5 of 5. **Status: planned, not built.** Needs LP-MB-Admin-02, LP-MB-Admin-03.

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
