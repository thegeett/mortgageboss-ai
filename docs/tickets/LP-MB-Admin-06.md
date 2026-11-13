# LP-MB-Admin-06 — Restrict loan files to their team (loan teams, Part 2)

Admin and roles, ticket 6. **Status: groomed, not built.** Needs LP-MB-Admin-05 Part 1 (built) and its
survey, `LP-MB-Admin-05-survey.md`, which is this ticket's door list. Build before the LOS track adds
routes: every route written after this ticket is written against the gate; every one written before it
is a door to go back and check.

## What and why

Part 1 gave each file a team. Part 2 turns the team into a lock: when a company turns on
`restrict_loans_to_team`, a loan officer or processor can see a file only if they are on its team. Admins
(`loan.view_all`) and anyone an admin marked `sees_all_loans` still see everything. To everyone else a
file they are not on does not exist: absent from lists and counts, 404 by id or by any child's id, the
same 404 as another company's file.

Off by default; existing companies see no change. It is for broker shops, where one loan officer must not
see another's borrowers, and the LOS track brings those.

## The one design decision (ADR-446)

**Visibility is a type, not a flag.** Today every file gate takes a bare `company_id: UUID`
(`get_loan_file`, `list_loan_files`, `count_loan_files`, `get_document_for_company`, the four
`get_stated_*_for_company`, `get_scoped_round`, `get_scoped_condition`, `list_triage_queue`,
`reminders._open_files`). Adding an optional team check beside the company id leaves the next route free
to pass only the id. So instead:

```python
@dataclass(frozen=True)
class FileScope:
    company_id: UUID
    restricted_to_user_id: UUID | None   # None = sees every file in the company

    @classmethod
    def for_actor(cls, actor: Actor) -> "FileScope": ...
```

`for_actor` returns `restricted_to_user_id=None` when the company setting is off, or the actor holds
`loan.view_all`, or `actor.user.sees_all_loans`; otherwise the actor's own id. One helper,
`scope_files(stmt, FileScope)` in `models/helpers.py` next to `scope_to_company`, applies the company
filter, `only_active`, and when restricted `LoanFile.id.in_(select(LoanTeamMember.loan_file_id).where(
user_id == …, deleted_at.is_(None)))`. The filter is IN THE QUERY (the conditions router's docstrings say
why: a row that was fetched and then refused is a row some later code touches before the check).

Every gate above changes its signature from `company_id: UUID` to `scope: FileScope`. That is the point:
a caller that still passes a UUID fails mypy, and the survey's "signature change at every caller" is the
mechanism that finds every door rather than a cost to avoid. `CurrentScope = Annotated[FileScope,
Depends(get_current_scope)]` is the dependency routes declare; `Actor` gains `.scope` so services that
already take an actor need nothing new.

Background jobs have no actor. They take `FileScope(company_id, None)` explicitly, spelled
`FileScope.system(company_id)`, so a grep for `.system(` lists every unrestricted read.

## Scope

Enforcement points, from the survey, in this order. Each is one change; the per-route test (below) is
what proves it covered its routes.

| # | Point | Routes covered | Change |
|---|---|---|---|
| 1 | `services/loan_files._scoped` | A 68 (via `get_scoped_loan_file`), B2, B3, B4, B5, `list_loan_files`, `count_loan_files`, saved-view counts (C5) | takes `FileScope`; `get_scoped_loan_file` takes `CurrentScope` |
| 2 | `api/conditions.get_scoped_loan_file_by_id` | B1 29 | delegates to the same lookup with `CurrentScope` |
| 3 | `api/conditions.get_scoped_round` | C1 15 | join to `LoanFile` through `scope_files` |
| 4 | `api/conditions.get_scoped_condition` | C2 24 | same |
| 5 | `services/documents.get_document_for_company` → `get_document` | C3 13 + dev C6 | `scope_files` on its existing join |
| 6 | the four `services/stated_financials.get_stated_*_for_company` | C4 8 | same |
| 7 | `services/inbound_triage.list_triage_queue` | C5 inbox | rows WITH a `loan_file_id` filtered by scope; rows with none stay (ADR-421) |
| 8 | `services/inbound_triage.move_unrouted_message` | C5 move | target file through scope |
| 9 | `services/reminders._open_files` | C5 reminders | `scope_files` |
| 10 | `api/loan_files` create and MISMO import | B2 create | Part 1 already calls `on_loan_file_created` before the re-read (verified: `api/loan_files.py:116, 180`). The hole is a creator who gets NO slot: a loan officer who names another loan officer on intake (review fix 6 keeps the typed LO) and holds no PROCESSOR role would 404 on the file they just made. Under the setting, a creator who would land on no slot is refused at create with 422 "You would not be able to see this file. Leave the loan officer blank to be its loan officer, or ask an admin to create it." An admin creator is unrestricted and needs no slot. See open question 4. |
| 11 | `services/processor_copy.copy_recipient` | D copy_to_processor | when the file's company has the setting on, the copy goes to the most recent sender who is STILL on the team; nobody on the team → no copy, one log line |
| 12 | `api/users.assignable` counts, `api/overlay_admin` blast radius | C addendum, C5 | unchanged, documented: counts reveal a number not a file; blast radius is `overlays.manage`, admin-only |

