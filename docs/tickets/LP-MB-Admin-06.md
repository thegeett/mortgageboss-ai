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
