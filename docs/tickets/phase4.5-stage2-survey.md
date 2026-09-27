# Phase 4.5 Stage 2 — survey before the first ticket

- **Ticket:** the survey §10 of [`../phases/phase4.5-stage2-tickets.md`](../phases/phase4.5-stage2-tickets.md) asks for
- **Date:** 2026-09-26
- **Branch:** `phase4.5-conditions`, HEAD `98a97b4d`, working tree clean at the start
- **Spec:** `phase4.5-stage2-tickets.md` §1, §2, §10 (it wins over `phase4.5-build-plan.md` §4)
- **Screens:** none of its own. The Stage 2 pack (`docs/design/phase4.5-conditions/stage2/`) was read
  end to end before this was written, and the numbers on S2-01, S2-02, S2-06 and S2-11 are
  checked against the fixtures below. S2-08 is not: it needs round 3, which does not exist yet (§4).

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

**Local checks are therefore the only gate for this whole stage.** LP-909 §5 measured three failures
on this machine that are not about conditions: two `test_page_ocr` tests need tesseract (absent) and
`test_cli_refuses_unpaced_bedrock` fails on this `.env`'s model tiers. This survey ran nothing; the
baseline at `b0dc8c10` was measured by the review and is in the Review section below.

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

**Decision: LP-912's migration swaps `ck_conditions_ownerhintsource` listing all five values.** The
same applies to `ck_condition_events_conditioneventkind` for the **eight** new event kinds (LP-912's six
plus LP-915's `round_compared` and `round_completeness_changed`, which the spec puts in LP-912's single
migration). *(Review: `_CASES` now watches `ck_conditions_ownerhintsource` and every other
condition-family CHECK, and the guard's swap reader was fixed so it can read a migration that swaps
two constraints. LP-912 no longer needs to touch `_CASES`; see Review R3.)*

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

`1228` is **`unknown` with source `code_map`**, not source `none`: `uwm.yaml` gives it
`default_owner_hint: unknown`, and `_apply_code_defaults` records the source whenever the map gives a
hint (measured in review). So "Not known" must be decided by the owner being `unknown`, never by the
source being `none`, or `1228` renders as "Not known · from code map".

**Consequence for every Stage 2 fixture:** the acceptance file must be created with a lender and the
UWM codes loaded, or nine of the eleven conditions come back `unknown` (only `1947` and `6378` keep
`title`, from the prefix, which the reader sets without any map) and both the LP-911 assertion and
S2-01/S2-02/S2-09 are unreproducible.

**Seed through the product's own path, not by hand and not through `load_seed` either** *(refined
while building LP-911; the review agreed)*. `app/scripts/seed_lender_codes.py::seed_lender_codes(db)`
is public and split from its CLI for exactly this — its docstring says "separated from the CLI below so
a test can drive it against a session with no database of its own". So the fixture sets
`canonical_lender_key = "uwm"` on its lender, flushes, and calls it. Three consequences worth stating,
because each is a way the fixture silently goes wrong otherwise:

- `make_lender` does **not** set `canonical_lender_key`, and `_lenders_for_key` matches on it alone. A
  fixture that forgets it seeds nothing, reports the key unclaimed, and yields nine `unknown` owners —
  a failure that reads as a logic bug in the filter rather than as a fixture that did nothing. **The
  fixture asserts the rows landed `SEEDED`** so it fails as itself.
- Rows must be `SEEDED`, not `OBSERVED_UNMAPPED`: `resolved_status` never demotes, and `SEEDED` is what
  makes `unmapped_codes` come back empty on import.
- All 28 shipped rows load, not the eleven on round 1 (measured: 28, one of them `info_only`). A subset
  would be a second hand-maintained list — the LP-910 lesson, whose review had to diff 56 copied rows
  to find three slips — and the extra rows are inert on a file whose sheets never mention them.