Frontend: one confirm line on the Team card (Decided, 1). Otherwise nothing: a restricted user's pipeline simply has fewer rows, "All files" means "all I
can see", and a 404 on a deep link shows the existing not-found state. One copy change: the overview's
setting hint already says what the switch does.

Dev seed: `seed_dev_data` gets a second company with the setting on, two loan officers each with a file,
and one processor on one of them, so the behaviour can be seen locally.

## Out of scope

- The assistant slot, auto-assignment, notifications (still Part 1's deferrals).
- Per-file sharing ("let this person see this one file" without a team slot): a processor slot is that.
- Hiding a file's existence in the audit log or the company timeline from admins: admins see all.
- Borrower-side visibility: the portal's participant gate is its own thing.
- `GET /users/assignable` file counts (a number, not a file).

## Schema changes

None. The setting (`companies.settings.restrict_loans_to_team`, LP-MB-Admin-02), `users.sees_all_loans`
(03) and `loan_teams` (05) exist. `loan_teams.user_id` already has a plain index (`index=True` on the
column), which serves the `IN (select loan_file_id … where user_id = ?)` predicate; no new index.

## API

No new endpoints. Behaviour change under the setting: lists shrink, counts shrink, ids 404. Each route
keeps its EXISTING not-found body ("Loan file not found", "Document not found", "Condition not found",
…): a restricted row must be indistinguishable from a missing one on that route, and a different sentence
would be the tell. No route gains a new message.

## Tests

- `FileScope.for_actor`: the setting off → unrestricted; on → restricted unless `loan.view_all` or
  `sees_all_loans`; a user with no roles → restricted (sees nothing).
- `scope_files` as SQL: restricted scope returns only files with a live team row for that user; a
  soft-deleted team row does not count; unrestricted returns the company's files.
- **The per-route test, the ticket's real deliverable.** One parametrised test over EVERY route in the
  survey's groups A, B and C (223 minus the excluded), generated from the survey table checked into
  `tests/api/file_doors.py` as data: method, path template, and a `fixture` kind from a closed set of
  about a dozen (`file`, `document`, `condition`, `round`, `draft`, `stated_liability`, `stated_asset`,
  `stated_income`, `stated_employer`, `message`, `needs_item`, `finding`, `upload_link`, `reminder`),
  each with one factory in `tests/api/file_door_fixtures.py` that builds a file on company X with a team
  of exactly one processor and the child row the route needs, and returns the path substitutions. A
  body-taking POST/PUT/PATCH is sent with the minimal valid body the data file names, or `{}` where the
  404 fires before validation (verify per route; a 422 is a failure of the test, not a pass).
  For each route, with the setting on: a processor not on the file's team → 404 (or an empty list / zero
  count for the list and count routes), and nothing written; a processor on the team → not 404; an admin
  → not 404; a `sees_all_loans` processor → not 404. With the setting off: the non-member → not 404. A
  route in the survey that the data file does not cover fails the suite (the two lists are compared), so
  a new route cannot be added without being classified.
- Creator: a loan officer creates a file under the setting and can open it; an admin without a slot
  creates one and can open it.
- Inbox: an unrouted message stays visible to a restricted user; a routed one on another team's file
  does not; `move` to a file they are not on → 404.
- Reminders: only the user's files' nudges.
- Saved-view counts: "All files" count for a restricted user equals their visible files.
- Processor copy: a sender who left the team gets no copy under the setting; the same message copies
  with the setting off.
- The whole existing suite with the setting off: unchanged (it is the default, so this is the normal run).
- mypy: a gate called with a bare UUID is a type error (no runtime test needed; it is the design).

## Decided (2026-11-13)

1. **An LO who hands off their own file** loses it on the next request. The Team card shows a one-line
   confirm, only when the person changing the loan officer is removing themselves AND is restricted:
   "You will no longer see this file." The card decides from `can_change`, the current LO, and a new
   `restricted: bool` on `UserPublic` (`FileScope.for_actor(actor).restricted_to_user_id is not None`),
   so the API needs no new endpoint. This is the ticket's one frontend change.
