# Phase 4.5 Stage 2 — survey before the first ticket

- **Ticket:** the survey §10 of [`../phases/phase4.5-stage2-tickets.md`](../phases/phase4.5-stage2-tickets.md) asks for
- **Date:** 2026-09-26
- **Branch:** `phase4.5-conditions`, HEAD `98a97b4d`, working tree clean at the start
- **Spec:** `phase4.5-stage2-tickets.md` §1, §2, §10 (it wins over `phase4.5-build-plan.md` §4)
- **Screens:** none of its own. The Stage 2 pack (`docs/design/phase4.5-conditions/stage2/`) was read
  end to end before this was written, and the numbers on S2-01, S2-02, S2-06, S2-08 and S2-11 are
  checked against the fixtures below.

**Nothing in this file is code.** It exists so that LP-911 does not start by assuming a fact that
stopped being true, and so the four places where the spec and the tree disagree are decided here
rather than discovered in the middle of a migration.

## 0. Is the ground free?

| Question | Answer |
|---|---|
| Is **ADR-408** the next free number? | **Yes.** `decisions.md` runs to ADR-407 (`## ADR-407`, line 16334, Accepted under LP-903). Nothing cites 408. |
| Are **LP-911 … LP-917** free? | **Yes.** No `docs/tickets/LP-91[1-7].md` exists. The only mentions anywhere are the three planning documents (`phase4.5-build-plan.md`, the Stage 2 tickets file, the Stage 2 design README) — that is, they are *planned* and not *built*. |
| Is anything near them taken? | **Yes, and it is worth knowing.** `docs/tickets/LP-930.md` exists (structured reader warnings, raised by LP-909 §5). LP-918 is spoken for by the condition taxonomy (`uwm.yaml`'s header and `phase4.5-progress.md` both name it), and LP-921/922 by Stage 3's emails. So the free block is exactly 911-917 minus 914, which is what this stage uses. |
| Is **LP-914** in scope? | **No — deferred by D1**, kept in the plan and moved after Stage 3. Not built here. |
| Migration head | `b6d1e93f57ac` (`uv run alembic heads` → single head). LP-912's migration revises this. |

## 1. The base is one commit further on than the spec's, and Stage 1 is not finished

The spec's §2 facts were read at `e5a481bf`. HEAD is `98a97b4d`, and the five commits since Stage 1's
§5 are `30860613`, `fef767d5`, `882f792c`, `bb01c16d`, `98a97b4d` — the Stage 2 tickets file, a Stage 2
staging commit, an emoji sweep, the conditions routes accepting a display id, and a
`terraform.tfvars` edit. None of them changes the condition model or the import.

**§10 asks that Stage 1 part 5 be finished first, and it is not.** `phase4.5-progress.md` says so in
its own words: all 13 visual checks are done and §8 steps 1-7 pass through the API, but **CI is not
known to have run** (both workflows trigger only on `push`/`pull_request` to `main`, so a push of this
branch runs nothing), §8 step 8 needs the product owner's real sheets, and one STOP AND ASK is open
(S1-01's forward card offering a door the `receiving` switch keeps shut). None of those blocks Stage
2 — they are about a PR to `main` and about the product owner's machine — and per the standing
instruction this survey records the gap and continues rather than stopping.

**Local checks are therefore the only gate for this whole stage.** The measured limits from LP-909 §5
still hold on this machine: two `test_page_ocr` tests need tesseract (absent) and
`test_cli_refuses_unpaced_bedrock` fails on this `.env`'s model tiers. Three failures unrelated to
conditions; anything else is mine.

## 2. Every fact in §2, checked against the tree

Read from the code, not from the spec. "✓" means verified at the line named.

| Spec's claim | Verdict |
|---|---|
| `Condition.prep_status`: `to_do · waiting · review · ready · with_underwriter` | ✓ `models/condition.py:89-96` (`ConditionPrepStatus`), default `TO_DO`. |
| all `prep_status` rows are `to_do` | ✓ **by construction rather than by query.** No writer exists: `condition_import.py:402` says "`prep_status` and `lender_status` take their defaults and are never moved in Stage 1", `_update_seen_again` (`:411`) states the same, and no other module assigns either. Not checked against a database — there is no Stage 2 database to check and the claim is about what the code can do. |
| `Condition.lender_status`: `open · pending_review · cleared · not_cleared · waived · superseded` | ✓ `models/condition.py:99-107`, default `OPEN`. |
| `owner_hint` + `owner_hint_source` (`prefix · bucket · code_map · none`) | ✓ `models/condition.py:63-86`. `manual` is **absent**, as A2/LP-912 assume — see difference **D-4**, which is not free. |
| `bucket_heading`, `bucket_kind`, `info_only`, `origin` (`sheet · manual`) | ✓ `models/condition.py:161-186`, `:110-114`, `:197`. |
| `first_round_id`, `last_seen_round_id`, `underwriter_notes` (dated), `text_fingerprint` | ✓ `models/condition.py:143-148`, `:171-177`. `underwriter_notes` is `[{date, text, first_seen_round_id}]`. |
| `round_numbers` per condition, from its events | ✓ `api/conditions.py:400-420` via `services/conditions.py::appearances_for_file`, derived from `CONDITION_CREATED`/`CONDITION_SEEN_AGAIN` (`APPEARED_ON`, `:40`). One query per file, not per row. |
| `condition_events` append-only; **kinds up to `condition_edited`** | ✓ append-only by shape (`Base, UUIDMixin` only) and guarded by `tests/models/test_condition_events_append_only.py`. **The count is 11, not 10:** `ROUND_REPARSE_REQUESTED` was added by LP-909 §3 with its own constraint swap (`b6d1e93f57ac`). The spec's phrase still reads true because `condition_edited` is last in enum order, but anyone counting members from §2 will be one short. |
| `possible_match` in `CONDITION_CREATED` when the code matched and the wording did not | ✓ `services/condition_import.py:638-642`, and `_match` (`:157-194`) returns it only for same-code / different-fingerprint. `_existing_conditions` is ordered oldest-first so the id is the *original* (`:114-129`) — and that ordering is protected by argument, not by a test (LP-909 recorded the un-caught mutation). LP-915's "Reworded?" rule depends on both. |
| Round `completeness` (`full · partial`), `header`, `expiry_dates`, `date_printed` | ✓ `models/condition_round.py:149-172`. `expiry_dates` is explicitly **not** NPI; `header` is. |
| Round strip, imported list, round-details sheet, `R1 R2` chips | ✓ `frontend/components/file/conditions/` — `round-strip.tsx`, `imported-view.tsx` + `imported-conditions.tsx`, `round-details-sheet.tsx`, `owner-cell.tsx`, and the tab at `app/(protected)/loan-files/[id]/conditions/page.tsx`. LP-913 replaces `ImportedView`. |
| `NeedsItemOrigin.CONDITION`, reserved for Stage 3 | ✓ `models/needs_item.py:91`, commented "generated from a lender condition (Phase 4.5)". Untouched by Stage 2. |
| "Nothing in Stage 2 re-reads a sheet" | ✓ nothing in the plan calls a reader; every Stage 2 result comes from `conditions`, `condition_rounds` and `condition_events`. |

**Conclusion: §2 is accurate.** One count is stale (11 event kinds) and one absence is load-bearing in
a way the spec does not flag (`manual`, D-4). Everything else is where it says it is.

## 3. Differences from the spec, each decided here

### D-1 · LP-911 needs no migration, because two of its four readonly columns already exist

LP-911's rules say: "Add `prep_status`, `lender_status`, `effective_owner` and the verdict's
`source_kind`/`source_date` to `readonly.conditions`".

**`prep_status` and `lender_status` are already exposed.** LP-904's `_CONDITIONS_VIEW`
(`d1f4b8c25e93`, lines 149-158) selects `text_fingerprint, owner_hint, owner_hint_source, info_only,
canonical_type_id, prep_status, lender_status, origin` and
`jsonb_array_length(underwriter_notes) AS underwriter_note_count`. The wording and the notes are
dropped, per ADR-405.

The other two — `effective_owner` and the verdict scalars — are derived from columns that **do not
exist until LP-912 creates them** (`owner_override`, `verdict`). A view cannot select them earlier.

**Decision: LP-911 writes no migration at all.** The `readonly.conditions` rebuild moves into LP-912's
single migration, where the columns it projects are created in the same file. LP-911 is a pure read
ticket, which is also what its own "Out of scope: anything that writes" implies.

Two constraints on that rebuild, both from the existing guards:

- The new `CREATE VIEW readonly.conditions` must sit **above** `def downgrade(` in the migration.
  `tests/test_readonly_query.py::_later_view_redefinitions` reads every such statement above that line
  as the live definition, and LP-904's own migration carries the comment saying so (`:495`).
- `tests/test_condition_readonly_npi.py` asserts both halves: no NPI column exposed
  (`verbatim_text`, `underwriter_notes`) **and** `REQUIRED_OUTPUTS` still present
  (`text_fingerprint`, `bucket_kind`, `lender_code`, `underwriter_note_count`). `prep_note` and
  `verdict.note` are NPI and must stay out; the NPI set in that file will need the two new NPI
  columns added to it, or it will pass while saying nothing about them.
- `test_readonly_query.py` requires **every model column** to be exposed or listed in `EXCLUDED`. So
  each column LP-912 adds (`waiting_on`, `prep_note`, `sent_at`, `prep_status_changed_at`,
  `lender_status_changed_at`, `verdict`, `owner_override`, `superseded_by_id`) and LP-915's
  `condition_rounds.comparison` must be one or the other, deliberately.

### D-2 · Stage 2 adds a THIRD router shape, and the gating guard walks the two that exist

LP-911's `GET /api/conditions/{condition_id}` and `…/events`, and all five of LP-912's write routes
(`POST /api/conditions/{id}/prep-status`, `/verdict`, `/reopen`, `PUT /owner`), carry **no loan file in
the path**. Neither existing gate fits: `ScopedLoanFileById` has no file id to scope, and
`ScopedRound` scopes a round, not a condition. A new `get_scoped_condition` + `ScopedCondition` is
required, filtering `company_id` **inside the statement** the way `get_scoped_round` does
(`api/conditions.py:187-213`) — `Condition.company_id` is on the row precisely for this
(`models/condition.py:131-135`).

**And `tests/api/test_condition_route_gating.py` will not see it.** `_gate_map()` (`:54-73`) names four
routers by hand: `conditions_router`, `condition_rounds_router`, `inbound_router`,
`inbound_company_router`. A new router is simply absent from the walk, so **every new Stage 2 route
would be ungated and the whole suite green** — which is, word for word, the failure that file was
written for: *"the fourth route someone adds in Stage 2 is the one that ships open, and every existing
refusal test passes, because they test the routes that exist."*

**Decision: the first ticket that adds a route on a new router adds it to `_gate_map()` in the same
commit,** with its own accepted-gate set, and proves it the way that file proves everything else — the
positive control at `:207` plus a per-route refusal test (404, never 403). LP-911 owns this because
LP-911 adds the first such route.

### D-3 · `ConditionPublic` carries no `updated_at`, so LP-912's `stale` refusal would be unreachable

LP-912 specifies optimistic concurrency on `updated_at` for all five writes, with the refusal
`stale` → "Someone else changed this condition — reload to see their change."

`Condition` has `TimestampMixin`, so the column exists. **`ConditionPublic` exposes `created_at` and
not `updated_at`** (`schemas/condition.py:412`), and the frontend `Condition` interface matches
(`lib/types/conditions.ts:338`). A client cannot send a value it was never given, so every request
would carry `null`, the check would read "no opinion", and the 409 could never fire.

This is **the same defect LP-909 §4 found and fixed one table over**: `ConditionRoundPublic` carried
only `created_at`, so `ConditionDraftUpdate.expected_updated_at` was always `None` and the two-tabs
409 was unreachable. Its own comment says "EXPOSED SO THE STALE-WRITE GUARD IS REACHABLE AT ALL"
(`:490`).

**Decision: LP-911 adds `updated_at` to `ConditionPublic` and to the TypeScript `Condition`,** so that
LP-912's concurrency has something to compare. A test that a fresh read carries it, and a LP-912 test
that a stale value is refused *and changed nothing*, are the pair that makes it real.

### D-4 · `OwnerHintSource.MANUAL` is a CHECK swap, and NO guard watches that constraint

`OwnerHintSource` is mapped with `str_enum` (`models/condition.py:182`), which per ADR-037 is
**VARCHAR + CHECK**, not a native enum (`models/enums.py:32-58`). LP-904 created
`ck_conditions_ownerhintsource` inline inside `create_table` (`d1f4b8c25e93:337-339`).

So adding `MANUAL` to the enum changes what the code writes and **nothing** about what the database
accepts. And the guard that catches exactly this — `tests/test_activity_type_migrations.py` — watches
only two constraints (`_CASES`, `:58-61`): `ck_activity_logs_activitytype` and
`ck_condition_events_conditioneventkind`. `ck_conditions_ownerhintsource` is not among them, and that
file's own docstring says why that matters: a new enum column with no entry "is invisible to this
test". `conftest` builds the schema with `create_all`, which regenerates the CHECK from the very enum
being changed, so **the full suite would be green and the first owner override on a migrated database
would raise `IntegrityError` on commit.** That is the LP-637 defect, one enum further over, for the
second time in this stage.

**Decision: LP-912's migration swaps `ck_conditions_ownerhintsource` listing all five values, and adds
`("ck_conditions_ownerhintsource", OwnerHintSource)` to `_CASES` in the same commit.** The same applies
to `ck_condition_events_conditioneventkind` for the six new event kinds — that one *is* watched, so it
fails loudly, which is the difference between the two and the argument for widening `_CASES`.

`ConditionPrepStatus` and `ConditionLenderStatus` gain no members (A4 keeps `review` and
`pending_review` in the database and out of the UI), so their constraints are untouched.

### D-5 · LP-916's history needs a new reader, which finally justifies an index LP-909 left open

`events_for_round` filters `condition_id IS NULL` (`services/conditions.py:170`) — deliberately, so a
30-row import does not render thirty lines in a round's history. LP-916 needs the opposite: **one
condition's** events, newest first.

LP-909 left this as a named open question in two places (the route docstring at `api/conditions.py:639`
and `services/conditions.py:139`): `ix_condition_events_condition_occurred` is
`(condition_id, occurred_at)`, "nothing in this codebase asks that question", and "either something
reads it, or it should go in a follow-up migration".

**LP-916 is that reader**, and its ticket file should say so, closing the question rather than leaving
a third copy of it. No migration: the index already exists.

### D-6 · LP-911's Done-when holds only when the file has a lender AND the UWM codes are seeded

"open + waiting on borrower after round 1 returns exactly `7086 6132 6637`" is true — and it is true
*through the code map*, not through anything on the sheet. Verified against `uwm.yaml` and the reader,
for every code on round 1:

| Code | Effective owner | Where it comes from |
|---|---|---|
| `7086`, `6132`, `6637` | **borrower** | `default_owner_hint: borrower`, `owner_hint_source: code_map` |
| `6178` | insurance | code map (this is S2-09's "waiting on Insurance" row) |
| `0132` | broker | code map |
| `1582`, `0006`, `0007` | processor | code map |
| `1947`, `6378` | title | the lender's own `TC:` prefix, `owner_hint_source: prefix` — `readers/uwm.py:509` — which outranks the map |
| `1228` | unknown → **"Not known"** | `default_owner_hint: unknown` (S2-01 must-match) |

The hint is applied by import step 4, and `_apply_code_defaults` only fills it **where the sheet gave
none** (`condition_import.py:336-338`) — so `1947` and `6378` keep `prefix`, which is what S2-01 draws.
But the whole step is **skipped when `round_.lender_id is None`** (`:619`), and it needs
`LenderConditionCode` rows for `(lender, code)`.

**Consequence for every Stage 2 fixture:** the acceptance file must be created with a lender and the
UWM codes loaded, or all eleven conditions come back `unknown` and both the LP-911 assertion and
S2-01/S2-02/S2-09 are unreproducible. `tests/conditions/test_round_import.py:444-489` is the shape for
building `LenderConditionCode` rows in a test; `app/conditions/lender_codes/loader.py` loads the YAML.
Noted in the progress file too: **the LP-910 seed has never run against a database**, so the fixture
must not depend on it having been run.

## 4. The fixtures already say what the spec claims (§7 checked line by line)

Checked against `tests/conditions/fixtures/uwm_round1_2026-08-28.txt` and
`uwm_round2_2026-09-10.txt`. This matters because LP-915's Done-when demands **exact assertions, not
counts**, and a fixture that disagreed would have been found halfway through LP-915.

- **Round 1 carries exactly 11 conditions:** `1228 7086 6132 6637 6178` under "UW - Prior To Final
  Approval (PTD)", `0132` under "Compliance - Prior To Closing (PTD)", and
  `1947 1582 0006 0007 6378` under "Closing (PTF)" — the 5 / 1 / 5 grouping S1-05 and S2-01 draw.
- **Round 2 carries exactly 6:** `1228 1947 1582 0006 0007 6378`.
- **So absent from round 2 = `7086 6132 6637 6178 0132`** — LP-915's "probably cleared" list, exactly,
  and **still open = `1228 1947 1582 0006 0007 6378`**, exactly. Both match the Done-when.
- **Every letter change in LP-915's Done-when is real in the text:** note rate `6.374% → 6.490%`,
  ratios `32.51% / 40.36% → 32.83% / 40.69%`, verified assets and max funds to close
  `$11,062.18 → $41,914.42`, rate lock exp **blank → `09/30/2026`**, UW team `Tigers → Lightning`,
  Close By `10/30/2026 → 11/03/2026`, Asset `10/30/2026 → 11/30/2026`.
- **What did not change**, for S2-06's "a line naming what didn't change": Must Not Close Before
  `09/30/2026` on both, Must Fund By blank on both, verified income `$5,741.32` on both, Appraisal
  `11/23/2026`, Credit `11/10/2026`, Income `11/03/2026`, Insurance `09/30/2027`.
- **S2-01's seven summary numbers are reproducible:** Open 11 · Came back 0 · Cleared 0 · Waived 0 ·
  **Information 0** · Prior to docs open **6** · Prior to funding open **5**. The 6 is the five UW PTD
  rows plus `0132`, whose heading "Compliance - Prior To Closing (PTD)" reads `PRIOR_TO_DOCS` from the
  parenthetical (`BucketKind`'s docstring states that rule). **Information 0** is not luck: the only
  `info_only: true` row in `uwm.yaml` is `0973`, which appears on neither sheet.
- **S2-02's numbers follow** once round 2's five are cleared: Open 6 · Cleared 5 · Prior to docs open
  **1** (`1228` alone) · Prior to funding open **5**.
- **§7.1 needs no new text.** `tests/conditions/uwm_pdf_fixture.py` renders any text fixture as a real
  monospaced PDF, and `fixture_helpers.portal_excerpt()` already slices round 2 as a paste — so both
  paths for round 2 (full PDF, and pasted "just some") exist today.
- **§7.3 does not exist and must be written:** `uwm_round3_2026-09-18.txt`, synthetic, in the same
  column-aligned layout. `fixture_helpers.py`'s docstring is explicit that these files are extracted
  mechanically and that **column positions carry meaning** (the expiry table is matched by column),
  so round 3 must be built to the same columns and its `{SHY}` count stated.

## 5. Decisions taken without the product owner

Each is a **STOP AND ASK** the spec marks, or a contradiction in it, settled with the option that
never clears, removes or changes a condition's status without a person's click.

1. **LP-917's example contradicts its own Done-when.** The goal says "Asset docs expire 11/30/2026 ·
   65 days"; Done-when and S2-11 say the soonest expiry after round 2 is **11/03/2026** with
   "Close by and income docs · 38 days". The fixture settles it: round 2's expiry row is Close By
   `11/03`, Appraisal `11/23`, Asset `11/30`, Credit `11/10`, Income `11/03`, Insurance `09/30/2027`,
   so the soonest is `11/03/2026`, and 09/26 → 11/03 is 38 days. **Decision: build to Done-when and
   S2-11; the goal's example is stale.** (Raised independently by the review session.)
2. **LP-912's named STOP AND ASK — "if Stage 1's import cannot tell a new note from an old one
   reliably (for example, the same note pasted twice)" — is not a stop.** It can:
   `_note_key` is `(date, text)` and ignores `first_seen_round_id` because that field is ours
   (`condition_import.py:202-209`), and `_new_notes` keeps only keys not already present. A note
   pasted twice is therefore **not** new, and a note with the same text under a different date
   correctly **is**. No change needed, and A1 can be wired to the existing decision rather than to a
   new comparison.
3. **An UNDATED new note does not set *Came back*.** A1 says "a new **dated** underwriter note", and a
   verdict requires `source_date`. Undated notes are a real state, not an edge case: LP-909 §5
   measured them on S1-11, where a sheet with no header has no `date_printed` to resolve the year
   against. **Decision: only a new note with a resolvable date sets `lender_status = not_cleared` and
   moves our status; an undated new note keeps Stage 1's behaviour — `CONDITION_NOTE_ADDED`, no status
   change.** This is the option that cannot change a status without a dated verdict behind it, and the
   note is still visible on the row and in the detail sheet either way.
4. **A1 stays wired for partial rounds as well as full**, as the spec says — a note is a statement by
   the lender however the sheet arrived. This never *clears* anything on a partial round, so ADR-404's
   "a partial source may add or update but may never remove or clear" is untouched.
5. **The `readonly.conditions` rebuild moves from LP-911 to LP-912** (D-1), so LP-911 ships no
   migration and no view change lands before the columns it would project exist.

## 6. What each ticket must carry that the spec does not say

Collected so it is not re-derived six times.

- **LP-911:** `ScopedCondition` on a new router, that router added to `_gate_map()` (D-2);
  `updated_at` on `ConditionPublic` and on the TS `Condition` (D-3); no migration (D-1); `q` searches
  `verbatim_text` and **is never logged** — log filter names and counts only (ADR-405, and
  `condition_import.py`'s own log lines are the pattern); a lender + seeded UWM codes in the fixture
  (D-6).
- **LP-912:** ADR-408 first; one migration carrying eight columns, the event-kind swap, the
  `ck_conditions_ownerhintsource` swap **and** its `_CASES` entry (D-4), plus the
  `readonly.conditions` rebuild above `def downgrade(`; every new enum mirrored into
  `frontend/lib/types/conditions.ts` and registered in `_MIRRORED`
  (`tests/test_condition_type_mirror.py:55`), or the TS side silently lacks it; the refusal sentences
  taken verbatim from S2-04 / S2-05 (below); bulk inside `loan_file_needs_lock`, which is **advisory
  and not mutual exclusion** — the lock narrows a window, it does not close it.
- **LP-916:** the new one-condition events reader, and a line in the ticket closing LP-909's open
  question about `ix_condition_events_condition_occurred` (D-5).
- **LP-913:** replaces `ImportedView`; two new `StatusToken` vocabularies in `lib/status.ts`
  (`CONDITION_PREP_STATUS`, `CONDITION_LENDER_STATUS`) typed `Record<Enum, StatusMeta>` so a new
  member breaks the build, with the tones the design README fixes: ours `to_do` neutral / `waiting`
  progress / `ready` verified / `with_underwriter` progress, lender `open` neutral / `not_cleared`
  attention / `cleared` verified / `waived` verified / `superseded` muted. Read through
  `resolveStatus`, never indexed directly — LP-909 fixed that exact bug in `round-reading.tsx`.
- **LP-915:** `condition_rounds.comparison` is a new column and therefore a `readonly` decision (D-1);
  the `possible_match` id the "Reworded?" rule reads is written only for same-code /
  different-fingerprint, and points at the **oldest** such condition.
- **LP-917:** dates from the newest round that has a header or expiry table; 38 days, not 65 (§5.1).

### The exact strings from S2-04 and S2-05

Taken from the HTML, which the README says carries the exact wording:

- Title **"Record the lender's answer"**; subtitle **"For 3 conditions. Only record what the lender
  said — this is what "Cleared" will show and where it came from."**
- The three choices with their one-line meanings: **Cleared** "Lender signed it off" · **Waived**
  "Lender dropped it" · **Came back** "Lender says not satisfied".
- Field labels **"The lender's answer"**, **"Where the lender said it"** (Portal / Email / Phone),
  **"Date the lender said it"**, **"Note (optional)"** with the placeholder
  *"e.g. "Cleared in EASE, condition status screen""*. Button **"Record for 3 conditions"**.
- S2-05: title **"Move 0006 back to To do?"**, the *from → to* tokens, the wording in serif, a
  required reason labelled **"Why? (required)"**, the hint **"Moving back keeps the history. Moving
  forward never needs a reason."**, buttons **"Move back"** / **"Cancel"**. Retitled **"Reopen 0006?"**
  for a reopen.

The UI primitives these need all exist: `components/status-token.tsx` (note: **not** under
`components/ui/`), and `components/ui/` holds `sheet.tsx`, `dialog.tsx`, `empty-state.tsx`,
`card.tsx`, `button.tsx`, `select.tsx`, `searchable-select.tsx`.

## 7. What this survey did not check

Stated plainly, because a survey that reads as exhaustive is worse than one that names its edges.

- **No database was queried.** Every claim above is from source text. "All rows are `to_do`" is
  therefore a claim about what the code can write, not a count (§2).
- **No screen was rendered.** The Stage 2 PNGs were read and their Must-match lists checked against
  the fixtures *numerically*; no pixel comparison was made, and none is claimed. That is each UI
  ticket's "Visual check".
- **CI has not run and will not run on this branch.** Local `ruff`, `mypy`, `pytest`, `biome`, `tsc`
  and `vitest` are the gate for all six tickets.
- **No real lender sheet was involved**, and none may enter the repo (ADR-405).