It also makes this fixture **the first thing to exercise the LP-910 seed against a database**, which
`phase4.5-progress.md` lists under "Never exercised". `tests/conditions/test_round_import.py:444-489` remains the shape for
building a `LenderConditionCode` row directly when a test wants one specific mapping.
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

### 5.0 Defaults A1 to A7, and D1 to D4: ACCEPTED by the product owner *(R1, corrected in follow-up)*

The spec tells this survey to STOP AND ASK about A1 to A7 before ADR-408 is written. **They have
already been answered.** The product owner's build instruction for Stage 2 states, in as many words,
that "D1-D4 and defaults A1-A7 in §1 of the tickets file are ACCEPTED" and that they are not to be
re-asked. The review recorded them as "pending an answer" (R1) because that instruction is not in the
repository — it reached the builder directly — so this is the more accurate record, not a softer one.

ADR-408 therefore records A1 to A7 as **accepted**, citing this paragraph rather than claiming a
conversation that did not happen in the tickets file.

| # | Default | Status |
|---|---|---|
| A1 | A new dated underwriter note sets *Came back* and moves our status to *To do* | **Accepted as intent.** Its *mechanism* had a defect — see §5.2, which is now decided, not open |
| A2 | The processor can change "who it's waiting on" by hand | Accepted |
| A3 | No "Draft email to borrower" in Stage 2 | Accepted |
| A4 | `review` and `pending_review` stay in the database, never offered | Accepted |
| A5 | Hand-added conditions are never "probably cleared" | Accepted |
| A6 | "Probably cleared" compares against every open condition on the file | Accepted |
| A7 | An imported round can switch from *Just some* to *Full list* | Accepted |

**Accepting A1 did not settle §5.2, and the two must not be confused.** A1 is a statement of intent —
"the lender's own dated note is the lender reopening the condition". R2 found that the *mechanism* A1
would be wired to cannot tell one case apart. Accepting the intent says nothing about which notes
qualify, which is what §5.2 decides.

### 5.1 to 5.5: the spec's contradictions and marked STOP AND ASK points

Each is a **STOP AND ASK** the spec marks, or a contradiction in it, settled with the option that
never clears, removes or changes a condition's status without a person's click.

1. **LP-917's example contradicts its own Done-when.** The goal says "Asset docs expire 11/30/2026 ·
   65 days"; Done-when and S2-11 say the soonest expiry after round 2 is **11/03/2026** with
   "Close by and income docs · 38 days". The fixture settles it: round 2's expiry row is Close By
   `11/03`, Appraisal `11/23`, Asset `11/30`, Credit `11/10`, Income `11/03`, Insurance `09/30/2027`,
   so the soonest is `11/03/2026`, and 09/26 → 11/03 is 38 days. **Decision: build to Done-when and
   S2-11; the goal's example is stale.** (Raised independently by the review session.)