2. **"My files" vs "All files" for a `sees_all_loans` processor**: My files = files they are on; All
   files = every file in the company.
3. **Names across files**: an activity actor keeps their name after leaving the team; an upload-link
   uploader's name shows to the team. The build checks nothing else names a person across files.
4. **A creator who would get no slot** is refused at create with the 422 in point 10. Not added as a
   processor regardless of role.
5. **Scope is computed once per request, at the start**, before any user change in that request
   (LP-MB-Admin-03's `_locked` re-read unloads `actor.user.company`). An admin who flips the setting
   sees the effect on their next request.

## ADR note (ADR-446)

**File visibility is carried by a scope type, not a flag.** `FileScope` replaces `company_id` at every
loan-file gate; `scope_files` is the one place the team predicate is written; the restricted/unrestricted
decision is made once per request in `FileScope.for_actor` from the company setting, `loan.view_all`
and `sees_all_loans`. Background jobs declare `FileScope.system(...)`. Extends ADR-041/043 (tenant
scoping) and ADR-443 (one function decides the company): the same object now decides the company and
the visibility, and a caller cannot have one without the other.

## Result

**Built**
- `app/core/file_scope.py`: `FileScope` (frozen; `company_id`, `restricted_to_user_id`), `.restricted`,
  `FileScope.for_actor` (unrestricted when the setting is off, or `loan.view_all`, or
  `sees_all_loans`; otherwise the actor's own id), `FileScope.system(company_id)`, and
  `FileScope.for_user(user)` (the same decision from a `User`, for `UserPublic`). `Actor.scope` is set
  when `get_current_actor` builds the actor, at the start of the request; `CurrentScope` is the route
  dependency. `UserPublic.restricted`.
- `models/helpers.scope_files(stmt, scope)`: `scope_to_company` + `only_active(LoanFile)` + the live
  `loan_teams` sub-select when restricted. In the query everywhere; child gates join `LoanFile` and
  apply the same helper.
- Gates moved from `company_id` to `FileScope`, with no `company_id` overload left:
  `services/loan_files._scoped`, `get_loan_file`, `list_loan_files`, `count_loan_files`;
  `get_scoped_loan_file` (`CurrentScope`); `conditions.get_scoped_loan_file_by_id`,
  `get_scoped_round`, `get_scoped_condition`; `services/documents.get_document` (renamed from
  `get_document_for_company`); `stated_financials.get_stated_{liability,asset,income,employer}_scoped`;
  `inbound_triage.list_triage_queue` (a message on a file only if the file is in scope; a message on
  no file unchanged, ADR-421) and `move_unrouted_message` (the target through the scope);
  `reminders._open_files` / `build_suggestions`. Every route passes `CurrentScope` or `actor.scope`.
  Eight API files no longer read `current_user.company_id`, so LP-MB-Admin-02's allowlist went from
  18 to 10.
- `processor_copy.copy_recipient`: with the file's company setting on, the newest Send approver who
  still has a live team row; none → `None` and one `processor_copy_no_team_sender` line with the file
  id only.
- Create path: `POST /loan-files` and `POST /loan-files/import-mismo` create inside a SAVEPOINT and,
  after `on_loan_file_created`, refuse a restricted creator with no live team row:
  `CreatorWouldNotSeeFile` (a `UserRuleError`, 422, the ticket's sentence). Nothing is left behind.
- 404 bodies: every `detail=` string in `app/api` and `app/services` was compared before and after
  (86 strings); none changed.
- Frontend: `User.restricted` (optional, so an older backend reads as not restricted). The Team card
  asks "You will no longer see this file." when a restricted user who is the file's loan officer picks
  someone else or clears the slot, and goes to `/dashboard` after the change. Nothing else changed.
- Dev seed: Harbor Mortgage Brokers (setting on), two loan officers with a file each, a processor on
  Lena's file, a sees-all processor; logins in `seed_dev_data`'s docstring and its summary, cleared by
  `--reset`.

**The door test**
- `tests/api/file_doors.py`: 200 doors (A 68, B 67, C 65) and 59 exemptions with reasons, together
  every one of the 259 routes in `app/api`. `test_file_doors_guard.py` fails if a route in `app/api`
  or a route the survey names is in neither list, if an entry is stale, or if group A's per-router
  counts differ from the survey's.
- `test_file_doors.py` sends every door as five callers (1000 cases), each on its own fixture: the
  non-member gets exactly what a random id gets (status and body) or an empty list / zero count, and
  `pg_stat_xact_user_tables` shows no row inserted, updated or deleted; the member, an admin, a
  sees-all processor, and the non-member with the setting off get neither 404 nor 422 nor a server
  error, and the list doors include the file.
- Fixture kinds: the ticket's set plus `borrower`, `versioned_document`, `condition_item`,
  `evidence`, `package`, `outbound_draft`, `snapshot_finding`, `attachment`, `participant`,
  `dti_line`, `team_member`, `unrouted_message`, `routed_message`, `saved_view`, `received_need`,
  `property`.

**Counts covered versus the survey**
| Group | Survey | Doors | Exempt (reason) |
|---|---|---|---|
| A | 64 + 4 addendum = 68 | 68 | 0 |
| B | 69 | 67 | 2: the two create routes (no file to hide; the create-path tests) |
| C | 68 + 2 addendum = 70 | 65 | 5: overlay blast radius (`overlays.manage`), `GET /users/assignable` and `POST /users/{id}/reassign-loans` (point 12), the two upload-token routes (the token is the credential) |
| D | 16 tasks | n/a | not routes; the one that delivers mail to a person is point 11 |

**Verification**
- Backend, run 1 (everything but the door test; the setting off everywhere it is not set by a new
  test): 10129 passed, 12 skipped, 1 xfailed: the previous 10101 plus the 28 new non-door tests, so
  the existing suite is unchanged. Run 2 (with the door test): 11129 passed, the same plus 1000.
  ruff and mypy strict (`app/`) clean; pre-commit clean on the 46 changed files.
- Frontend: 2637 passed (5 new Team card tests); `tsc --noEmit` and Biome clean.
- Mutations, each caught by its tests: `scope_files` without the team predicate; `for_actor`
  ignoring `loan.view_all`, `sees_all_loans`, or the setting; `get_document`, `get_scoped_round`,
  `get_scoped_condition`, `get_scoped_loan_file_by_id` and the stated-liability lookup each reverted
  to company-only; the Inbox listing every routed message; move resolving its target company-wide;
  reminders over every file; saved-view counts company-wide; no creator refusal; the refusal check
  removed from the create path; the copy ignoring the team; `restricted` always false; a door
  removed from the list (18 backend). Frontend: no confirm, no navigation, ignoring `restricted`,
  ignoring who the loan officer is (4).

**Classification the build disagreed with**
- None of the survey's routes moved group. Two refinements: the two create routes in B2 are not
  doors (there is no file to hide before it exists; the creator rule is their test), and
  `POST /dev/documents/{id}/extract-text-layer` is a door in its own right (the dev router is mounted
  in tests), not only "covered by C3".

**Behaviour changes with the setting OFF** (the existing suite is unchanged by them)
- A condition, a round, or a stated item on a soft-deleted file is now a 404 (the gates filter the
  live file through `scope_files`; before, they filtered only the row's own company).
- The Inbox no longer lists a routed message whose file was deleted.

**Found by the door test, not fixed (outside this ticket)**
- `GET /documents/{id}/versions` on a document never replaced answers 500 (`extractions` not loaded
  for the standalone branch of `get_version_group_documents`). The documents drawer asks only when
  `version_count > 1`, so only a direct API call reaches it; the door uses a versioned document.
- `POST /needs/{id}/confirm-coverage` on a PENDING need answers 500 (`InvalidNeedTransition` is not
  mapped). The door uses a RECEIVED need, the state the button is shown in.
- `POST /messages/{id}/follow-up/stop` on a message whose follow-up was never on answers 500 (the
  `follow_up_time_set` CHECK). The door uses a message with its follow-up on.
- `POST /conditions/{id}/reading/confirm` on a condition with no reading answers 500 (`type_id`
  missing). Every imported condition has a reading; the door's condition has one.

**Assumptions**
- `Actor.scope` is a `field(init=False)` set in `__post_init__`, so the scope exists exactly when the
  actor does; `test_authorization_guards`' bare `Actor` was given a company with default settings.
- No background job calls a gate (each reads its file by id), so `FileScope.system` has no app call
  site today; tests use it. `processor_copy` reads the setting from the file's company, since a job
  has no actor.
- On a refused MISMO import, the raw bytes already written to storage stay unreferenced, as on the
  existing `MismoImportError` path.
- `_open_files` with a named file now re-reads it through `scope_files` (one query) instead of
  comparing its company in Python.
- Names across files (Decided 3): the routes that return a user's name are file-scoped (follow-ups,
  condition events, the team) or admin-only (invites, People, audit), plus `GET /users/assignable`
  (names and counts, by decision). Nothing else names a person across files.

**Deferred**
- Per-file sharing; the assistant slot, auto-assignment and notifications (Part 1's deferrals).
- The four 500s above.
- The remaining 10 files on the `current_user.company_id` allowlist.