2. **LP-912's named STOP AND ASK — "if Stage 1's import cannot tell a new note from an old one
   reliably (for example, the same note pasted twice)" — is a REAL stop, and it is DECIDED here
   rather than left open.** *(This item first said the mechanism was reliable; review measured that
   wrong, R2, and its correction stands.)* `_note_key` is `(date, text)`, and a note's date is
   resolved from the sheet's `date_printed`. **A paste has no `date_printed`**, so a note first saved
   from a paste is `(None, "Not in Upload")`; when a later PDF carries the same note it is
   `("2026-08-28", "Not in Upload")`, the keys differ, and `_new_notes` calls it new. Attaching the
   PDF to the pasted round does not repair the saved note (`condition_enrich` fills holes and leaves
   matched rows' notes alone). Under A1 as written, the next full PDF round would set *Came back* and
   move our status to *To do* on a note the lender wrote weeks before — on the spec's own acceptance
   path. Measured on `uwm_round1` in `tests/conditions/test_note_identity.py` (a strict xfail).

   **Decision (taken without the product owner, standing instruction: choose the option that never
   changes a status without a person's click). Two parts, and the split is the point:**

   **(i) The safety lives in A1's trigger, not only in `_new_notes`.** A1 fires only when the
   incoming note is evidence the lender *re-issued* something. It is not evidence when the note it
   would be compared against has **no known date**: the two may be the same note seen twice, and
   nothing in the data distinguishes that from a re-issue. So — a new note whose text matches a saved
   note with `date: null` **never sets `not_cleared` and never moves our status**, whatever its own
   date. Two notes with the same text under two *known and different* dates **do** fire A1: that is a
   genuine re-issue and the signal is kept.

   **(ii) The undated saved note has its date filled in place** when a dated note with identical text
   arrives, with **no event written and no status change** — a data repair, not a lender statement.
   This is the review's recommended rule and it is adopted for the *storage* question.

   **Why (i) is stronger than (ii) alone, which is why both are here.** Text-only matching would also
   swallow a *real* re-issue: a lender that prints the identical note text on two dates ("Not in
   Upload" appears twice in the round-1 fixture alone) would have the second occurrence absorbed into
   the first if the first was undated. Part (i) makes the *status* consequence conditional on a known
   date rather than on the merge, so the false *Came back* is impossible **and** the true one survives
   once both dates are known. A missed *Came back* is recoverable — the processor records the lender's
   answer by hand, which is what LP-912's verdict endpoint is for. A false one silently reopens a
   condition and moves work backwards.

   **Amended in the second review (R8 to R10); these three rules replace the matching parts of (i)
   and (ii) above:**

   - **Match on normalised text, not raw text (R8).** The reader keeps whitespace inside a note
     exactly as it arrives (measured: a paste with "Not in  Upload" gives `'Not in  Upload'`), and a
     browser copy of the portal need not space a note the way the PDF does. With raw equality, (i)
     does not recognise the same note and fires a false *Came back*. Both (i) and (ii) compare
     `" ".join(text.lower().split())`, the normalisation `note_stripped` already uses for wording.
   - **An undated saved note has an upper bound: the `round_date` of the round it was first seen on
     (R9).** `underwriter_notes` carries `first_seen_round_id`, and `round_date` is "`date_printed`
     when known, else the date received", so a note first saved from a paste received on 08/29
     cannot have been written after 08/29. An incoming dated note with the same normalised text is
     **the same note** only if its date is on or before that bound. Then (ii) fills the date and
     (i) keeps the status still. If its date is **after** the bound it is a re-issue: it is new and
     **fires A1**. Without the bound, (i) swallows exactly the case its own rationale names. Round 1
     is pasted (the note saved undated), and round 2's PDF prints "**8/28 Not in Upload **9/10 Not in
     Upload". The 9/10 note matches the undated text, so (i) as first written never fires, which is
     the same loss it was meant to avoid under text-only matching.
   - **The date fill writes no event of its own, but it is recorded (R10).** §6 rule 4 says every
     change writes an event, and a fill changes what the note chip shows. It goes into the
     `CONDITION_SEEN_AGAIN` event the same import already writes for that condition (a
     `notes_dated` list in its payload), so there is still one event per condition per import.

   **LP-912 therefore wires A1**, with (i) as a guard on its came-back rule and (ii) in the note
   merge, and the strict xfail in `test_note_identity.py` becomes a normal passing test — the
   alternative the review's own xfail reason offers ("either fix `_new_notes` or move this assertion
   onto its came-back rule"). A test for (i) that fails without the guard is part of the same commit.
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
- **LP-912:** ADR-408 first, recording A1 to A7 as **accepted** (§5.0); A1 **is** wired, carrying
  §5.2's two-part rule as amended by R8 to R10 (normalised text; an undated saved note bounded by its
  first round's `round_date`; the fill recorded in `CONDITION_SEEN_AGAIN`), which turns `test_note_identity.py`'s strict xfail into a passing
  test and needs its own test for the guard; one migration carrying eight columns, the event-kind swap (eight kinds), the
  `ck_conditions_ownerhintsource` swap (D-4; `_CASES` already watches it), plus the
  `readonly.conditions` rebuild above `def downgrade(`; every new enum mirrored into
  `frontend/lib/types/conditions.ts` and registered in `_MIRRORED`
  (`tests/test_condition_type_mirror.py:55`), or the TS side silently lacks it; bulk inside
  `loan_file_needs_lock`, which is **advisory and not mutual exclusion** — the lock narrows a window,
  it does not close it.

  **THE REFUSAL SENTENCES ARE NOT IN THE DESIGN PACK, and this line said they were.** Corrected while
  building: all eleven Stage 2 screens were grepped and none of the four appears. The only related
  wording is S2-05's *hint* ("Moving back keeps the history. Moving forward never needs a reason."),
  which is not a refusal, and there is no "skipped" wording either. **§LP-912 of the tickets file is
  their single source of truth**, and the bulk report line ("4 updated · 1 skipped: information only")
  lives only in the spec's LP-913 text. That is consistent rather than an omission — every mockup is a
  happy-path state, and a refusal only appears once a processor trips it. A test compares each sentence
  against the tickets file's own bytes rather than a second hand-typed copy, which is what makes
  "character for character" a property instead of a claim (em dash included).

  **Three things LP-911's review hands forward** (LP-911 §Review, R1/R6/R8):
  - **Narrow `came_back` in the commit that allows a manual verdict.** LP-911 ships it as "the lender
    said not satisfied", which is the same set only while nothing but a note can produce
    `not_cleared`. The moment LP-912 lets a processor record *Came back* by hand, the field must
    become `verdict.source_kind == underwriter_note` or it starts claiming a note the lender never
    wrote.
  - **Add `verdict` and `pending_suggestion` to `ConditionPublic` typed, with their producers.** LP-911
    shipped them and the review removed them: `dict[str, Any]` is a type LP-912 has to replace anyway,
    and "add the key once to spare the mirror" does not survive the key being the wrong shape.
  - **A `_gate_map()` entry is not a guard on its own.** LP-911 added one and the gating tests stayed
    green with it deleted — it was decoration, measured. `test_every_condition_route_the_app_serves_is_in_the_walk`
    now checks the map against `app.routes`, so LP-912's new routes are caught by that test rather
    than by anyone remembering the map.
- **LP-916:** the new one-condition events reader, and a line in the ticket closing LP-909's open
  question about `ix_condition_events_condition_occurred` (D-5).

  **A MOVE THE APP MADE MUST NEVER BE SILENT** *(LP-912 follow-up review)*. A `not_cleared` verdict now
  resets our track from `ready` / `with_underwriter` to `to_do` (ADR-408 as amended, LP-912 decision
  row 10). The rule is not the surprise risk — **invisibility is**: a processor records "underwriter
  phoned, refused it" and finds the row at *To do* with nothing saying why. S2-08 already draws the
  sentence for the note-driven route — *"our status moved from Sent to lender back to To do"* — so the
  history line must say the same for the manual route, composed from the event's `prep_status_from` /
  `prep_status_to`, which `condition_verdict_recorded` now carries under the same key names
  `condition_came_back` uses. One sentence, two routes, one vocabulary.
- **LP-913:** replaces `ImportedView`; "Not known" follows the owner being `unknown`, not the source
  being `none` (D-6, `1228`); two new `StatusToken` vocabularies in `lib/status.ts`
  (`CONDITION_PREP_STATUS`, `CONDITION_LENDER_STATUS`) typed `Record<Enum, StatusMeta>` so a new
  member breaks the build, with the tones the design README fixes: ours `to_do` neutral / `waiting`
  progress / `ready` verified / `with_underwriter` progress, lender `open` neutral / `not_cleared`
  attention / `cleared` verified / `waived` verified / `superseded` muted. Read through
  `resolveStatus`, never indexed directly — LP-909 fixed that exact bug in `round-reading.tsx`.

  **A third thing, from LP-912's part 2 review (Q1):** **render `effective_owner` and
  `effective_owner_source`, never `owner_hint` / `owner_hint_source`.** `imported-conditions.tsx` and
  `review-rows.tsx` both render the hint pair, so a manual owner override — the whole point of
  `PUT /owner` — is **invisible in the list**: a processor reassigns a condition to Title and the row
  still says what the code map guessed. The hint pair stays on the wire deliberately (it is a true fact
  about what the sheet said, and S1-04 shows its provenance), so this is not a rename: the list and the
  filters read the effective pair, and only the detail sheet has any business showing the hint it
  overrode.

  **A fourth, from LP-916:** **the client cannot read a refusal's typed CODE, only its sentence.**
  `lib/errors/api-error.ts` normalises the LP-46 envelope (`error.type` / `error.message` /
  `error.details`) and never reads `error.data`, which is where LP-912 puts `{message, code}`. So
  `getErrorMessage` returns the right sentence — §6 rule 5 holds — and `ConditionRefusalCode` is
  unreachable in a component today. **Left deliberately unfixed by LP-916**, whose dialogs act on one
  condition at a time, where the sentence is the whole answer. **LP-913 is where it becomes real**:
  the bulk bar has to group refused rows ("4 updated · 1 skipped: information only") and cannot do
  that from prose. Widening the shared error module then, with its first actual consumer, rather than
  now on speculation.

  **Two things LP-916's review hands forward** (LP-916 §Review of `cf3b7fd3`):
  - **The sheet must be fed the DISPLAYED order, not the server's.** `ConditionDetailSheet` steps
    through the array it is given, which is how Previous/Next follow the filter and sort without
    knowing what they are — but LP-913 sorts and groups CLIENT-side, so passing it
    `conditions.data` would make ↑/↓ walk a different order from the one on screen. Pass the rows in
    the order they are rendered, after grouping.
  - **The Owner select cannot clear an override back to the hint, although `PUT /owner` accepts
    `owner: null`.** The sheet offers the seven owners and a Clear button; the LIST's inline owner
    control needs the same escape, or a processor who overrides by mistake can only pick another
    owner, never go back to what the sheet said. **A decision for LP-913** — the safest reading is
    that "back to the suggestion" must always be reachable wherever an override can be set, since
    the alternative is a one-way door.

  **Two things LP-911's review hands forward** (LP-911 §Review, R6 and its residual):
  - **Read `X-Conditions-Capped`.** The cap is reported in a header, not the body, because the list's
    response shape is a Done-when. `fetchConditions` returns `.data` only, so nothing reads it yet —
    a capped list currently renders as a complete one. The header is in CORS `expose_headers` (it was
    not, and a browser therefore saw it as absent), so the client *can* read it and must.
  - **`q` IN THE URL IS A REAL EXPOSURE, AND LP-913 MAKES IT WORSE THAN LP-911 DID.** The spec puts
    the filters in the browser URL *so a link can be shared*, and `q` searches `verbatim_text` — so a
    shared link can carry a borrower's employer or an account ending into whatever the recipient
    pastes it into, and into their history. Nothing in the app logs the term (`uvicorn.access` is at
    WARNING, `errors.py` logs the path only) and ALB access logs are off on staging, so the server
    side is recorded-and-accepted; the SHARED LINK is the part LP-913 introduces. **STOP AND ASK
    candidate for LP-913:** keep `q` out of the shareable URL (hold it in component state, or strip it
    when a link is copied) rather than shipping a share button that leaks the search. Recorded here
    because LP-913 is where the decision has to be made, not discovered.
    *(Review of `ee74b48d`: this is not a new kind of exposure, and the decision is ADR-405's rather
    than one ticket's. The pipeline LP-913's spec names as its model already writes `search` into the
    URL (`dashboard/page.tsx` → `writePipelineUrl`), and that search matches borrower NAMES
    (`services/loan_files.py`, `ilike` on first + last name). So a shared pipeline link has carried
    a borrower's name since the saved-views work. Keeping `q` out of the conditions URL is still
    the right default for LP-913, because it is cheap and every other filter stays shareable. But
    record it as an ADR-405 amendment that names the pipeline as the same exposure, or the app ends
    up with one rule for conditions and the opposite for borrowers.)*
- **Two follow-ups LP-912's review found, neither belonging to any Stage 2 ticket** *(recorded here
  because LP-911's forward items were nearly lost inside a Review section)*:
  - **24 CHECK constraint names disagree between a migrated database and `create_all`**, on 12 tables —
    19 doubled by the naming convention (all eleven of LP-904's, plus `communication_evidence`,
    `finding_events` ×2, `lender_contacts`, `mailbox_connections` ×3, `reminder_snoozes`) and five
    differing outright. Not urgent: `tests/test_migrated_checks_match_models.py` now compares by COLUMN
    rather than by name, so the landmine fails the suite instead of shipping. The rename is a tidy-up.
  - **Three CHECKs the models declare were NEVER migrated** — `communications.body_format`,
    `users.mail_client`, `validation_verdicts.kind`. A migrated database accepts any string in those
    columns today. Older than this stage, listed in that test's `_KNOWN_MISSING`, and the fix is one
    migration adding the three.
- **LP-915:** `condition_rounds.comparison` is a new column and therefore a `readonly` decision (D-1);
  the `possible_match` id the "Reworded?" rule reads is written only for same-code /
  different-fingerprint, and points at the **oldest** such condition.

  **Two parts of the DETAIL SHEET that LP-916 deliberately did not build** (LP-916 §"Two items from
  the ticket's content list are NOT built"), because each would be a branch no condition can reach
  until LP-915 writes its producer — **add them in the commit that adds the producer**:
  - **The pending-suggestion block** on S2-03: *"Round 2 suggests this probably cleared"* with
    **Confirm** and **Keep open**. `pending_suggestion` is not on `Condition`; LP-911's review removed
    it for having no producer, and it comes back typed WITH one, the way `verdict` did in LP-912.
  - **The "Replaced by / replaces" link** on S2-03. `superseded_by_id` is null on every row until a
    reworded pair is confirmed. The inverse direction ("replaces") is derivable from the list —
    the condition whose `superseded_by_id` names this one — so it needs no second endpoint.

  **Two things LP-912's part 2 review hands forward** (LP-912 §Review of `c1fbfedc`):
  - **Refuse verdicts and moves on a Replaced condition, and add the guard WITH the producer.** Nothing
    writes `superseded` until LP-915, so the guard has nothing to protect today and would be untestable
    if written now — which is precisely how it gets forgotten. A superseded condition's successor carries
    the work, so a verdict recorded against the replaced one is a verdict nobody will see.
  - **`record_verdict` takes `derived_allowed=False`** and refuses `round_comparison` /
    `underwriter_note` from a client (R2: a client could otherwise post
    `{not_cleared, underwriter_note, <any uuid>}` and paint S2-08's amber *Came back* on a note that
    never existed — measured, 200 and `came_back: true`). **LP-915's confirm step is one of the only two
    legitimate writers of a derived source and must pass `derived_allowed=True`**, along with a
    `round_id` that is an active round on the condition's own file.
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

- **No database was queried.** Every claim above is from source text, except the fixture numbers in
  §4 and D-6, which the review measured by running the readers and `load_seed("uwm")` (Review R5). "All rows are `to_do`" is
  therefore a claim about what the code can write, not a count (§2).
- **No screen was rendered.** The Stage 2 PNGs were read and their Must-match lists checked against
  the fixtures *numerically*; no pixel comparison was made, and none is claimed. That is each UI
  ticket's "Visual check".
- **CI has not run and will not run on this branch.** Local `ruff`, `mypy`, `pytest`, `biome`, `tsc`
  and `vitest` are the gate for all six tickets.
- **No real lender sheet was involved**, and none may enter the repo (ADR-405).

## Review (of `b0dc8c10`)

Each claim the builder flagged was checked against the code, and the fixture numbers were measured by
running the readers, not read by eye. Wrong claims were corrected in place above rather than softened.

| # | Finding | Fix |
|---|---|---|
| R1 | **A1 to A7 were never shown.** The spec's first instruction is to STOP AND ASK about them in this survey and record the answers before ADR-408. The survey did not list them. | §5.0 lists all seven as adopted-pending-answer; A1 marked blocked on R2. §6 tells ADR-408 to record which were confirmed. |
| R2 | **§5.2 was wrong: the import cannot reliably tell a new note from an old one.** A paste has no `date_printed`, so its notes save undated; the same note on a later PDF is dated, `_note_key` differs, and `_new_notes` calls it new. `condition_enrich` does not repair saved notes. Under A1 this is a false *Came back* that moves our status to *To do*, on the spec's own path (paste a round, attach the PDF, import the next full round). | §5.2 rewritten as an open STOP AND ASK, with a recommended rule. `tests/conditions/test_note_identity.py` measures it on `uwm_round1`: the precondition, what the decision gets right (two tests), and the defect as a **strict xfail** that flips when LP-912 fixes it. |
| R3 | **D-4 is right, and the guard was worse than it said.** Confirmed: no test, and no CI step (neither workflow runs Alembic), watches `ck_conditions_ownerhintsource`. Adding `MANUAL` with `_CASES` widened fails exactly that case (mutation-checked, reverted). Two more defects in `tests/test_activity_type_migrations.py` would have hit LP-912: (a) the swap reader returned the **first** swap in `upgrade()` for *any* constraint, so LP-912's two-swap migration would have read event kinds as owner-hint sources, and it already counted LP-909's event-kind swap as an **activity-type** definition, because that file names the activity constraint in its docstring; (b) names were matched as substrings, and `ck_conditions_ownerhint` is a prefix of `ck_conditions_ownerhintsource`. | `_CASES` now watches all ten condition-family CHECKs (the two nullable `lender_condition_codes` hints are not, since their `IS NULL OR` form isn't parsed). A swap is credited to the constraint its call or helper names, a helper naming none or several is reported as unreadable rather than guessed, and a file that only mentions a constraint no longer counts as defining it. Five new tests; restoring the old reading fails three of them. |
| R4 | D-4 said "six new event kinds". The spec's single LP-912 migration adds **eight** (six plus LP-915's two). | Corrected in D-4 and §6. |
| R5 | §4/D-6 numbers were read by eye. **All measured true** with `read_uwm` + `load_seed("uwm")`: round 1 = 11 in the 6/5 PTD/PTF split, round 2 = 6, absent = `7086 6132 6637 6178 0132` exactly, still open as stated, new = none, `0132` → `prior_to_docs`, the only `info_only` row is `0973` (on neither sheet), borrower = exactly `7086 6132 6637`, and `1947`/`6378` are `title`/`prefix`. Every letter change and expiry date matches. **Two things were wrong:** without a code map, *nine* conditions come back `unknown`, not all eleven (the prefix still sets `title`); and `1228` is `unknown` with source **`code_map`**, not `none`. The seed has **28** rows, not 29. | D-6 corrected; the `1228` rule added to D-6 and to §6's LP-913 line. |
| R6 | The header claimed S2-08's numbers were checked against the fixtures. S2-08 needs round 3, which doesn't exist. | Cut. |
| R7 | §1 said LP-909's three failures "still hold on this machine", but nothing was run at this commit. | Replaced with a pointer to the measured baseline below. |
| — | **D-2 confirmed.** No test walks `app.main`'s routes for gates (`test_no_draft_save_route.py` walks `app.routes` only to check a path is absent). A route added to the existing `/loan-files` router *would* be caught (it must carry `ScopedLoanFileById`), so only a **new** router is invisible, as D-2 says. | None needed. |
| — | **§5.1 (LP-917) confirmed.** Round 2's expiry row gives close-by and income `11/03/2026`, and 09/26 to 11/03 is 38 days. Done-when and S2-11 are right; the goal's "65 days" is stale. | None needed. |

### Measured baseline

- **Backend at `b0dc8c10`:** `uv lock --check`, `ruff check`, `ruff format --check` and `mypy app/`
  clean; **pytest 8310 passed, 3 failed, 10 skipped, 1 xfailed** in 18 m 36 s. The three failures
  are LP-909's: `test_cli_refuses_unpaced_bedrock` and the two `test_page_ocr` tesseract tests.
- **Backend, this review's change:** the two changed test files alone, **44 passed, 1 xfailed**. That
  is the whole delta: no app code changed, and neither file shares fixtures. The full suite was not
  re-run after the edit. Ruff clean over `tests/`.
- **Frontend at `b0dc8c10`** (unchanged by this review): biome clean over 438 files, `tsc` exit 0,
  `CI=true TZ=UTC pnpm test` **1956 / 1956** in 159 files.

## Second review (of `0fd8066b`)

`0fd8066b` changes docs only. The tests it names for (i) and for the xfail flipping are **promised for
LP-912's commit**, not included here. The follow-up message could be read as saying they were in this
commit.

The builder asked for (i) to be attacked directly: can it still fire a false *Came back*, and can it be
built against the import as it is?

| # | Finding | Fix |
|---|---|---|
| R8 | **Yes, (i) can still fire a false *Came back*.** It keys on the note's text being *identical*, and the reader keeps whitespace inside a note: `_NOTE` captures `(.*?)` and only `.strip()`s it. Measured with `read_pasted_text` on round 1: a paste with a double space or a tab inside "Not in Upload" saves `'Not in  Upload'` / `'Not in\tUpload'`. A browser copy of the portal is exactly where that happens. The PDF's note then fails to match the undated one, and A1 fires. | §5.2: (i) and (ii) compare normalised text, `" ".join(text.lower().split())`, the same folding `note_stripped` uses. |
| R9 | **(i) as written loses the true *Came back* it was designed to keep.** Its rationale is that text-only matching would absorb a real re-issue. But (i) also decides by text alone whenever the saved note is undated, so the case it cites (round 1 pasted, then round 2's PDF carrying "**8/28 Not in Upload **9/10 Not in Upload") never fires for 9/10. This is the note A1's own rationale quotes. | §5.2: the undated saved note is bounded by the `round_date` of its `first_seen_round_id` (the date printed, or else the date received). An incoming note dated on or before the bound is the same note (fill the date, no status). Dated after the bound, it is a re-issue and fires. This is buildable today: both fields exist and the import already has the file's rounds. |
| R10 | (ii) said "no event written", but §6 rule 4 requires an event for every change. | The fill is recorded in the `CONDITION_SEEN_AGAIN` event the same import already writes, so it adds no second event. |
| — | **§5.0, accepted rather than pending.** I can't see the product owner's instruction from here. The builder quotes it, and it answers exactly the question the spec says to ask, so recording it as the answer satisfies "record the answers there". Accepted. Keeping A1's intent separate from §5.2's mechanism is right. | None. It has also been raised with this session's user, who can object. |
| — | **For LP-912 to settle, not a survey defect:** a came-back import already writes `CONDITION_SEEN_AGAIN` and `CONDITION_NOTE_ADDED`, and the spec adds `condition_came_back` plus a move of our status. ADR-408 should say which of these is "the one event" for §6 rule 4, or state why a came-back writes more than one. | Left to LP-912. |

Nothing was run for this review beyond the two reader measurements above. Nothing executable
changed, so the baseline in the first Review section still stands.
