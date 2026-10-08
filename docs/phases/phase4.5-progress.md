# Phase 4.5 progress — Stages 0, 1 and 2 (conditions)

**Read this first and write it last.** It is the short state of the conditions work: what shipped,
what was deferred, and every STOP AND ASK and how it was answered (spec §11). The detail lives in the
ticket files; this page points at them.

Spec: [`phase4.5-stage0-1-build-spec.md`](phase4.5-stage0-1-build-spec.md) ·
Plan: [`phase4.5-build-plan.md`](phase4.5-build-plan.md) ·
Boundaries: [`phase4.5-boundaries.md`](phase4.5-boundaries.md) ·
Survey: [`../tickets/phase4.5-survey.md`](../tickets/phase4.5-survey.md)

**Branch:** `phase4.5-conditions`. **Do not merge** (LP-909): the branch stays for review. Check with
`git rev-parse --abbrev-ref HEAD`, not this line.

**STAGE 1 IS NOT FINISHED, AND THE GAP IS NAMED.** Of §11's list, the tickets, ADRs, glossary,
boundaries and this file exist; §8 steps 1–7 pass through the API; all 13 screens have been checked.
What is outstanding: **CI is not known to have run** (only a PR to `main` triggers it), §8 step 8 needs the product owner's
machine, several screens are partial (LP-909 §5), and one STOP AND ASK is open.

---

## What shipped

| Ticket | What | State as its file records it |
|---|---|---|
| [LP-903](../tickets/LP-903.md) | ADR-403…407, glossary terms, `phase4.5-boundaries.md` — no code | done; ADR-403…407 all **Accepted** |
| [LP-904](../tickets/LP-904.md) | four condition tables, four `lenders` columns, migration `d1f4b8c25e93`, five readonly views | done; downgrade never run |
| [LP-905](../tickets/LP-905.md) | upload and email-forward doors, the parse task, migration `e5a2c7f31b84` | done; its table lists a §2 that has no body in the file |
| [LP-906](../tickets/LP-906.md) | rule readers: line model, UWM, Champions, generic; UWM from PDF | done |
| [LP-907](../tickets/LP-907.md) | the paste door and reader, fingerprint, `attach-pdf` enrich | done |
| [LP-908](../tickets/LP-908.md) | the AI splitter (`split_v1`) and its enqueue wiring | done; its table still reads §2 "next" though §2 is written |
| [LP-909](../tickets/LP-909.md) | read endpoints, import under the needs lock, draft / discard / add-by-hand, the Conditions tab and all 13 screens, round history | §1–§4 done; §5 in progress |
| [LP-910](../tickets/LP-910.md) | UWM and Champions code maps (28 codes each), loader, seed keyed on `canonical_lender_key` | done; the seed has never run against a database |

Migrations since `phase4-with-ui`: `d1f4b8c25e93`, `e5a2c7f31b84`, `c4b8f1a72e95`, `b6d1e93f57ac`
(head). A local dev database at `e5a2c7f31b84` needs the last two before an import will write.

## STOP AND ASK — every one, and its answer

| # | Where | Question | Answer |
|---|---|---|---|
| 1 | spec §2 | Is `phase4-with-ui` the right base; are LP-903…910 and ADR-403…407 free? | checked, no stop (survey §0) |
| 2 | spec LP-910 | Can UWM and Champions be identified reliably? | **No** — product owner, 2026-09-23: option 1, a nullable `canonical_lender_key` added in LP-904 (survey §15.1, ADR-407) |
| 3 | spec LP-906 | Would a PDF library be a new runtime dependency? | no stop — `pymupdf` already installed |
| 4 | spec LP-905 | Would storing the sheet route it through classify → extract → needs? | no stop — `storage.save_at()` |
| 5 | spec LP-905 | Does `CORRESPONDENCE` keep the file retrievable? | no stop — `_attachment_bytes` re-derives it; confirmed by the product owner |
| 6 | LP-910 | Declare PyYAML? | product owner, 2026-09-23: declare it explicitly. (The ticket cites §9; the spec has no specific line for it — §9.10's general rule.) |
| 7 | survey §15.2 | How to do a Visual check with no browser? | product owner, 2026-09-23: "the way LP-859" — mark UNVERIFIED. **Superseded in LP-909 §5:** a browser was found and all 13 were checked on screen. |
| 8 | LP-909 §3 | S1-03 depicts failures the system cannot produce | product owner: build the screen for the failures that exist |
| 9 | LP-909 §5 | Spec step 2 updates `sequence` on seen-again; on a partial round that breaks S1-08 | **taken as the recommended option** (standing instruction): only a FULL round moves `sequence` — `ac9007ac` |
| 10 | LP-909 §5 | S1-01's forward card offers a door the v1 capability switch keeps shut | **OPEN.** Recommended: show the card only when `receiving` is on |

Not raised as a STOP AND ASK though §9.10 would allow it: the survey's §14 table of spec/code
differences records each difference without stopping on any.

**For the domain expert (open):** the UWM reader maps "UW - Prior To Final Approval (PTD)" to
`prior_to_docs`, trusting the parenthetical over the words (LP-909 §5).

## Deferred — on purpose, and where it is written

- **Stage 2 and later:** comparing rounds, "probably cleared", `possible_match`, statuses that move,
  needs from conditions (Stage 3), `canonical_type_id` on the 56 code-map rows (LP-918).
- **Never exercised:** LP-904's downgrade; the LP-910 seed against a database; any real lender sheet
  (§8 step 8); the OCR path (tesseract absent); a paste from an HTML portal; `(PA)` markers.
- **Known gaps left in place:** the stranded-`PARSING` reaper (LP-905, LP-908); unrouted-message
  forwarding (LP-905); "Ignore this line" (LP-909 §4); `failure_kind` in the history (LP-909 §4);
  `ix_condition_events_condition_occurred` has no reader (LP-909 §4).
- **Visual-check misses still open** — screen by screen in LP-909 §5. After four passes: S1-11's warnings and dateless note
  chips need structured reader warnings (**LP-930**); "Ignore this line" (S1-10), a recorded
  deviation because nothing in the schema can remember a dismissal. S1-13 now asks attach-or-new and links to the round, but lives behind the `receiving`
  switch, which v1 turns off.

---

# Stage 2 — "See and track"

Spec: [`phase4.5-stage2-tickets.md`](phase4.5-stage2-tickets.md) (it wins over the build plan) ·
Screens: [`../design/phase4.5-conditions/stage2/README.md`](../design/phase4.5-conditions/stage2/README.md)

**STAGE 2 IS NOT FINISHED, AND THE GAP IS ONE THING.** All six tickets are built, reviewed and
committed, and §5's acceptance scenario passes steps 1–9 through the API. **§5 step 10 has not been
done at all: not one of the 11 reference screens has been looked at by a person.** Neither this
session nor the reviewer's had a browser. That is a regression against how Stage 1 finished — its
STOP AND ASK 7 above records that "a browser was found and all 13 were checked on screen" — and §5
step 10 says in as many words that "Stage 2 is not done until a person has looked at them".

## Stage 2 — what shipped

| Ticket | What | State as its file records it |
|---|---|---|
| [LP-911](../tickets/LP-911.md) | conditions read API: filters, five sorts, summary, detail | done |
| [LP-912](../tickets/LP-912.md) | ADR-408, the two status tracks, verdicts, reopen, owner, bulk, the came-back hook; migration `f3a9c05d81e7` | done; reviewed twice (part 2 and a follow-up) |
| [LP-916](../tickets/LP-916.md) | condition detail sheet (S2-03) with S2-04 and S2-05; eight condition-level event scalars | done; two blocks deliberately left for LP-915 and built there |
| [LP-913](../tickets/LP-913.md) | conditions list view (S2-01, S2-02, S2-09): summary bar, filter row, grouping, bulk bar | done |
| [LP-915](../tickets/LP-915.md) | round comparison, its three doors, the `condition_was_replaced` guard, the S2-06/07/08/10 panel; migration `a7c31e6d94b2` | done; seven review findings fixed |
| [LP-917](../tickets/LP-917.md) | the lender's dates in the rail, on the round card, and "Must Fund By" (S2-11) | done; no defects found in review |
| LP-914 | board view | **deferred by D1** — not built, and nothing here anticipates it |

Migrations added by Stage 2: `f3a9c05d81e7` (LP-912), `a7c31e6d94b2` (LP-915, **head**).

## Stage 2 — the acceptance scenario (§5)

`backend/tests/conditions/test_stage2_acceptance.py` drives **steps 1–9 through the API** on the §7
fixtures — every sheet through the upload door, every decision through its endpoint, nothing calling a
service directly. **2 passed.** What it pins, in the spec's own numbers: 11 conditions all *To do /
Open*; the step-2 moves, with the backward move refused by its typed code and accepted with a reason;
round 2's probably-cleared being exactly `0132 6132 6178 6637 7086` against 11 compared; confirm 4 →
**Open 7 · Cleared 4** with no question left pending; `0132` cleared by hand → **Open 6 · Cleared 5**;
round 3's came back `1228` (our track back to *To do*), new `7383`, reworded `6378` answered *Same
condition* so the old half reads *Replaced* and points at its successor, and `0006 0007` confirmed →
**13 total · Cleared 7 · Replaced 1 · Open 5**; the reopen with a reason; the history newest-first; and
round 3's own letter carrying the dates the rail reads. Step 9's twelve cross-tenant calls all 404 and
leave the file untouched.

**Step 10 is not done and no assertion in that file should be mistaken for it.** It is the screens.

**Measured after Stage 2, at the Stage 2 review:** full backend suite, run alone, **8507 passed,
3 failed, 10 skipped, 1 xfailed** in 21 m 31 s (the builder's 8506 plus the review's bulk test).
`ruff`, `ruff format`, `mypy app/` clean. Frontend: `tsc` 0, biome clean over 456 files, and vitest on
`lib/conditions`, `components/file/conditions` and `components/layout` **231 / 231** (the affected
directories, not the full suite). The review also tightened this acceptance test from counts to exact
sets: round 2's still-open six, round 2's eight letter changes, round 3's still-open pair, and the
reworded pair's two halves. The three are the baseline's and none touches conditions
(`test_cli_refuses_unpaced_bedrock`, and the two `test_page_ocr` tesseract tests — tesseract is absent
on this machine). Migrations `f3a9c05d81e7` and `a7c31e6d94b2` are both applied in that run.

## Stage 2 — decisions taken without the product owner

The standing instruction was to settle each with the reviewer, take the safest option — the one that
never clears, removes or changes a condition's status without a person's click — and record it rather
than stop. Each ticket carries its own table; these are the ones a product owner may still want to
overturn:

| Where | Question | What was chosen |
|---|---|---|
| [LP-915](../tickets/LP-915.md) #3 | "Different conditions — keep both" leaves both rows alone, but the spec does not say what becomes of the QUESTION | The pair is resolved either way, so the panel stops asking. Left pending, "these are different" would be unanswerable |
| [LP-915](../tickets/LP-915.md) #5 | *Full list → Just some*: recompute, or withdraw? | Withdraw the unconfirmed suggestions, recompute nothing — a recompute would retroactively change "compared with the 11 conditions that were open before it" |
| [LP-915](../tickets/LP-915.md) #6 | S2-06 and S2-08 order the count pills differently, and neither lists order under *May differ* | Settled in review (R4): the sheet's own news first when there is any, then Probably cleared collapsed with **Review** — one rule that satisfies both screens, so this no longer needs the product owner |
| [LP-915](../tickets/LP-915.md) #8 | S2-06's "line naming what didn't change" | Not built. The saved comparison stores only the values that MOVED, and widening it would put more of the lender's letter into an NPI column to decorate one line |
| [LP-917](../tickets/LP-917.md) #1 | The tickets file's example says "Asset docs expire 11/30/2026 · 65 days"; S2-11 draws 11/03/2026 and "· 38 days" | The design and the Done-when, which agree with each other. The prose example appears to predate the fixture |
| [LP-917](../tickets/LP-917.md) #2 | S2-11 shows Lender dates in the rail without naming a tab; the rail never fetches anything of its own | Behind a Conditions-tab check, like its two siblings. Showing it everywhere is a BACKEND change (the dates reaching the file read), not a placement one |
| [LP-912](../tickets/LP-912.md) #10 | A *Came back* recorded BY HAND left our track at *Sent to lender*, while the lender's own note reset it to *To do* | Both now reset `ready` / `with_underwriter` to *To do* (ADR-408 amended). The one row most likely to be revisited if the product owner wants the two routes to differ |
| Stage 2 review | Bulk "Set status → Waiting" sends no owner (one request cannot carry one per row) | Each row waits on its own effective owner, the rule the single-row control already follows. Before this, every row was refused "Say who you are waiting on." |

Also recorded and not fixed: a reworded pair answered *Different* is asked again if the round is
switched *Full → Just some → Full*, because keeping that answer would need it stored on the round
(LP-915 review).

## Stage 2 — every screen, and how to open it

**None of these has been checked on screen.** Seed a UWM file whose lender has
`canonical_lender_key = "uwm"` and whose code map is seeded (`seed_lender_codes`), then import the §7
fixtures as PDFs through the upload door: `uwm_round1_2026-08-28.txt`, then
`uwm_round2_2026-09-10.txt`, then `uwm_round3_2026-09-18.txt`. Open at **1600 px** (the file rail is
`hidden xl:block`, so below 1280 px it becomes the File context drawer).

| Screen | Ticket | The state that opens it | Result |
|---|---|---|---|
| S2-01 list after round 1 | LP-913 | after round 1 only | **UNVERIFIED ON SCREEN** |
| S2-02 list mid-work, bulk | LP-913, LP-912 | after §5 step 5, with 3 rows ticked | **UNVERIFIED ON SCREEN** |
| S2-03 condition detail | LP-916 | click `6637` once round 2 has cleared it | **UNVERIFIED ON SCREEN** |
| S2-04 record the lender's answer | LP-912 | select 3 rows → **Record lender's answer** | **UNVERIFIED ON SCREEN** |
| S2-05 move back needs a reason | LP-912 | move `0006` from *Ready to send* back to *To do* | **UNVERIFIED ON SCREEN** |
| S2-06 what changed in round 2 | LP-915 | immediately after importing round 2 (full) | **UNVERIFIED ON SCREEN** |
| S2-07 confirm with one unticked | LP-915 | the same panel, `0132` unticked | **UNVERIFIED ON SCREEN** |
| S2-08 round 3: came back, reworded, new | LP-915, LP-912 | confirm round 2's five, send `1228` to the lender, import round 3 | **UNVERIFIED ON SCREEN** |
| S2-09 filtered to nothing | LP-913 | filter Owner: Insurance + Our status: Waiting | **UNVERIFIED ON SCREEN** |
| S2-10 partial round, nothing suggested | LP-915 | import round 2 as *Just some* instead | **UNVERIFIED ON SCREEN** |
| S2-11 lender dates | LP-917 | the Conditions tab after round 2 or 3 | **UNVERIFIED ON SCREEN** |

**Where the build is short of a screen, as opposed to unverified on it.** Named here so the
"unverified" label is not used to cover an absence *(corrected in the Stage 2 review: the first version
listed S2-08's second came-back clause as not built, but LP-915's review built it (R5), and it missed
the other three rows below)*:

| Screen | Item | State | Where recorded |
|---|---|---|---|
| S2-06 | "a line naming what didn't change" | **NOT BUILT.** The saved comparison stores only the values that moved | LP-915 #8 |
| S2-09 | the line explaining *why* the filter matches nothing ("6178 was cleared in round 2") | **NOT BUILT.** On S2-09's May-differ list; the named filter is present | LP-913 |
| S2-03 | the note's quote in "Underwriter note added in round 1: “8/28 Not in Upload”" | **Left out by decision.** The quote is the lender's words (NPI); the line keeps everything else | LP-916 #1 |
| S2-08 | round 3's card text | **Count form only**, not "Review what changed" | LP-915 #11 |

And two behaviours a person checking S2-02 should judge (LP-913 review): the collapsed "Cleared"
section also holds **waived** rows, and clicking "Cleared 5" empties the live list and points at the
section below rather than expanding it.

## Stage 2 — deferred, on purpose

- **LP-914 (board view)** — D1, kept in the plan and moved after Stage 3.
- **Stage 3 and later:** needs from conditions, the lender's verified figures against the file's own
  (LP-915 leaves it out with a note), "Email borrower" / "Request document" actions.
- **Stage 4:** contract closing / signing / funding dates a processor enters, "soon" warnings and
  colours on the lender dates, the Today queue (LP-917 keeps the section plain text for this reason).
- **Never exercised in Stage 2:** both migrations' downgrades against a database with data; the
  `GRANT` in LP-912's and LP-915's view rebuilds (the role `mbai_readonly` does not exist on this
  machine, so the guard takes its no-op branch).

## Stage 2 — follow-ups the reviews recorded

Four were done on 2026-09-28, each through the same build, review and push loop as Stage 2.

- **Done — LP-909's event kind, checkable on staging** (no ticket; `70b87c8e`). The query is now
  [`scripts/checks/staging_condition_event_checks.sql`](../../scripts/checks/staging_condition_event_checks.sql),
  with what a healthy result looks like in its header and a "How to run it" section in
  [LP-912](../tickets/LP-912.md). Proven on scratch databases (two rows at `b6d1e93f57ac`, one healthy row
  at head). **Staging is healthy:** run there during D's review on 2026-09-28, it returned exactly one
  row, `ck_condition_events_conditioneventkind`, admitting `round_reparse_requested`. LP-912's repair is
  live and `round_reparse_requested` is writable on staging.
- **Done — the three CHECKs no migration created** ([LP-931](../tickets/LP-931.md), `8b26c76b`).
  `communications.body_format`, `users.mail_client` and `validation_verdicts.kind` are constrained on a
  migrated database; a bad existing row stops the migration and changes nothing. `_KNOWN_MISSING` is
  empty. Staging's `body_format` and verdicts were checked clean through the readonly views;
  `mail_client` is not exposed there, and the migration's own pre-check covers it.
- **Done — the 24 misnamed CHECKs** ([LP-932](../tickets/LP-932.md), `45f722d8`). Every CHECK on a
  migrated database now carries the name the models give it, and the migrated-schema guard checks names
  as well as values.
- **Done — `q` out of the pipeline's URL** ([LP-933](../tickets/LP-933.md), `4c58e6a7`). The borrower
  search is kept per tab in sessionStorage; statuses and the selected view stay in the URL; a saved
  view's own term is applied without reaching the URL. ADR-405's amendment says the pipeline follows it.
  Its review found that a stored term could pass to the next user after a reload, since a sign-out the
  tab never witnessed did not clear it; fixed in `1e2d97c1` by stamping the term with its user.

Found while doing them, not done:

- **Column widths and nullability drift between a migrated database and the models** (found by the
  LP-931 review: 26 columns). `validation_verdicts.kind` is `varchar(14)` migrated against
  `VARCHAR(32)` in the models, and `flagged_remove` is exactly 14 characters, so a longer `VerdictKind`
  member would pass the suite and fail only on a migrated database. No guard compares widths. Deserves
  its own ticket.
- **`conditions-screens.test.tsx` › "offers a way out once the round is stranded" fails in a full-file
  run** and passes alone; it fails the same way at `dc87234e`, before these tickets. Its fixture sets
  `created_at` to exactly `now - STRANDED_AFTER_MS` and `isStranded` needs strictly more, so the
  fixture sits on the threshold and answers "is a round stranded at exactly 10 minutes?" by accident,
  depending on which clock the file leaves running. Measured two ways: **deterministic at file scope**
  (four runs of the file, four failures), **green in some whole-suite runs** (the LP-933 review's run
  passed 2048 of 2048), so a whole-suite green does not close it. The fixture should be one millisecond
  to whichever side the product means.

## CI

**Not known to have run,** for Stage 1 or Stage 2. Both workflows trigger only on `push` and
`pull_request` to `main` — a push of this branch runs nothing, so CI needs a PR against `main`, and
this branch is not to be merged (LP-909).

Measured rather than asserted: the Stage 2 review's commit (`ad2dc2aa`) is pushed.
`origin/phase4.5-conditions` was at `ad2dc2aa` on 2026-09-28 before the follow-ups above. **The plan was
to push each follow-up only after its review commit, and that is not what happened:** at 17:46 that day
a push from this clone (not from the session building them) moved origin to `1e2d97c1`, carrying all
five follow-up commits (`8b26c76b`, `45f722d8`, `4c58e6a7`, `70b87c8e`, `1e2d97c1`) and `dc87234e`
ahead of every review. The reviews found one real defect, in LP-933, and its fix (`1e2d97c1`) was in
that push, so nothing unreviewed-and-wrong reached origin that the review had caught. The review commits
and the review follow-ups come after. Pushing still runs no CI, for the reason above. Local results
and their limits are in LP-909 §5 for Stage 1, and in each ticket's own Verification section.

---

# Stage 3 — Work the conditions

**Spec:** [`phase4.5-stage3-plan.md`](phase4.5-stage3-plan.md) (behaviour, data, numbers) and
[`../design/phase4.5-conditions/stage3/README.md`](../design/phase4.5-conditions/stage3/README.md) (look
and wording, S3-01 to S3-12). **Loop:** [`phase4-execution-protocol.md`](phase4-execution-protocol.md),
builder `mortgageboss-ai-be`, reviewer `mortgageboss-ai-cf` (the brief names it "Reaspberry-review"; no
session of that name exists, and the product owner named `mortgageboss-ai-cf`). A ticket is done when its
row says **REVIEWED** with a review SHA; the branch is pushed only after that.

**Screens are checked with `scripts/visual-check/`** (LP-934): a scratch database, 1600 px, light theme,
the "Today" table's clock. Actual and review shots are committed under
`docs/design/phase4.5-conditions/stage3/checks/`.

## Stage 3 — tickets

| Ticket | Status | Build SHA | Review SHA | Visual check | Notes |
|---|---|---|---|---|---|
| LP-934 Pre-flight: screens against the plan, visual-check harness | REVIEWED | `97c39491` | the commit titled `LP-934 review:` | harness re-run on `base` by the reviewer; no S3 state buildable yet | 7 mismatches, 4 screen deviations (LP-934.md); review found 1, fixed: the dev-database guard had no test |
| LP-918 Condition library v1 (data) | REVIEWED | `28ffc2f8` | the commit titled `LP-918 review:` | none of its own | owner's top-20 sign-off tracked separately (decision 6); review found 1, fixed: 5 type ids are also rule ids, now pinned |
| LP-919 Reading each condition | REVIEWED | `65cb0617` | the commit titled `LP-919 review:` | S3-01 (this ticket's lines) and S3-03 re-shot by the reviewer: both match | no findings; D5 recorded; 6637 and 0132 item splits confirmed on screen |
| LP-920 The action plan | REVIEWED | `106de9af` | the commit titled `LP-920 review:` | S3-01, S3-02, S3-03 re-shot by the reviewer; S3-02 matches every line, S3-01 differs on one string (D6) | review found 1, fixed: a Must-match string recorded as a match, now D6 |
| LP-921 Next-step options | REVIEWED | `0111c5f0` | the commit titled `LP-921 review:` | S3-12 shot and walked by the reviewer: every line this ticket builds matches (sends LP-922, checks LP-923); S3-01 chips match | review found 2, fixed: the suite count was pre-fix (8592), the deviation list named only D1-D4 |
| LP-922 Asking people (drafts only) | REVIEWED | `29c74a7d` + follow-up `35a558f8` | the commits titled `LP-922 review:` and `LP-922 follow-up review:` | S3-04, S3-05, S3-06 shot and walked by the reviewer; D7 and D8 recorded | 2 reviews: a pre-existing flaky test recorded; the polish fact-check could not see a swapped pair, now caught |
| LP-923 Evidence arrives and is checked | REVIEWED | `d2a6f43a` | the commit titled `LP-923 review:` | S3-07, S3-08, S3-12 shot and walked by the reviewer; S3-08 matches every line, S3-12 confirms Failed a check 3 | review found 2, fixed: LP-934's D1 still said 2; the per-item open-finding guard had no test |
| LP-924 The figures check | REVIEWED | `2f848c5f` + follow-up `e7afa680` | the commits titled `LP-924 review:` and `LP-924 follow-up review:` | S3-09 shot and walked by the reviewer: matches every line | review found 1 (Apply ignored the baseline she saw); the builder fixed it and the fix is verified, including that it does not over-refuse. STOP AND ASK 2 open on the 45% reading |
| LP-925 Package, submit, lender settings | REVIEWED | `b415c136` | the commit titled `LP-925 review:` | S3-10 and S3-11 shot and walked by the reviewer: both match, with D10 and D11 | no defects; the ungated lender-settings routes judged correct; a note-check boundary recorded |
| LP-935 Stage 3 close | REVIEWED | `5b1582cf` | the commit titled `LP-935 review:` | every screen (24 shots: both sessions, all twelve) | review found 2, fixed: the mortgagee-clause term asserted unsourced domain claims; a decision she may want to overturn was missing from the table |
| LP-936 DU tolerance (STOP AND ASK 2) | REVIEWED | `0c8090e6` | the commit titled `LP-936 review:` | S3-09 re-shot by the reviewer: the new callout is true as a rule, not only in this state | no findings; the owner's table and the 50% parenthetical both verified, including 47→51 |
| LP-937 Superseded failures | REVIEWED | `770d2513` | the review section in [LP-937](../tickets/LP-937.md) (written, not yet committed) | S3-08, S3-12 re-shot: unchanged (no drawn state shows it) | review found 1: a superseded row that is still evidence can hold the condition while the sheet hides the finding doing it — the Stage 3B dead end through the other door; plus the "together with" wording is false when both rows are the same account. Counts verified (8702/1, 2125/2125); a second intermittent test recorded. **Follow-up `da6fbd19` reviewed: no findings** — `replaced` and `_settle`'s filter are now the same predicate negated, so a row that can hold the condition can no longer be hidden; the third member (Next step) verified reachable; predicate pinned in both directions |
| LP-938 Library fixes (AS-04, the review table) | REVIEWED | `37f5aa9f` | the review section in [LP-938](../tickets/LP-938.md) (written, not yet committed) | none (no screen) | review found 1 (pre-existing, not a regression): AS-04's receipt item's only check, `amount_matches`, reads bank-statement transactions and so returns not_run for an earnest money receipt — the item can never pass without a manual accept. Table verified independently of its generator: 20 rows x 5 columns re-derived from the raw YAML and seed files, 0 mismatches. The owner's top-20 sign-off still open, on the regenerated table. **Follow-up `8239ea91` reviewed: 1 finding** — the receipt is fixed and the purchase-agreement census is clean (only AS-11 lists it, with no amount check), but the same dead end is open on AS-06's `gift_letter` item, whose only document type carries `gift_amount` that `amount_matches` never reads; latent, since AS-05/AS-06 are on no mapped sheet. **Second follow-up `c9425f67` reviewed: 1 finding** — the typed `OWN_AMOUNT` allow-list is the right guard (better than the tripwire the reviewer suggested: it makes the unsafe pairing unrepresentable and takes `_takes` off the correctness path), but `reask_name` now names a receipt, gift letter or deposit slip "A corrected the statement", which is both false and ungrammatical, on a re-ask path this commit opens. **Third follow-up `71ca84a8` reviewed: 1 finding + 2 recorded** — copying the failed item's performer is right (a wrong receipt is title's, and it used to re-ask the borrower), but `reask_to` falls back to "borrower" both when the item is not an ask and when its performer has no `_RECIPIENT` entry, and in the second case the ask is created for someone else and reaches no draft; the grammar fix is universal, the document name is fixed for 3 types of 32. **Fourth follow-up `341f9c54` reviewed: 1 finding** — the gate is now correct by construction (`recipient_for` decides both) and the naming class closes for 29 of 32, but `document_label` renders five types as non-English where a re-ask now prints them, four on mapped sheets. **Reviewer agrees LP-938 can close**, the open items carrying the remainder |
| LP-939 Real-model trial | SKIPPED | | | none | skipped for now by the owner, 2026-09-29 | REVIEWED: no findings. Script and README only. The written summary enumerated at the source: counts, enums, lender codes, "sheet 1" labels — no text, names, amounts or digits. The one path the builder's list missed, `"error": outcome.error`, verified safe: condition_reading sets it only to `type(exc).__name__` or the literal "unreadable_response". The private `_ai_input`/`_ask_model` import is right (a copy would measure the copy) and fails loudly. `Path.resolve().is_relative_to` handles `..` and symlinks |
| LP-940 Withdraw a hand-added condition | REVIEWED | `faea58ad` | the review section in [LP-940](../tickets/LP-940.md) (written, not yet committed) | detail sheet | amends ADR-404. Review found 1: `submit` never rewrites `package.rows`, so a condition withdrawn while the package was BUILT stays in the submitted record — the refusal then tells her it went to the lender (false) and the Undo becomes one-way. Census verified complete for the 40 Condition-row readers, plus one class it did not name (child-table queries that do not filter the parent). Counts verified (8723/1, 2135/2135). **Follow-up `e8265768` reviewed: no findings** — the record now stores exactly what was sent (verified on the reviewer's own sequence: the row is gone, `_submitted_on` is None, the second withdrawal succeeds), and the restored Undo guard is unpinned only in the branch that cannot fire — `_was_withdrawn` always-False fails 4 tests |
| LP-941 Withdrawal history | REVIEWED | `44d9fbfa` | the review section in [LP-941](../tickets/LP-941.md) (written, not yet committed) | detail sheet history | batch 2, the owner's list of 2026-09-29. No defect: the free-text exception is contained — traced to two company-scoped routes and ruled out of the log, the activity log, the timeline, the package, any export and `readonly.condition_events` (whose `detail` is dropped, verified against the live view). Two notes: the new allow-list justification is a *different* kind of exception from `actor_name`'s (that one is safe because it is never read from `detail`; this one is), and the 500 cap is written twice |
| LP-942 Asks with no email | REVIEWED | `ac4f6d58` | the review section in [LP-942](../tickets/LP-942.md) (written, not yet committed) | an item line | No defect; the invariant verified for all 11 performers x both asks (0 stranded). Review found 1: `emailKey`'s appraiser→lender merge is UNPINNED — removing it leaves the frontend suite green at 2137/2137. Also: the processor-sourced re-ask should be her task (`route_ask` in `_add_ask`), and the round-1/page-break tests do not hold the processor rule (no library item is processor-first). **Follow-up `66f60857` reviewed: 1 finding** — both items are fixed and the LP-938 test rewrite is sound (it keeps both halves of the invariant and adds the item's own performer/option), but `_hers` reads `performers[0]` while `recipient_for` prefers the LO anywhere, so a `[processor, lo]` ask goes in the LO's email while its re-ask becomes her task; fix by making `_hers` the predicate `route_ask` already uses. **Second follow-up `b072d36b` reviewed: no findings** — the seam is closed (re-verified on the reviewer's own probe: both orders now give "LO", matching where `route_ask` leaves the item, with her own task untouched) |
| LP-943 Document display names | REVIEWED | `8af848c6` | the review section in [LP-943](../tickets/LP-943.md) (written, not yet committed) | none (emails and notes) | All 41 library types rendered and checked. Review found 2: `letter_of_explanation` and `letter_of_explanation_misc` share the display name "Letter of explanation" and the test does not check uniqueness ("(other)" fixes both); and `attention.py`'s `_document_label` still shows her "Borrower s authorization…", "Hoa statement", "Voe" from a helper whose docstring says "never the raw enum". (c) verified: no slug reaches a third party. **Follow-up `219ad4a6` reviewed: 1 finding** — both fixes verified on the reviewer's own probes, but the `attention.py` change gives `display_name` its first UNGATED caller (any of 166 catalogued types) while the cleanliness test covers the library's 41; five of the other 125 read badly, including `social_security_administration_ssa_89` -> "… ssa 89", the concrete member of the acronym gap. **Second follow-up `9212f734` reviewed: 1 finding** — all 166 now pass the rule with zero collisions (verified on the reviewer's own scan), but two more names are invisible to it: `business_existence_verification_cpa_ltr_bus_lic` → "… cpa ltr bus lic" and `prior_closing_disclosure_final_cd_from_purchase` → "… final cd …". The commit subject claims more than the test verifies, by exactly the amount the rule cannot see. **Third follow-up `ee28322b` reviewed: 1 finding, correcting the reviewer's own last claim** — "nothing else in the 166" was false because the reviewer's scan skipped capitalised words and `display_name` capitalises the first: `cpa_letter` renders "Cpa letter". Re-scanned with a positive control, exactly one remains, and one `ACRONYMS` entry (`cpa` → CPA) closes it. **Reviewer agrees LP-943 can close** |
| LP-944 Flaky tests | REVIEWED | `adf963aa` | the review section in [LP-944](../tickets/LP-944.md) (written, not yet committed) | none | Sweep checked and complete for its class (widened to every spelling; the `"ssn" not in body` hits are dict-KEY checks, not substrings). Review found 1: the ordering mechanism has a live member in app code — `condition_enrich.py:185` keys a dict on `text_fingerprint` (a sha256, non-unique index) from an unordered query, so which of two identical-text conditions enrichment matches is the planner's choice. `email_send.py:482` already carries this repo's doctrine for it |
| LP-945 Wording for the expert's two questions | REVIEWED | `058d0e7a` + `9392f19f` | | S3-11 checkbox | batch 3, the owner's list of 2026-09-30 | REVIEWED by the reviewer: no defect. Outward text traced surface by surface (emails, the package, the upload link which names nothing, the underwriter question); the sweep's result is right but its gate — type-level text only "when any item is asked" — misses `render_question`, which renders the type's short-or-name for any condition, and 19 of 56 types have no asked item. No VOE member today. IE-08: the owner's third route (regulator listing) has no document type so it cannot arrive, and the 120-day note states a checkable rule the item does not check. IE-08 unmapped is normal — 10 of 56 are |
| LP-946 Items with more than one performer | REVIEWED | `1233372a` + follow-up `247ddd14`, reviews `9041cb3e`, `c53e299b` | | reading box: parts under their item | batch 3; an item is split into parts, one per destination (`part_of_item_id`, migration `c4a8e2f1b637`); the LO relays to the borrower (STOP AND ASK 3) | REVIEWED by the reviewer: 1 finding. The split invariants hold for EVERY 1-, 2- and 3-performer combination (zero violations: no stranded ask, her task iff the processor is a performer, one item per destination), and split-before-route at all three call sites is load-bearing. FINDING: `update_item`'s re-split soft-deletes any non-DONE part, so a part whose ask was already SENT is deleted and the file stops showing a request that went out — reproduced, and against LP-940's own doctrine that a sent draft keeps its items. No test covers a re-edit after sending **Follow-up `247ddd14` reviewed: no findings** — only OPEN parts are deleted now, the test asserts its premise first, four mutations kill one test each, and both consequences verified independently (`move_prep_status` has no item gate, so a manual Ready works; the item DELETE endpoint has no frontend caller). Note recorded: re-adding a performer whose ask went out does NOT re-ask them |
| LP-947 One source for "waiting on" | REVIEWED | `8a9def53` + follow-up `679d598a` + note `b542c89c`, reviews `c53e299b`, `bb5211ff` | | detail sheet's "Becomes …" line | batch 3; the server sends `waiting_on_when_sent` with each condition, computed by the rule its send applies; the client's `WAITING_ON` and its drift check are deleted | REVIEWED: no defect. The reviewer's first reading — that the prediction and the move disagree (0132: prediction broker, sending the title email gives title) — was checked before reporting and is NOT a bug: `becomes()` names a specific email, and for that email the two agree (measured). FINDING: the ticket claims "the ONE statement of the rule" but there are two predicates (`status in _OPEN_ASK` vs `option in _ASKS` + a sent draft) that coincide only on the named email, and `test_the_prediction_is_the_move` marks EVERY draft sent — the one configuration where they always agree — so it cannot see the difference it exists to prove. Deleting the client's WAITING_ON map closes the LP-942 cross-language open item **Follow-up `679d598a` reviewed: no findings** — `first_asked_owner` is ONE function run by both the move and the prediction (one send ahead), so the equivalence is structural rather than coincidental. The named-email coupling measured across all 11 fixture conditions: 0 disagreements. Three mutations kill, including the NOT_NEEDED survivor. Note: the skip is dead for the move and load-bearing for the prediction, because their item sources differ |
| LP-948 Four small defects | REVIEWED | `32bce190`, review `3737e346` | | draft dialog labels; S1-09 tie questions | batch 3; (a) labels not keys (STOP AND ASK 5); (b) code, then wording, a tie asked; (c) withdrawn parents filtered; (d) the assertion rewritten, a mutation shown failing | REVIEWED: no defects. All four fixed; (a) closes both key renderings from LP-943 plus a catch the reviewer missed (the item's own name carries the substituted figure), (b)'s new `questions` field has a renderer, (d)'s evidence is the right shape (the OLD assertion survives a mutation the new one catches). One finding: (a)'s `key.split(".")` rests on "no library key has a dot" (re-measured 0 of 52) and nothing pins it — one assertion, the `_COVERS_ITEMS` shape |
| LP-939 Real-model trial (script only) | REVIEWED | `ec44fae6`, review `3737e346` | | none | un-skipped in batch 3; `backend/scripts/condition-reading-trial.py` and its README; checked with `--no-model` on a fictional sheet (strings in the summary listed: codes, type ids, performers only); the owner runs it with the model |

## Stage 3A — acceptance (build prompt §6)

`backend/tests/conditions/test_stage3a_acceptance.py` runs on the fictional UWM round 1 with the AI
mocked. The expected table is written by hand from plan §6, not from the code's output. Status:
**REVIEWED** (build `b5480845`; the commit titled `Stage 3A acceptance review:`).

| §6 requirement | Result |
|---|---|
| items and who acts, the proposed option per code | **matches** all eleven rows. 7086's $27,148.22 is required less verified, by code; 0006 is the credit invoice 07/15, page 1; 0007 waits on 1228; 6178's item is dropped, with the push-back dates 09/30/2026 and 09/30/2026 |
| three drafts: borrower 7086, 6132, 6637; title/attorney 6637, 0132, 1947, 6378; LO 0132 | **matches**, plus the question on 6178 |
| 1582 and 0007 her tasks; 0006 in the file; 6178 push-back; 1228 lender; 0132 to confirm at 0.64 | **matches**; 0132 is the only reading that needs her, and it blocks the confirm |
| marking the three drafts sent moves exactly those conditions to Waiting on the right owner | **matches**: 7086, 6132, 6637 Borrower; 0132 LO; 1947, 6378 Title. 6178 stays To do until its own question is sent; every lender status stays Open |
| the same plan with the AI switched off | **matches after one fix**. The fallback gave 0132's disclosure to the LO alone, where §6 says "borrower + LO": a library item could name only one performer. Library items now take `performers` (DI-01 disclosure: borrower, LO), validated at load. The mutation that undoes it fails this test. Every fallback reading is marked to confirm (11 blockers) |
| after round 2, the six conditions seen again keep their plan | **matches** |

### Review of the acceptance (of `b5480845`)

**No findings.** Walked §6 row by row against the test's output, and checked the thing a hand-written
expectation puts at risk: that the table itself says what the plan says.

- **The transcription is faithful and complete.** `SECTION_6`'s eleven codes are exactly §6's eleven
  rows, in the same order, with nothing added or missing (compared mechanically). Every cell was read
  against the plan by hand: 1228 lender-doing-it, 7086's two `AS-10` items both to the borrower, 6637's
  borrower/title/borrower split, 6178 push-back, **0132's disclosure as borrower + LO**, 1947 title,
  1582 and 0007 her tasks, 0006 already in the file, 6378 to title. A test whose expectation is typed
  by hand is only as good as the typing, which is why this was checked first.
- **The test asserts §6's Result line too**, not only the per-code table: the draft recipients with
  their codes, the two tasks, 0006 ready, 1228 lender-doing-it, 0007's wait on 1228, 0006's link to
  "Credit invoice 07/15" page 1, and that no condition is left without a plan.
- **The fix is right, and the mutation proves which test earns it.** Reverting `_item_from_library` to
  the single performer fails `test_the_same_plan_with_the_ai_switched_off` — and only that one. The
  AI-on path still passes, because the model's reading widened the performer itself. The defect was
  therefore invisible from every test that existed, and only the fallback could show it: that is this
  acceptance test paying for itself on its first run.
- **The library guard holds.** Mutating the DATA rather than the code: `performers` naming an unknown
  value is refused, `performers` omitting the item's own `performer` is refused, and the shipped
  `[borrower, lo]` loads. (A first attempt of mine "passed" a case that should fail — I had picked an
  item whose own performer was already in the list. The guard was right and the probe was wrong.)
- **Leaving 6178's question unsent is the correct reading.** The plan's Done-when moves conditions when
  "the three drafts" are marked sent; the question is a fourth message, and LP-921's table moves a
  push-back only when the question itself is sent. `test_condition_drafts.py` covers that fourth send,
  so nothing is untested — the split is deliberate, not a gap.

**Counts:** backend **8637 passed, 1 failed, 8 skipped, 1 xfailed**, an exact match, the failure being
the named pre-existing one; ruff, format and mypy clean (561 files). No frontend change, so none run.

**The arithmetic of the count, for the next baseline.** 8631 after the LP-922 follow-up review
(`7b50d853`, the parent of this build) + 4 acceptance tests + 2 malformed-library cases = **8637**.




Each is reversible and stored as data where it can be. The reviewer does not reopen them.

| §8 question | Build against this |
|---|---|
| 1 Who orders what at UWM | Per-lender setting (S3-11 "Who does what"). UWM seed: the final inspection or appraisal update is ordered by the lender (so 1228 is "Lender is doing it"). Title updates, insurance and payoffs: we ask the party. Other lenders: nothing ticked. |
| 2 Does the LO approve borrower emails? | No in V1. The draft goes straight to the processor. Leave room for a later "LO reviews first" step, but don't build it. |
| 3 Processor certifications | Not in V1. "I'll do it" is done only when she marks the task done, and a document item also needs a linked document. No certification text is generated. |
| 4 Where does the note per condition go? | Both: it is editable in the package (S3-10), included in the download, and copied with "Copy all notes". Per-lender fields: UWM note; Sun West comment + Name of Source + Date Verified. |
| 5 UWM Underwriting+ | The file-level switch "Lender is processing this file" is built. It defaults to off for every lender. The UWM "new files default" setting is unticked (S3-11). |
| 6 Library review | Build LP-918 as data, and also write `docs/phases/phase4.5-library-review.md`: the top 20 types as a table the product owner can mark up (type, items, who, documents, checks, rule, default plan). The ticket is REVIEWED when the code and data pass review. The owner's sign-off is tracked as a separate open item. It does not block later tickets, which use the library as it stands. |

Also fixed, from the screens:

- The reading confidence bar is **0.75**, stored as a setting (0.64 is below it; 0.86 and above pass).
- The borrower email is due **4 business days** after the plan is confirmed: 08/28 gives Thursday 09/03.
  It is editable in the draft.
- The Stage 3 package lives on the **Conditions tab**. The Lender package tab stays Phase 6's placeholder.
- "Lender is doing it" and "Information only" are **plan options** shown with Stage 2's display rule. They
  are not new `prep_status` values (plan §4a change 12).

## Stage 3B — acceptance (build prompt §6)

`backend/tests/conditions/test_stage3b_acceptance.py` runs round 1 of the fictional UWM file from
the statements arriving to the submit, in screen order, on one file. The statement PDFs are generated
in the test (real pages: 6, 5, 6, 12, and a 1-page invoice), so page counts and merges are measured. The
expected values are written by hand from build prompt §6 and the screens. Status: **REVIEWED**
(build `82c8f9b1`; the commit titled `Stage 3B acceptance review:`).

| §6 requirement | Result |
|---|---|
| the August statement with 5 of 6 pages cannot reach Ready (S3-07) | **matches**: "pages 1–5 of 6 — page 6 is missing"; 6132 and 7086 stay Waiting |
| a wrong-account statement is rejected with the reason | **matches**: "Capital One ending 4471 — the condition asks for ending 9912"; the item is not done |
| the $4,000.00 deposit on 08/21 is flagged against the $2,870.66 threshold (S3-08) | **matches**, and "Enough for closing" reads verified $41,914.42 against $38,210.40, **after fix 1** |
| accepting the evidence proposes the S3-09 figures and changes nothing until applied; applying goes through the stated-financials edits | **matches after fixes 2 and 3**: nothing proposed before the deposit is answered; the four S3-09 rows; the stated asset and the ratios unchanged until Apply, then $41,914.42 and 33.12% / 40.97%, with "Edited a stated asset" and "Applied 2 changes…" |
| DTI 44% → 46% flagged "re-run DU", 46% → 48% not | **matches** (the crossing reading; STOP AND ASK 2 since answered: correct, LP-936) |
| one named PDF and one note per ready condition (S3-10) | **matches after fixes 4 and 5**: 7086, 6132, 6178, 0006 in sheet order; `7086 - Assets.pdf` holds only the passing 12-page statement; 6178 has no file; an invented $45,000.00 note is refused; the zip has 3 PDFs and `notes.txt`, nothing missing |
| Mark submitted moves exactly those to Sent to lender, and the lender's track never moves | **matches**: 4 moves, 4 `condition_prep_moved` events, every other condition unchanged, every lender status Open |

### Review of the acceptance (of `82c8f9b1`)

**One finding, fixed: the scoping decision in (a) is right, and rested on nothing.** The three
judgments asked for, each checked against the data rather than the reasoning:

**(a) Condition-scoped propagation is correct today, and now pinned.** It holds because a large-deposit
finding can only be raised on an item whose checks include `covers_required_funds`, and **exactly one
library item declares that check** — `AS-10`'s `statements`. Measured: of 55 types, one. So every copy
of a given deposit lives under one condition and a condition-scoped sweep reaches all of them.

That is a fact about `types.yaml`, not a property of the code, and nothing guarded it. Give a second
type the same check — a reserves type, or a lender that splits the short-funds ask — and two conditions
can each carry a copy of the same deposit; answering it on one leaves the other open and holding, which
is fix 3's defect returning through a different door. **Fixed:**
`tests/conditions/test_deposit_findings_stay_on_one_item.py` pins the set with a positive control and
the reason written out. Mutation-checked: giving a second type the check fails it, and the library file
is restored byte-identical.

**(b) The `covers_required_funds` exception is right**, and for a sharper reason than "it is a sum".
Every other stored check is a property of the DOCUMENT — `right_account`, `right_period`,
`right_borrower`, `inside_lender_dates`, `all_pages`, `amount_matches` — so failing one means the paper
is wrong. `covers_required_funds` is the only one about the aggregate, so a real July statement short
on its own must stay evidence. Checked on seeded data: `no_large_deposit` is **not** among the stored
checks at all (it is a finding, and only 7086's item carries one), so an unexplained deposit does not
stop a statement counting as evidence — which is right, since the money is there whether or not it is
sourced.

**(c) Leaving the token alone and recording it is the right call** — it changes a rule reviewed in
LP-923, and reviewed behaviour should not move without the owner. Worth sharpening for whoever reads
that open item: a condition that is **Ready to send** while reading "Evidence failed a check — page 6"
is not a cosmetic wrinkle. `snapshot_findings/fingerprint.py` already makes the argument this repo
believes — *"a count that drifts for no reason teaches people to stop reading the tab at all"* — and a
count that stays high after the problem is fixed does the same damage from the other side. The decision
is the owner's; the stakes are trust in the number, not tidiness.

**The five fixes are one predicate, used in five places:** `condition_evidence` (the funds sum and
`_settle`), `figures_check` (`_funds_evidence`), and `condition_package` (the documents and the notes).
Confirmed by grep across `app/`, so the class is closed at one place rather than patched five times.

**Reverting the `is_evidence` flag was right too**, for the reason given: a row with `is_evidence`
false always has `failed` true, so the filter sat behind an unreachable branch. Dead code that looks
like a guard is worse than no code.

**Counts:** backend **8691 passed, 1 failed** — their 8689 plus this review's 2; the failure is the
named pre-existing one. ruff, format and mypy clean (567 files). No frontend change in the commit, so
none run.

**What the acceptance test found: one class, "a rejected statement treated as evidence", in five
places.** Each fix has a test at its own layer, and a mutation undoing it fails that test:
1. **The funds sum** (`_statements_for_item`) added every statement checked against the item. A ··4471
   upload rejected on "right account" made 7086's check read "verified $83,828.84".
2. **The figures check** (`_funds_evidence`) did the same, and proposed $83,828.84 as verified assets.
3. **An answer reached one copy of a deposit.** The rejected 5-page August showed the same 08/21
   $4,000.00 deposit; she explained it on the complete statement, and the copy kept 7086 at Waiting
   with nothing left to answer. An answer now reaches the same deposit (the same account, date and
   amount) on the condition's other statements, and the event names them (`also_answered_on`).
4. **A finding on a rejected statement held the condition** (`_settle`). Another account's statement
   with its own deposit kept 7086 Waiting. Only findings on documents that are evidence hold it now.
5. **The package's documents** took only rows with every check passed. That excluded a real July
   statement whose only failure is "covers required funds" on its own, so 7086 would have gone to the
   lender with August alone. The package's note also said "deposit sourced" once per copy.

All five now ask one predicate, `counts_as_evidence`: accepted by her, or failing no check but the funds
sum. New tests: 3 in `test_condition_evidence.py`, 2 in `test_condition_package.py`, 1 in
`test_figures_check.py`. There were 8 mutations. The one that survived first (the package note's
filter, masked by the de-duplication) is killed by a deposit explained only on a rejected statement.

**Re-shot after the fixes:** S3-07, S3-08, S3-09 and S3-12 differ from their committed shots only
behind the drawers or below the fold. The difference is LP-925's package bar ("1 condition ready to
send · Build package"), which the LP-923 and LP-924 shots predate (**D12**). S3-08's list also shows
6132's "Evidence checked" where the older shot had "—". S3-10 is byte-identical.

**Verification on the finished tree:** backend 8689 passed, 1 failed (the named sonnet test), 8
skipped, 1 xfailed. ruff, format and mypy (567 files) are clean. No frontend change.

## Stage 3 — tests that already failed before Stage 3

Named so a later ticket is not blamed for them (baseline at `840df131`):

- `backend/tests/ai/test_provider_selection_b1.py::test_a_sonnet_reasoning_id_cannot_survive_boot` —
  this machine's `backend/.env` sets its own `ANTHROPIC_MODEL_*` values, so the test's premise fails here.
- ~~`conditions-screens.test.tsx` › "offers a way out once the round is stranded"~~ — **FIXED in
  LP-925**: the fixture was exactly 600,000 ms old against a strict `>`, now eleven minutes. Confirmed
  by the LP-925 review: 15/15 three times at file scope, where it failed 4/4 before; the frontend suite
  is fully green for the first time this stage.
- ~~`backend/tests/conditions/test_condition_evidence.py::test_the_reask_goes_into_a_new_borrower_email`~~ — **FIXED in [LP-944](../tickets/LP-944.md)** (the cause measured and removed; three clean full runs). Originally:
  **intermittent, seen once in three full runs** by the LP-937 review. It passes alone, passes with its
  module (22/22), and passes right after the sonnet test; a third identical fixed-order run was clean.
  Not caused by LP-937 and not the inbox-token flake below. Recorded so the next ticket is not blamed.
- ~~`backend/tests/services/test_timeline_lp812.py::test_the_timeline_never_carries_a_body`~~ — **FIXED in [LP-944](../tickets/LP-944.md)**. Originally:
  **intermittent, seen once in two full runs** by the LP-940 review. It passes alone, passes with its
  module (23/23), and passes when run straight after the withdrawal tests, which rules out the one
  interaction that would have mattered (LP-940's new event carries her free-text reason, and this test is
  the guard against a timeline row carrying a body). A second identical full run was clean.
- **THREE tests now fail once each in a full run and pass in isolation** (the reask email, this timeline
  one, and — separately — the randomised inbox token, which is understood). Two unexplained ones with the
  same signature are more likely one shared cause in the suite's shared state than two independent flaky
  tests. Worth someone reproducing under `-p no:randomly` with `--lf` rather than adding a fourth line
  here next time.
- ~~`backend/tests/services/test_loan_file_ids.py::test_inbox_token_is_independent_of_display_id`~~ — **FIXED in [LP-944](../tickets/LP-944.md)** (the cause measured and removed; three clean full runs). Originally:
  **randomised, and it fails about once in a thousand runs** (measured by the LP-922 review: 2 trips in
  2000 simulated runs, 0.100%). It draws 1000 display ids and asserts the 4-character code is not a
  SUBSTRING of that iteration's inbox token; both are random, so chance alone produces a hit
  (`RAKSTDzq1DNBKVL5PyKWmQ` contains `AKST`). Nothing to do with the token being derived from the
  display id, which is what the test is for. It surfaced in the LP-922 review's suite run and is
  recorded here so the next ticket is not blamed for it. The fix belongs in its own change: assert
  independence by generating two tokens for one display id rather than by substring.

## Stage 3 — STOP AND ASK

| # | Where | Question | Reading taken (never idle) |
|---|---|---|---|
| 1 | plan §5 LP-922 "The AI polishes the wording and does not invent new requests" | Should condition emails get an AI polish pass? | **Answered by the product owner, 2026-09-29: yes, as a button.** The AI's version is shown as a proposal. A changed or dropped fact is shown with a warning, not refused. It applies to every draft and is always on. Built as the LP-922 follow-up (ADR-413, [LP-922](../tickets/LP-922.md) "Follow-up"). The reading first taken (no pass) is superseded. |
| 2 | plan §2.3 and §5 LP-924 (B3-2-10) against LP-924's own **Done when** | Is DU resubmission required when the DTI *is* above 45%, or only when it *crosses* 45% from at or under it? | **Answered by the product owner, 2026-09-29: the crossing reading is correct.** B3-2-10 reads "the DTI ratio recalculated by the lender to now exceed 45%, or increase by 3 percentage points or more (if the recalculated DTI ratio is 50% or less)", with the table 35→40 yes, 44→46 yes, 46→48 no, 46→50 yes. She added a limb: a recalculated DTI over 50% always flags, and the 3-point limb applies only at 50% or less. Built in [LP-936](../tickets/LP-936.md), all four rows and 50→51 pinned. The first reading (LP-924's) stands. |
| 3 | the owner's LP-946 ("every outside performer gets the ask in their own draft") against plan §6 and the reviewed Stage 3A acceptance (0132's `[borrower, lo]` disclosure goes in the LO email only) | Does the borrower on a borrower + LO item get their own email too? | **Reading taken: no.** The LO relays to the borrower (plan §6, the acceptance test), so `[borrower, lo]` stays one ask in the LO's email; every other combination is split, each outside performer in their own draft and her task if she is one. Built in [LP-946](../tickets/LP-946.md). If the borrower should also be emailed directly, it is the one line `relayed` in `destinations`. |
| 4 | the LP-946 review: a part whose ask went out is now kept when she removes its performer | Does a kept part still block the condition from reaching Ready to send? | **Reading taken: yes, it blocks the automatic move.** Someone was asked and has not answered, and the record says so; `_settle` counts it like any live item. She is never stranded: a manual move to Ready is allowed from To do or Waiting with no item gate. The alternatives are dimming it like a withdrawal or marking it not needed when its performer is removed. There is no UI today to remove a part by hand (the item DELETE endpoint has no frontend caller). |
| 5 | the owner's LP-948 (a) "labels, never internal item keys" against the S3-04 mock's "Earnest money: source and clearance", whose words are library item keys | Should a library item's key stand as its short word in the partial label? | **Reading taken: no, the owner's words are literal.** An item is named by its library label, else its own name, so the line reads "Earnest money: source of the earnest money and clearance". The mock's shorter words are one line in `item_words`, a library key for a library item and a name only for generated keys. Built in [LP-948](../tickets/LP-948.md). |

## Stage 3 — open items (not blocking)

- ~~**After a withdrawal is undone, her reason is on no screen**~~ — **decided and built in [LP-941](../tickets/LP-941.md)**:
  the history line carries the reason, and Undo adds "Withdrawal undone". Originally (LP-940 review): The Withdrawn row is gone
  and the history line ("Withdrawn as entered in error") never carried the reason; it stays in the event's
  detail. If "stays in the history" meant she can see later why, the history line should carry it. The
  owner's call.
- **Child-table queries that do not filter the parent condition** (LP-940 review). **The named member is
  fixed in LP-948 (c)**: `_items_by_condition` joins the parent. The CLASS stays open: other queries on
  child tables were not censused in LP-948, whose scope was the one query. Originally: `_items_by_condition`
  returns a withdrawn condition's items. Safe today because every caller keys in by a condition that is on
  no list; a caller that iterates the map would show them.

- ~~**A failed upload keeps saying so after a better document has done its item**~~ — **decided by the
  owner (2026-09-29) and built in [LP-937](../tickets/LP-937.md)**. Once a passing document has done
  the item, the earlier failures stop counting in "Failed a check" and stop showing in the Next step.
  They stay in the history, and on the sheet as "Replaced by <document>".

- ~~**A superseded card can hide the finding that is holding its condition**~~ — **fixed in the LP-937
  follow-up**: findings are hidden on replaced rows only (`replaced`, set by the server), and the Next
  step skips only those. Found by the LP-937 review; originally: `_settle` holds a condition on an open
  finding carried by any row that `counts_as_evidence`, which includes a statement whose only failed check is "Enough for closing"; LP-937 supersedes that
  same row, and the sheet renders none of a superseded row's findings. So an unexplained deposit on the
  earlier statement holds the condition at Waiting with no way to answer it, while the list still says
  "Large deposit needs sourcing". The Stage 3B dead end through the other door. The fix follows from
  LP-937's own reasoning — hide findings on the "Replaced by" branch only, since a row that is still
  evidence is a row whose findings still count. Reproduction and detail in
  [LP-937](../tickets/LP-937.md) "Review".

- ~~**A submitted package's stored rows can claim a condition it did not send**~~ — **fixed in the LP-940
  follow-up** (submit freezes exactly the rows it sends; verified on the reviewer's own sequence — the row
  is gone from the record, `_submitted_on` returns None, and the second withdrawal succeeds). Found by the
  LP-940 review; originally open. `submit` set `status` and `submitted_at` but never assigns `package.rows`, though its
  docstring says "the rows frozen as the record". So a hand-added condition withdrawn while the package was
  BUILT stays in the stored rows once it is submitted: `live_rows` correctly keeps it out of what is sent,
  but afterwards `_submitted_on` reads the stale row, the withdrawal refusal tells her *"It went to the
  lender in the package submitted on <date>"* (false), and the Undo becomes one-way — she can restore it
  but never withdraw it again. Reproduced end to end. Fix: freeze `await live_rows(...)` into
  `package.rows` at submission, which is what the docstring already claims. Detail in
  [LP-940](../tickets/LP-940.md) "Review".

- ~~**`emailKey`'s appraiser→lender merge is unpinned**~~ — **pinned in LP-942's follow-up** (and the
  client's `WAITING_ON` for the appraiser corrected to the lender). Found by the LP-942 review; originally open. The merge makes
  an appraiser ask and a lender ask count as ONE recipient, which is what stops the sentence reading
  "lender + lender emails". Measured: removing the branch from `emailKey` leaves the whole frontend suite
  green (2137/2137), because the only appraiser test asserts `EMAIL_WORD` and the item note and never
  reaches `askRecipients`' dedupe. One test on `askRecipients` with both items closes it.

- ~~**A re-ask sourced from her own task still asks the borrower**~~ — **fixed in LP-942's follow-up** (her own item's re-ask is her task). Originally found by the LP-942 review, open.
  `_takes` admits a document to an `i_will_do_it` item, so her task (IE-03's `call`, IE-06's `wvoe`, both
  processor performers with checks) can carry a failed document and offer a re-ask; `_add_ask` then sees
  `recipient_for(source) is None` and falls back to the borrower, who cannot act on a verbal VOE she made
  outside the window. Under the owner's LP-942 rule it should be her task: call `route_ask` on the item
  `_add_ask` creates, which also makes `route_ask`'s docstring true ("called wherever an item is made or
  edited" — `_add_ask` makes items and does not call it).

- ~~**`_hers` and `recipient_for` disagree about precedence**~~ — **fixed in LP-942's second follow-up**
  (`_hers` is processor-led AND in no email, `route_ask`'s rule). Found by the LP-942 follow-up review; originally open,
  low stakes. `_hers` reads `performers[0]`; `recipient_for` prefers the LO wherever it appears. So a
  `[processor, lo]` ask stays an ask in the LO's email (`route_ask` leaves it alone) while its re-ask
  becomes her task — and `[lo, processor]`'s re-ask follows the LO, so the re-ask's destination flips on
  performer order while the original ask's does not. The card and the item still agree, so this is NOT
  LP-940's divergence returning. Fix: make `_hers` the predicate `route_ask` already uses —
  `recipient_for(item) is None and performers[0] is PROCESSOR` — so three functions share one rule.
  Reachable only via `update_item`. Detail in [LP-942](../tickets/LP-942.md) "Review of the follow-up".

- ~~**The server's `WAITING_ON` and the client's are two statements of one rule, unpinned**~~ — **removed
  in [LP-947](../tickets/LP-947.md)**: the server sends the value and the client renders it. Same review,
  originally open, low stakes. They agree on every entry now (verified entry by entry: `hoa`, `employer` and
  `other_party` are `UNKNOWN` on both sides, so the appraiser was the only drift), but nothing holds them
  together across the language boundary, and they have drifted once. Contrast `_RECIPIENT` /
  `_RECIPIENT_ORDER`, pinned the same round because both live in Python. **Deliberately NOT guarded by a
  mirror test** (reviewer, LP-942 second follow-up): a drift is self-revealing — the client's map is a
  prediction and the server's is the fact, so a disagreement shows up as a wrong sentence on the next
  click — and a mirror test would freeze the duplication rather than remove it. The proper fix, if it is
  ever worth one, is the server sending the `waiting_on` it will set, so the client renders a value
  instead of recomputing the rule.

- ~~**Two document types share one display name, unchecked**~~ — **fixed in LP-943's follow-up** ("Letter of
  explanation (other)", and a uniqueness test). Found by the LP-943 review; originally open.
  `letter_of_explanation` and `letter_of_explanation_misc` both render "Letter of explanation"; both are on
  mapped sheets (CR-02 UWM 5868/7383 and CR-05; CR-12 Champions 245), so one file can carry two conditions
  asking for the same-named document and a package note cannot tell them apart. Cleanliness says nothing
  about uniqueness, so the test written to catch bad names missed it. Fix: name `_misc` "Letter of
  explanation (other)" — matching its parenthesised siblings — and add a uniqueness guard with an
  allow-list of deliberate duplicates.

- ~~**`attention.py` shows the processor the strings LP-943 removes**~~ — **fixed in LP-943's follow-up**
  (it reads `display_name`). Same review; originally open.
  `_document_label` is `document_type.replace("_", " ").capitalize()` under a docstring reading "A
  processor's name for the document, never the raw enum": her attention list says "Borrower s authorization
  for counseling", "Hoa statement", "Voe", "Ira 401k". Outside the owner's words ("emails and notes") since
  it is her screen, but a one-line substitution to `display_name`, and leaving it means the app spells one
  document two ways in two panels.

- ~~**The display-name guarantee covers 41 types; `attention.py` calls it on 166**~~ — **fixed in LP-943's second
  follow-up** (the tests run over the whole catalogue; the five named). Found by the LP-943
  follow-up review, open. `_document_label` names any FAILED or stalest document (`attention.py:160, 169`)
  with no library gating, while the cleanliness test is parametrised over the library's 41. Measured over
  all 166, five read badly: `social_security_administration_ssa_89` → "Social security administration ssa
  89" (**`ssa` is the concrete member of the acronym gap** — an acronym outside `ACRONYMS` is invisible to
  the rule), `k_1_shareholder_profit_and_loss_transcripts` → "K 1 …", `k1_statement` → "K1 statement",
  `form_4506c` → "Form 4506c", `form_4506t_request_for_transcript` → "Form 4506t …". Not a regression — the
  old `replace/capitalize` was the same or worse — but the commit routed a 41-type guarantee to a 166-type
  surface. Fix, with the blast radius measured: parametrise cleanliness over `CATALOG`, add `ssa` to
  `ACRONYMS`, name those four explicitly; exactly 5 of 166 fail, and collisions across all 166 are zero so
  the uniqueness test can widen for free. Detail in [LP-943](../tickets/LP-943.md) "Review of the
  follow-up".

- ~~**Item KEYS are rendered with `replace("_", " ")` in two processor-facing places**~~ — **fixed in
  [LP-948](../tickets/LP-948.md) (a)**: `item_words` replaced both. Same review, originally open,
  low stakes and a different vocabulary from document types. `condition_drafts.condition_label` (the draft
  dialog's side column) and the "Other drafts this round" summary render item keys that way, so a generated
  re-ask key shows as "6132 reask 3f2a9b1c".

- ~~**Two catalogued names are still unreadable, and no rule can catch them**~~ — **named in LP-943's third
  follow-up** ("Prior Closing Disclosure (final CD from the purchase)", and a neutral "Business existence
  verification"; the second's wording is still for the domain expert). Originally — found by the LP-943
  second-follow-up review, open. `business_existence_verification_cpa_ltr_bus_lic` renders "Business
  existence verification cpa ltr bus lic" and `prior_closing_disclosure_final_cd_from_purchase` renders
  "Prior closing disclosure final cd from purchase"; both pass the widened cleanliness rule because `cpa`,
  `ltr`, `bus`, `lic` and `cd` are not in `ACRONYMS`, and both are reachable through `attention.py`, whose
  domain is the whole catalogue. So "every catalogued document type has a clean name" is stronger than what
  the test verifies — the accurate claim is "clean BY THE RULE". The second is straightforward ("Prior
  Closing Disclosure (final CD from the purchase)"); the first is a compound catch-all (business existence
  by a CPA letter OR a business licence) and is a domain-wording call, so it belongs with the Verbal VOE
  question below. A human pass over the 166 is the only mechanism that finds these; the reviewer did one and
  found nothing else.

- ~~**`cpa_letter` renders "Cpa letter"**~~ — **fixed at LP-943's close** (`cpa` in `ACRONYMS`: "CPA letter", pinned by name). Originally found by the LP-943 third-follow-up review, open, one line.
  `cpa` is not in `ACRONYMS`, so the rule cannot see it; adding `cpa` → `"CPA"` gives "CPA letter" (verified).
  It survived the previous review because THAT review's scan only looked at lowercase words, and
  `display_name` capitalises the first — an absence claim the reviewer made and has corrected. The re-scan,
  with a positive control this time, found exactly this one across all 166.

- ~~**"Verbal VOE" and "Verification of employment (VOE)" are inconsistent**~~ — **answered by the owner
  and built in [LP-945](../tickets/LP-945.md)**: spelled out wherever a borrower or third party reads it. Originally same review, for the
  DOMAIN EXPERT rather than either session. One of the pair expands the acronym and the other does not;
  "verbal verification of employment" is the agency's own phrasing (B3-3.1-04), so expanding both is
  probably right, but it is a mortgage-wording call and CLAUDE.md says to flag rather than guess.

- ~~**`condition_enrich` lets the query planner pick between identical-text conditions**~~ — **fixed in
  [LP-948](../tickets/LP-948.md) (b)**: both sites go through `_choose`, and a tie is asked, not picked. The
  dict cited below no longer exists. Found by the LP-944 review, originally open. `condition_enrich.py:185` builds `{c.text_fingerprint: c for c in existing}` from a
  query with no `ORDER BY`; `text_fingerprint` is a sha256 with only a non-unique index
  (`ix_conditions_file_fingerprint`), so two conditions with identical verbatim text on one file share a
  key and the LAST row wins — whichever the planner returned. The same mechanism LP-944 fixed in `_drafts`,
  and the third site of a class this repo already has doctrine for: `email_send.py:482`, after two connected
  mailboxes made the sending identity undefined, records that "ordering does not decide the product
  question; it makes the answer reproducible while somebody decides." Fix: order the query. Detail in
  [LP-944](../tickets/LP-944.md) "Review".

- ~~**`test_insurance_wiring.py:63` asserts something that cannot fail**~~ — **fixed in
  [LP-948](../tickets/LP-948.md) (d)**, with the mutation the old assertion survives and the new one
  catches. Same review, originally open, one line.
  `assert "1200" in reason and "12" in reason`: the second conjunct holds whenever the first does, because
  "1200" contains "12". Not flaky — vacuous. It reads as "the reason names the divisor" and asserts nothing;
  assert the division (`"÷ 12"`) instead of the digits.

- **The outward-text sweep's gate is narrower than the surface** — found by the LP-945 review, open, no
  member today. `render_question` renders `library_type.short or library_type.name` for any condition with
  an underwriter question, but the sweep reaches type-level text only "when any item is asked", and 19 of
  56 types have no asked item (IE-03 and IE-06 among them — the two that keep "VOE"). Verified that no
  type's short, name or why says VOE today, so the result is right; dropping that gate for the two
  type-level fields makes the guard cover the surface it exists for.

- **IE-08's third route cannot arrive, and its 120-day rule is unchecked** — found by the same review, open,
  for the OWNER. The ask offers "CPA letter, business licence, or regulator listing", but the item's
  documents are the first two plus the compound type; a regulator listing classifies as
  `miscellaneous_document` (the catch-all), which is not listed, so `_takes` refuses it. That is the same
  question as the performer: a listing is what SHE checks, and under LP-942 an ask addressed to her is her
  task. Separately, the owner's note states "within 120 calendar days before the note date" and the item
  declares no checks, so nothing enforces it — IE-03 has `inside_voe_window` for that shape. (Having no
  checks is normal: 18 of 52 items have none.)

- ~~**A re-edit deletes an ask that was already sent**~~ — **fixed in LP-946's follow-up**: a re-edit
  removes only parts never asked (OPEN), keeps REQUESTED, RECEIVED and DONE ones, and does not split a kept
  part out again. Found by the LP-946 review; originally open. `update_item` re-splits by soft-deleting every part that is not DONE; a
  part whose email has been sent is REQUESTED, not DONE, so it goes. Reproduced: `source` [borrower,
  employer] splits, the employer's email is marked sent (part REQUESTED with a draft_id), she re-edits to
  [borrower], and the part is soft-deleted — the employer holds an email asking for something the file no
  longer shows, and a document arriving from them cannot link, since `_takes` refuses a deleted item. This
  contradicts LP-940's own doctrine, that `_leave_unsent_drafts` unlinks items only from UNSENT drafts
  because "a SENT draft is history and keeps its items", and `update_item`'s own rule that a DONE part is
  kept "as the record of what arrived" — a part that was ASKED is the record of what was requested. No test
  covers a re-edit after sending. Detail in [LP-946](../tickets/LP-946.md) "Review".

- **What the sheet should do with a kept part whose performer was removed** — raised by the same review,
  for the OWNER. The reading taken meanwhile is STOP AND ASK 4. Once a sent part is kept rather than deleted, it is no longer a live ask for anyone but is
  the record of one that went out: dim it like a withdrawal with a reason, or leave it for her to mark done
  by hand. A product question, not a code one.

- ~~**The "waiting on" prediction and the move are two predicates, and the test cannot tell**~~ — **fixed in
  LP-947's follow-up**: both call `first_asked_owner`, and the named-email boundary is tested. Found by the
  LP-947 review, open. `waiting_on_when_sent` selects the first item whose STATUS is an open ask;
  `_wait_on_first_asked` selects the first whose OPTION is an ask AND whose draft has been SENT. Measured on
  0132 they give different answers (broker vs title) on a partial send. That is NOT a user-visible bug —
  `becomes()` names a specific email and the two agree for that email, verified by marking exactly that one
  sent — but the ticket claims "the ONE statement of the rule", and the coincidence is load-bearing and
  unrecorded. `test_the_prediction_is_the_move` marks EVERY draft sent, the one configuration where the two
  predicates always pick the same item, so it is blind to the difference it exists to prove. Close it either
  by having the prediction call the move's rule with "this draft treated as sent", or by testing the
  boundary: two unsent drafts, mark the NAMED one sent, assert the predicted owner. Detail in
  [LP-947](../tickets/LP-947.md) "Review".

- **Which email the "becomes" sentence names is derived twice, once per language** — found by the LP-947
  follow-up review, open, no drift today. The server's `named` and the client's `askRecipients(...)[0]` must
  pick the same item for the sentence and its value to agree; measured across all 11 fixture conditions with
  **0 disagreements**, and both walk the same ordered payload skipping dropped, done and non-ask items.
  Nothing pins them. **Deliberately not guarded by a mirror test**, on the same reasoning as the LP-942
  `WAITING_ON` pair: a mirror freezes the duplication rather than removing it, and a drift here is visible
  (the sentence would name one email while the status named another). The durable fix is the server sending
  WHICH email is named, so the client renders both halves instead of deriving one.

- **A query with no ORDER BY that feeds a single-row pick is a CLASS, now four times** — raised by the
  LP-948 review, open, for a convention rather than a fix. The instances, each found after something looked
  wrong and each fixed in isolation: `email_send.py`'s mailbox; `condition_import._existing_conditions`
  (`possible_match` changed from run to run); `condition_drafts._drafts` (LP-944's flaky test);
  `condition_enrich`'s fingerprint dict (LP-948 b, where a tie is now asked). The LP-944 review counted 28
  unordered order-sensitive sites in `app/` (`.first()`, `[0]`, `[-1]`, `{key: row for row in …}`),
  nearly all benign today and none guarded. Proposed: write the rule where conventions live
  (`docs/project-structure.md`): any query whose result feeds one of those shapes needs an ORDER BY.

- ~~**`item_words` rests on "no library key contains a dot", unpinned**~~ — **pinned in LP-953** by
  `test_no_library_item_key_contains_a_dot`, now that `condition_matching.library_item_for` rests on the
  same split. Originally — found by the LP-948 review, open,
  one assertion. `base = item.key.split(".", 1)[0]` recovers a part's library item (LP-946 keys a part
  `<key>.<performer>`), and it is correct only because no library key has a dot — measured 0 of 52 by the
  builder and re-measured 0 of 52 by the reviewer. If one ever did, no library item would match and
  `item_words` would fall through to `in_sentence(item.name)`, which is the defect LP-948(a) exists to fix,
  silently returned for that item. The split is tested; the premise is not. Same tripwire shape as
  `_COVERS_ITEMS` and `_RECIPIENT` / `_RECIPIENT_ORDER`.

- **The product owner's sign-off on the library's top 20 types** (decision 6), once LP-918 has written
  `phase4.5-library-review.md`.

- ~~**AS-04's receipt item cannot verify the receipt it asks for**~~ — **fixed in the LP-938 follow-up**:
  a receipt's own `earnest_money_amount` is now its movement for "Amount matches". Found by the LP-938 review;
  originally open,
  pre-existing (not caused by LP-938). Its only check is `amount_matches`, which reads
  `Statement.movements`; `statement_from()` builds a Statement from bank-statement fields, so an
  `earnest_money_receipt` yields no movements and the check returns `not_run` — "no transactions could
  be read", a sentence that is false, since the extractor read `earnest_money_amount` fine. The item
  stops at Received and needs a manual accept every time. Fix: let `amount_matches` read a receipt's own
  amount for that document type, and correct the reason. Detail in [LP-938](../tickets/LP-938.md)
  "Review".

- ~~**`amount_matches` reads no amount off two more document types**~~ — **fixed in LP-938's second
  follow-up**: `OWN_AMOUNT` reads a gift letter's `gift_amount` and a deposit slip's `deposit_total`, as it
  does a receipt's. Found by the LP-938 follow-up review; originally latent. The follow-up fixed AS-04 by reading a receipt's own amount; the same gap remains
  for **AS-06's `gift_letter` item**, whose only document type is `gift_letter` and whose only check is
  `amount_matches`: `gift_amount` is extracted and never read, so the item can never pass and needs a
  manual accept every time — AS-04's defect in another item. AS-05's `explanation` is degraded, not dead:
  `bank_deposit_slip`'s `deposit_total` is equally unread, but that item also takes `bank_statement`.
  Latent because AS-05 and AS-06 are on no mapped sheet yet. Fix: generalise the branch to the document's
  own amount field, with `source` following. Detail in [LP-938](../tickets/LP-938.md) "Review of the
  follow-up".

- ~~**Nothing stops a library edit from letting a STATED amount satisfy `amount_matches`**~~ — **fixed
  structurally in LP-938's second follow-up**: a document's own amount is read only for the types in
  `OWN_AMOUNT` (receipt, gift letter, deposit slip), keyed by TYPE, so no library pairing can let
  `purchase_agreement` pass; `test_a_contracts_stated_deposit_never_satisfies_an_amount_check` pins it.
  Found by the same review; originally open. `purchase_agreement` extracts `earnest_money_amount`, and today no item pairs it
  with `amount_matches` (censused: only AS-11 `sale_evidence` lists it, checks `[signed_and_dated]`), so
  the code is safe by a fact about `types.yaml` that a comment records and nothing enforces. Pair the two
  and a contract's *stated* deposit would satisfy a check that exists to confirm *receipt*. Wants the
  tripwire shape of `test_deposit_findings_stay_on_one_item.py`.

- ~~**The re-ask calls a receipt, a gift letter and a deposit slip "A corrected the statement"**~~ —
  **fixed in LP-938's third follow-up** ("A corrected receipt"; and the re-ask now goes to the failed
  item's own asker: a receipt title sent is asked of title). Found by the LP-938 second-follow-up
  review; originally open. `reask` is newly reachable for those three types (before, their
  `amount_matches` was not_run and `reask` refuses when nothing failed), and `reask_name`'s fallback is
  `f"A corrected {what}{month} statement"`, where `what` collapses to "the" without a bank and last4. So
  the item name — the one the borrower or third party reads in the email — is both false about the
  document and ungrammatical. Pre-existing (`purchase_agreement` + `signed_and_dated` already produced
  it), widened here. The fix is nearly free: `Statement.source` already holds "receipt" / "gift letter" /
  "deposit slip", so use it in place of the literal. Fix the `source` unpack order at the same time — it
  is currently set before the `stated is not None` guard, which is unobservable only while `source` has no
  other reader. Detail in [LP-938](../tickets/LP-938.md) "Review of the second follow-up".

- ~~**`OWN_AMOUNT`'s keyset is not pinned**~~ — **fixed in LP-938's third follow-up**
  (`test_the_documents_that_read_their_own_amount_are_exactly_these`). Same review; originally open, low stakes. The guard against a stated
  amount confirming receipt is now structural and keyed by document type, which is right; but only
  `purchase_agreement` is pinned, by name. Adding a future stated-amount type to `OWN_AMOUNT` passes every
  test. This is where a keyset tripwire now belongs, in the shape
  `test_deposit_findings_stay_on_one_item.py` uses for `_COVERS_ITEMS`.

- ~~**A re-ask can be created for someone with no email, while the button says "borrower"**~~ — **fixed in
  LP-938's fourth follow-up** (one `recipient_for` call decides the destination and the label). Originally — found by the
  LP-938 third-follow-up review, open, introduced by that commit. `recipient_for` returns `None` for two
  different reasons and `reask_to` treats them alike: when the item is not an ask, `_add_ask` also defaults
  to the borrower and the label is true; but when the item IS an ask whose performer has no `_RECIPIENT`
  entry, `_add_ask` copies that performer, so the ask is created for (say) the processor while the button
  reads "to the borrower email" — and the new item's own `recipient_for` is `None` too, so it lands in no
  draft at all. Reachable by an ordinary edit: `edit_item` changes option and performers independently, and
  IE-03 `call` (UWM 1812) and IE-06 `wvoe` are `processor`-performer items that carry checks. Fix: gate
  `_add_ask` on `recipient_for(source) is not None` rather than on the option, so one call decides both and
  the label cannot disagree with the destination. Detail in [LP-938](../tickets/LP-938.md) "Review of the
  third follow-up".

- ~~**Three performers can be asked but have no email to be asked in**~~ — **decided and built in
  [LP-942](../tickets/LP-942.md)** (you: her task; the lender and the appraiser: the lender's draft).
  Originally: — same review, open, pre-existing and
  the root of the item above. `_RECIPIENT` covers 8 of the 11 `Performer` members: `processor`, `lender`
  and `appraiser` are absent, while `_THIRD_PARTIES` *includes* `appraiser` (the lender-processing switch
  flips appraiser items between `ask_third_party` and `lender_doing_it`) and the frontend's `EMAIL_WORD`
  has words for all three. So an appraiser ask lands in no draft today, silently.

- ~~**The re-ask still calls 21 live items' documents "a statement"**~~ — **fixed in LP-938's fourth
  follow-up** (a typed document with no statement facts is named by its type label). Originally — same review, open. `Statement.source`
  is only populated for `OWN_AMOUNT`'s three types, so `reask_name` names every other non-statement
  document a statement: censused at 29 items, 21 on mapped sheets, including IN-01 `declarations` (UWM
  6178, homeowners insurance — the insurance agent is asked for "a corrected statement"), ID-01 `id`
  (Champions 286, a driver's licence), DI-01 `disclosure` (UWM 0132) and TI-02 `report` (Champions 285).
  Not a regression: before the third follow-up all 32 said "A corrected *the* statement". Fix: both call
  sites hold the `Document`, so use `document.document_name` (what the card already prints) or
  `app/documents/naming.py`'s per-type stem, which cover all ~80 types.
- ~~**Five document-type labels are not English where a re-ask now prints them**~~ — **fixed in [LP-943](../tickets/LP-943.md)** (display names). Originally found by the LP-938
  fourth-follow-up review, open, pre-existing in `document_label` and newly user-facing. Measured through
  the real extraction models: `borrower_s_authorization_for_counseling` renders "borrower **s**
  authorization for counseling" (the possessive becomes a stray letter; DI-04 `certificate`, Champions 34),
  `verbal_voe` renders "verbal **voe**" (IE-03 `call`, UWM 1812 — and this contradicts `document_label`'s
  own docstring, which maps `voe` explicitly *because* lower-case "voe" reads as a typo),
  `letter_of_explanation_asset` leaks its internal discriminator (AS-13 `letter`, UWM 6006),
  `government_issued_id` renders "id", and `drivers_license` renders "drivers license" (ID-01 `id`,
  Champions 286). Four of the five are on mapped sheets, so they are live. Fix: extend
  `_DOCUMENT_ACRONYMS` (or a display-name override beside it), and pin the class with a catalogue-wide
  test — no stray single-letter word, no trailing discriminator, no lower-case known acronym. Detail in
  [LP-938](../tickets/LP-938.md) "Review of the fourth follow-up".

- ~~**`document_label` now crosses a layer**~~ — **gone in LP-943**: condition services read `app/documents/display_names.py`. Originally — same review, open, cosmetic. `app/services/condition_evidence.py`
  is the first dependency from the conditions service on `app.verification.rule_engine`. The label has
  become shared user-facing vocabulary rather than rule-engine wording, so `app/documents/` (beside
  `catalog.py` and `naming.py`) is arguably its home; `docs/project-structure.md` is where that is decided.

- ~~**Screen deviations for the product owner to redraw: D1 to D12**~~ — **accepted as built by the
  owner, 2026-09-29; no redraw.** The list below stays as the record of where the build and the drawings
  differ.
- **A library `label` or `short` may carry a placeholder nothing fills** (LP-955 review, measured and
  left alone deliberately). `_wording` validates WHICH placeholders a wording field may name, but
  `label` and `short` never pass through `fill` (`condition_drafts.py:1241, 1658, 1670, 1677` use them
  raw), so a `{code}` in either would print **literally** on her screen. No value in `types.yaml` does
  it today — the only braces are in `email`, `why` and `question`, each filled by its own caller — and
  it pre-dates LP-955 by every placeholder name rather than the two that ticket added, so fixing it
  means narrowing fields batch 4 never touched. The LP-955 review added the hook it needs: `_wording`
  now takes the allowed set per field, so this is `allowed=frozenset()` for those two plus whatever
  the change breaks in the yaml.
- **S3-12 outside LP-921 (LP-921 visual check):** the list's status select is Stage 2's native select
  and carries no glyph where S3-12 draws one; the rail's Recent activity shows Stage 2's relative times
  ("5 days ago") where S3-12 prints "Aug 28, 5:02 PM". Neither is a Stage 3 change; both are for the
  product owner to decide.

## Stage 3 — what shipped

| Ticket | What | State |
|---|---|---|
| [LP-934](../tickets/LP-934.md) | the screens checked against the plan (7 mismatches, their resolutions); the visual-check harness (`scripts/visual-check/`) | reviewed |
| [LP-918](../tickets/LP-918.md) | the condition library: 55 types as reviewed YAML, citations only where the plan cites (ADR-409) | reviewed; the owner's top-20 sign-off open |
| [LP-919](../tickets/LP-919.md) | reading each condition: one model call per round, library fallback, her confirm (ADR-410); migration `b8963ab6b627` | reviewed |
| [LP-920](../tickets/LP-920.md) | the action plan: items, needs shared across conditions, confirm (ADR-411); migration `6d517ee261d7` | reviewed |
| [LP-921](../tickets/LP-921.md) | next-step options, the Next step column and the Stage 3 summary bar | reviewed |
| [LP-922](../tickets/LP-922.md) | drafts only: borrower, title/attorney, LO, question to the underwriter; mark as sent; Polish with AI (ADR-412, ADR-413); migrations `fccf8534a7cd`, `976c705e5637` | reviewed, with the follow-up |
| [LP-923](../tickets/LP-923.md) | evidence checked by code; the large-deposit finding (B3-4.2-02); accept anyway; re-ask (ADR-414); migration `52239e18fd5d` | reviewed |
| [LP-924](../tickets/LP-924.md) | the figures check and its DU re-run tolerances (B3-2-10), applied only by her (ADR-415) | reviewed, with the follow-up |
| [LP-925](../tickets/LP-925.md) | the condition package, Mark submitted, lender condition settings (ADR-416); migration `08828fa86ffc` | reviewed |
| Stage 3A / 3B acceptance | above in this file | reviewed |

Migrations added by Stage 3: `b8963ab6b627`, `6d517ee261d7`, `fccf8534a7cd`, `976c705e5637`,
`52239e18fd5d`, `08828fa86ffc` (**head**). ADRs: 409 to 416.

## Stage 3 — acceptance

- **Stage 3A** (`test_stage3a_acceptance.py`): plan §6's table on round 1, row by row. It needed one
  fix: a library item may name two performers (DI-01's disclosure: borrower and LO). Reviewed.
- **Stage 3B** (`test_stage3b_acceptance.py`): statements to submit on one file. It found one class of
  defect in five places (a rejected statement treated as evidence), fixed behind one predicate. The
  review pinned the premise of the deposit fix (one library item carries the funds check). Reviewed.

Both tables are in their sections above. How the screens were checked against them is in
[LP-935](../tickets/LP-935.md): the harness replays the acceptance steps through the same services, and
every screen was shot and walked. No test clicks through the UI end to end.

## Stage 3 — decisions taken without the product owner

The standing rule was: take the plan's reading, choose the option that never moves a status without her,
and record it. Each ticket keeps its own table. These are the ones she may want to overturn:

| Where | Question | What was chosen |
|---|---|---|
| [LP-918](../tickets/LP-918.md) #1, #4 | The plan's taxonomy appendix is in no branch | Our own ids in the Stage 1 spec's shape; about 40 types became 55 (every mapped code needs a type), bounded at 40 to 60 by a test |
| [LP-918](../tickets/LP-918.md) #2 | Which agency sections to cite | Only the plan's six sources; everything else says "lender requirement" rather than a section nobody checked |
| [LP-919](../tickets/LP-919.md) #1, #2 | What the model may supply; how a fallback reading is treated | Specifics yes, figures never (every amount must be in the lender's text); a library-only reading needs her confirm |
| [LP-920](../tickets/LP-920.md) #1 | Due dates | 4 business days on asks only; working back from the lender's dates is not built |
| [LP-921](../tickets/LP-921.md) #1, #2 | When a chosen step moves our status | At confirm, forward only, from To do; never over a move she made |
| [LP-922](../tickets/LP-922.md) #2 | Whose "Waiting on" a sent email sets | The first asked item's (ADR-412), which is S3-12's "Waiting on LO" for 0132 |
| [LP-922](../tickets/LP-922.md) #7 | The due date on an ask draft | Editable in the draft, an addition to S3-04 |
| [LP-923](../tickets/LP-923.md) | A re-ask: drafted by the app, or her button? | Her button (S3-07), never auto-drafted |
| [LP-924](../tickets/LP-924.md), [LP-936](../tickets/LP-936.md) | The 45% DU tolerance | The crossing reading, **confirmed by the owner** (STOP AND ASK 2, answered 2026-09-29); over 50% always flags, and the 3-point limb applies only at 50% or less |
| [LP-925](../tickets/LP-925.md) | A Ready prior-to-funding condition | It goes in the package (S3-10 packages 0006); the ones not yet ready go in the info line |
| [LP-925](../tickets/LP-925.md) | Lender settings | Their own admin routes, not the lender's PATCH, so saving them cannot touch other lender fields |
| Stage 3B acceptance | A rejected statement | Is not evidence (`counts_as_evidence`); an answer to a deposit reaches every copy of it on the condition |
| Stage 3B acceptance, [LP-937](../tickets/LP-937.md) | A superseded failed check | **Decided by the owner, 2026-09-29, and built (LP-937):** once a passing document has done the item, earlier failures for it stop counting and stop showing in the Next step; they stay in the history and on the sheet as "Replaced by <document>". A statement that failed only the funds total on its own is still evidence: it reads "Still evidence — enough for closing was met once <document> arrived", and its findings stay on the sheet, answerable, because they can still hold the condition (LP-937 follow-up; the first wording, "together with", was untrue for two statements of one account). The first reading ("left as it is") is superseded |

## Stage 3 — screen deviations (accepted as built, 2026-09-29)

**Accepted as built by the product owner, 2026-09-29: no redraw.** Every Must-match line the build made
untrue, and why. The reference PNGs are in
`docs/design/phase4.5-conditions/stage3/screens/`. The build's shots and the reviewer's are in `checks/`.

| # | Screen | The line | Why | Recorded in |
|---|---|---|---|---|
| D1 | S3-12 | "Failed a check 1 (red)" | It is **3**: the 5-page August statement answers 6132, 7086 and 6637's clearance, and a document is checked once for each item it answers (§4a change 2) | [LP-934](../tickets/LP-934.md), amended in [LP-923](../tickets/LP-923.md) |
| D2 | S3-12 | 7086's next step "Deposit explanation asked · 09/02" | 7086 also fails "All pages", and a failed check outranks the finding: "Evidence failed a check — page 6" | LP-934 |
| D3 | S3-09 | Activity "Evidence accepted for 7086 and 6178" | 6178 has no evidence items (§6); only 7086's evidence is accepted | LP-934 |
| D4 | S3-12 | Activity "3 emails marked sent" | Four were: three drafts and the question to the underwriter, each an event | LP-934 |
| D5 | S3-01 | "Statement showing check #1042 cleared" | No check number is in the lender's text on 08/28, and the reading invents nothing: "Statement showing the check cleared · Aug 2026" | [LP-919](../tickets/LP-919.md) |
| D6 | S3-01 | "Same Aug statement answers 6132" | One need covers both months and both conditions: "Same statement as 7086 and 6132 — asked for once" | [LP-920](../tickets/LP-920.md) |
| D7 | S3-05 | "6378 Loan number on checks" and its item 4 | 6378 is the general TI-04 Instruction to title; the item quotes the lender's own instruction | [LP-922](../tickets/LP-922.md) |
| D8 | S3-04, S3-05, S3-06 | The four dialog buttons | A fifth, **Polish with AI**, sits between Copy message and Mark as sent (her answer of 2026-09-29) | LP-922 |
| D9 | S3-08 | Right account, period and all pages as one check row | Each check is its own row with its own reason, as S3-07 draws them | [LP-923](../tickets/LP-923.md) |
| D10 | S3-10 | "26 pages", and the row order | The fixture's documents give 43 pages (7086 and 6132 share the 12-page statement), in the sheet's order (6178 before 0132) | [LP-925](../tickets/LP-925.md) |
| D11 | S3-11 | "2 files" / "1 file" seen | "Seen" counts the loan files carrying the code: truthfully 0 in the harness | LP-925 |
| D12 | S3-07, S3-08, S3-09, S3-12 | (none contradicted) | LP-925's package bar ("1 condition ready to send · Build package") appears whenever something is Ready, which those drawings predate | Stage 3B acceptance, above |

Also for her, outside any ticket's lines (LP-921): S3-12's status select is Stage 2's native select with
no glyph, and the rail shows relative times ("5 days ago") where S3-12 prints "Aug 28, 5:02 PM".

## Stage 3 — every screen, and how to open it

Unlike Stage 2's table, every screen here has been checked on screen, by both sessions. Run
`VISUAL_STATES="S3-xx" scripts/visual-check/run.sh all` (a scratch database, never the dev one). It
seeds the state through the same services the acceptance tests use, opens the page at 1600 px with the
clock set to the screen's moment, clicks what the screen needs open, and writes
`docs/design/phase4.5-conditions/stage3/checks/S3-xx-actual.png`.

| Screen | Ticket | State (the harness builds it) | Result |
|---|---|---|---|
| S3-01 condition items | LP-919, LP-920, LP-921 | 08/28, 4:41 PM, the plan confirmed at 4:40 PM; 6637's sheet open | **matches**, with D5 and D6 |
| S3-02 round plan | LP-920 | 08/28, 4:21 PM, the plan ready, not confirmed | **matches every line** |
| S3-03 confirm reading | LP-919 | 0132's reading at 0.64, its confirm dialog open from its sheet | **matches** |
| S3-04 borrower email | LP-922 | 08/28, 4:41 PM, confirmed at 4:40 PM; "Borrower · draft" open | **matches**, with D8 |
| S3-05 title email | LP-922 | "Title/attorney · draft" open | **matches**, with D7 and D8 |
| S3-06 underwriter question | LP-922 | "Question 6178 · draft" open | **matches**, with D8 |
| S3-07 evidence checked | LP-923 | 09/02, 9:30 AM; the 5-page August; 6132 open | **matches**; re-shot after the Stage 3B fixes, with D12 |
| S3-08 new finding | LP-923 | 09/02; July and August, 12 pages; 7086 open | **matches every line**, with D9; re-shot, D12 behind the drawer |
| S3-09 figures check | LP-924 | 09/08, 3:10 PM; the deposit explained, the declarations in the file | **matches every line**, with D3; re-shot, D12 below the panel |
| S3-10 package | LP-925 | 09/09, 5:46 PM; six Ready; the package built | **matches**, with D10. Its button row is below the 1016 px fold, so it is verified by `condition-package-panel.test.tsx` |
| S3-11 lender settings | LP-925 | Administration → Lenders → UWM, as the company's admin | **matches**, with D11 |
| S3-12 list with next steps | LP-921, LP-922, LP-923 | 09/02, 9:30 AM; the four sends of 08/28; the 5-page August | **matches**, with D1, D2, D4 and D12 |

**Not covered by any screen:** the clicks themselves as one run. Each is covered by its component test
and its route test, not by a browser test (see [LP-935](../tickets/LP-935.md)).

## Stage 3 — deferred, on purpose

- **LP-914 (board view)**, after Stage 3 (D1 of Stage 2).
- **Smart due dates** worked back from the lender's dates (lock expiry, close-by): asks get 4 business
  days ([LP-920](../tickets/LP-920.md) #1).
- **Re-asking the same deposit across conditions**: an answer reaches every copy on its condition. That
  is enough while one library item carries the funds check, which the review pinned
  (`test_deposit_findings_stay_on_one_item.py`).
- ~~**A superseded failed upload** still reads "failed a check" on a Ready condition~~ — decided and built
  in LP-937.
- **The note check's swap blindness** (the LP-925 review): a note that swaps two real figures passes,
  because the check is shared with the finding-prose path. It needs a ticket of its own.
- **No upload to any lender portal.** The package is downloaded and uploaded by her; Mark submitted is
  her statement that she did.
- **Owner sign-offs:** the library's top 20 (`phase4.5-library-review.md`, now generated from the library,
  LP-938). STOP AND ASK 2 was answered (LP-936) and the deviations accepted as built, both 2026-09-29.

## Stage 3 follow-ups (the owner's list of 2026-09-29)

| Ticket | Result | Commits |
|---|---|---|
| [LP-936](../tickets/LP-936.md) DU tolerance | **Done.** B3-2-10's table pinned (35→40, 44→46, 46→50 flag; 46→48 does not); over 50% always flags; the 3-point limb only at 50% or less. STOP AND ASK 2 closed; ADR-415 amended | `0c8090e6`, review `8014e5a8` |
| [LP-937](../tickets/LP-937.md) Superseded failures | **Done.** A failure whose item a later passing document did stops counting and stops showing in the Next step; it stays on the sheet as "Replaced by …". The follow-up keeps a still-evidence statement's deposit visible (`replaced`). ADR-414 amended | `770d2513`, `da6fbd19`, `247aab18`, reviews `c0837ace`, `e5ef4e65` |
| [LP-938](../tickets/LP-938.md) Library fixes | **Done.** AS-04's receipt takes `earnest_money_receipt`; the review table is generated from `types.yaml` and a test keeps them equal. Four follow-ups from the reviews: receipts, gift letters and deposit slips are checked by their own amount (`OWN_AMOUNT`, keyed by type so a contract's stated deposit never counts); a re-ask names the document and goes to whoever was asked | `37f5aa9f` … `341f9c54`, closing review `4370ad8b` |
| LP-939 Real-model trial | **Skipped for now** by the owner | — |
| [LP-940](../tickets/LP-940.md) Withdraw a hand-added condition | **Done.** Withdraw with a reason, a collapsed "Withdrawn (n)" section with Undo, refused for sheet conditions, a recorded verdict or a submitted package. The follow-up makes a submitted package record exactly what it sent. ADR-404 amended | `faea58ad`, `e8265768`, reviews `5cc5212f`, `c8af1e79` |
| Screen deviations D1–D12 | **Accepted as built**, no redraw | — |

**Left for the owner** (each in the open items above): the library's top-20 sign-off; after an Undo the
withdrawal reason is on no screen; `_RECIPIENT` has no email for the appraiser, the processor or the
lender; five `document_label` wordings that read badly to a third party (four on mapped sheets); the note
check's swap blindness; three intermittent tests that probably share one cause.

**Last full runs on the finished tree:** backend 8724 passed, 1 failed (the named sonnet test), 8 skipped,
1 xfailed. Frontend 2135 / 2135. ruff, format, mypy, biome, tsc and the build are clean.

## Stage 3 follow-ups, batch 2 (the owner's list of 2026-09-30)

| Ticket | Result | Commits |
|---|---|---|
| [LP-941](../tickets/LP-941.md) Withdrawal history | **Done.** The withdrawal line shows her reason; Undo adds "Withdrawal undone" and the reason stays visible. The reason is the one free-text field in the history's projection, by the owner's decision, guarded by kind | `44d9fbfa`, `83bcf04b`, review `1eadb8fe` |
| [LP-942](../tickets/LP-942.md) Asks with no email | **Done.** An ask to her is her task; the lender's asks and the appraiser's go into one lender draft per round, from the lender's contacts; appraiser asks say "Appraisal requests go through the lender" (appraiser independence). Two follow-ups: her own item's re-ask is her task, and one rule decides "hers" | `ac4f6d58`, `66f60857`, `b072d36b`, reviews `c659396f`, `6f78d3e4`, `b3d9978f` |
| [LP-943](../tickets/LP-943.md) Document display names | **Done.** A display name for every catalogued type, clean by the rule and unique across all 166, with the owner's five exact; used in re-asks, package notes and the attention panel | `8af848c6` … `a82eb5ac`, reviews `0f480e2f` … `c52345e0` |
| [LP-944](../tickets/LP-944.md) Flaky tests | **Done.** One cause, two mechanisms, each measured: random-substring absence assertions, and dict order from a query with no ORDER BY. Three sequential full runs clean | `adf963aa`, review (this commit's parent) |
| Note swap check | **Left in the backlog**, as the owner asked | — |

**Left for the owner** (each in the open items above):
- ~~**Domain wording, for the resident expert**~~ — **both answered by the owner, built in LP-945** (VOE spelled out for
  third parties; IE-08 with the owner's wording). Originally: "Verbal VOE" next to "Verification of employment (VOE)";
  and whether "Business existence verification" should name the CPA letter or the business licence.
- **Product questions:** ~~an item edited to [processor, borrower] routes as her task and nothing says the
  borrower was not emailed~~ (answered by the owner, built in LP-946: the borrower is emailed AND she has
  her task); ~~the server could send the "waiting on" hint so the client stops keeping its own copy~~
  (built in LP-947).
- ~~**Recorded defects, not built**~~ — **all four built in [LP-948](../tickets/LP-948.md)**: round
  matching by code, then wording, with a tie asked; the vacuous insurance assertion; item keys in the
  draft dialog; child-table queries that did not filter a withdrawn parent.
- The library's top-20 sign-off.

**Last full runs on the finished tree** (three, sequential): backend 8929 passed, 1 failed (the named sonnet
test, which fails every run from this machine's `.env`), 8 skipped, 1 xfailed. Frontend 2139 / 2139 at
LP-942, unchanged since. ruff, format, mypy, biome, tsc and the build are clean.

## Stage 3 follow-ups, batch 3 (the owner's list of 2026-09-30)

| Ticket | Result | Commits |
|---|---|---|
| [LP-945](../tickets/LP-945.md) Wording for the expert's two questions | **Done.** VOE spelled out wherever a borrower or third party reads it; business existence has its own type, IE-08, with a lender setting that makes it "Lender is doing it" | `058d0e7a`, `9392f19f`, reviews `d5fe76e2` |
| [LP-946](../tickets/LP-946.md) Items with more than one performer | **Done.** An item is split into parts, one per destination: every outside performer in their own draft, her task only if "you" is a performer, each part shown under its item. The follow-up keeps a part whose ask went out when she re-edits | `1233372a`, `247ddd14`, reviews `9041cb3e`, `c53e299b` |
| [LP-947](../tickets/LP-947.md) One source for "waiting on" | **Done.** The server sends who a condition will wait on once its next email is marked sent; the client's copy and its drift test are deleted. The follow-up makes the prediction run the move's own rule, one send ahead | `8a9def53`, `679d598a`, `b542c89c`, reviews `c53e299b`, `bb5211ff` |
| [LP-948](../tickets/LP-948.md) Four small defects | **Done.** (a) labels, never keys, in the draft dialog; (b) matching by code, then wording, and a tie is asked on S1-09, not picked; (c) a withdrawn condition's items are left out; (d) the assertion rewritten, with the old one shown passing a mutation the new one catches | `32bce190`, review `3737e346` |
| [LP-939](../tickets/LP-939.md) Real-model trial (script only) | **Script and README committed; the owner runs it.** Checked with `--no-model` on a fictional sheet; no sheets or outputs in the repo | `ec44fae6`, review `3737e346` |

**Left for the owner** (each in the open items or the STOP AND ASK table above):
- **STOP AND ASK 3 to 5**, readings taken:
  - the LO relays to the borrower, so [borrower, lo] stays one ask in the LO's email;
  - a kept part whose ask went out still blocks the automatic Ready (she can move it by hand);
  - "labels, never keys" is read literally, so 6637 reads "source of the earnest money and clearance",
    not the mock's "source and clearance".
- **Product questions:**
  - what the sheet shows for a kept part whose performer was removed (dim it, or mark it not needed);
  - re-adding a performer whose ask already went out does not re-ask them.
- **IE-08:** the regulator-listing route has no document type, and the 120-day rule is stated but not
  checked.
- **Recorded, not built:**
  - an ORDER BY convention for queries that feed a single-row pick (four instances so far);
  - pinning the "no library key has a dot" premise that `item_words` relies on;
  - the server sending which email the "Becomes …" sentence names;
  - the census of child-table queries that do not filter a withdrawn parent.
- **LP-939's real run**, with the configured model, on sheets outside the repo.

**Last full runs, uncontended** (one test database, announced between the two sessions after one collision
spoiled two runs):
- backend: 8953 passed, 1 failed (the sonnet test, which fails every run from this machine's `.env`),
  8 skipped, 1 xfailed, at `32bce190`, matched by the reviewer's own run;
- frontend: 2142 / 2142, and the build passed;
- ruff, format, mypy, biome and tsc are clean.

## Stage 3 follow-ups, batch 4 (the staging trial of 2026-09-30)

**Source:** [`phase4.5-staging-trial-2026-09-30.md`](phase4.5-staging-trial-2026-09-30.md) and the owner's
batch-4 list. Builder `mortgageboss-ai-a1`; reviewer `mortgageboss-ai-cf` (asking its own user to sanction
the role for this batch, 2026-09-30). One ticket at a time; pushed only after its review. Item 9 (the
drawer) waits for mockups and is not built.

| Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|
| [LP-949](../tickets/LP-949.md) Lender on the file (items 1, 10b) | REVIEWED | `86089cf7` | the commit titled `LP-949 review: …` | ADR-417; reviewer: fresh subagent (peer session not sanctioned); 6 findings fixed (tenancy on PATCH, A→none→B, code map by rows, banner promise, no-op PATCH, stale tab) |
| [LP-950](../tickets/LP-950.md) Outbound wording (items 2, 3) | REVIEWED | `de7df33c` | the commit titled `LP-950 review: …` | reviewer: fresh subagent (peer session not sanctioned); 7 findings fixed (mask missed `123456789,` / `No.123…` / `Acct123…` / spaced card+SSN; item names and acceptable forms unmasked; `fill` ate the mask's `****`; acronym lowercased; dedupe dropped a Why; unnamed subject named nothing; three claims untested) |
| [LP-951](../tickets/LP-951.md) Wrong-file warning (item 11, raised to High) | REVIEWED | `5b2fc995` | the commit titled `LP-951 review: …` | reviewer: fresh subagent (peer session not sanctioned); 8 findings, 7 fixed + 1 recorded (attach-PDF and forward-merge doors skipped the check; accents/apostrophes false-warned; a shared particle hid a mismatch; a hyphenated surname switched the check off; Champions `Loan #` never read; duplicate surnames; "nothing from MISMO/extraction" too wide, flagged for the domain expert; stale cached answer left Import into an unanswerable 409). Builder full runs before review: backend 9024 passed, 1 failed (named sonnet); frontend 2156/2156. Full suites NOT re-run after review |
| [LP-952](../tickets/LP-952.md) Reading state and Read again (items 4, 5) | REVIEWED | `1fdce809` | the commit titled `LP-952 review: …` | reviewer: fresh subagent (peer session not sanctioned); 6 findings fixed (import/lender/code-map doors queued a second reading beside a running one; state marked on the imported round but read from the newest; failed with 0 unread offered a refused Read again; cached reading state not refetched after lender set / import / attach; refused Read again left the stale panel; three claims untested). Builder full runs before review: backend 9055 passed, 1 failed (named sonnet); frontend 2169/2169. Full suites NOT re-run after review |
| [LP-953](../tickets/LP-953.md) Linking (items 6, 7) | REVIEWED | `565c32b2` | the commit titled `LP-953 review: …` | ADR-418; reviewer: `mortgageboss-ai-cf` (sanctioned by its own user, 2026-10-02); 1 finding, fixed in the review commit: her unlink is keyed `(item_id, document_id)` and both `carry_plan` and `update_item`'s re-split mint a new item id, so her refusal was stranded and the next arrival re-linked the document she removed. `copy_unlinks` carries it; the narrow key was kept deliberately, since a file-wide one would suppress an unrelated condition's match (AS-01 and AS-10 both have a `statements` item). Both spec tensions answered in the Design and verified; the builder's mirror-test fix confirmed by a full re-run. Full suite after review: 9085 passed, 1 failed (named sonnet); frontend 2180/2180 unchanged |
| [LP-954](../tickets/LP-954.md) Reading keeps every clause (item 13) | REVIEWED | `3253e4d5` | the commit titled `LP-954 review: …` | reviewer: `mortgageboss-ai-cf`; supersedes plan §6 for 1228 by the owner's instruction (verified against the owner's quoted words, recorded here rather than in the plan, per convention); 1 finding, fixed in the review commit: `uncovered_conditionals` was satisfied by an ECHO of the conditional word plus any item key, so a clause nobody covered could leave the reading READY — the quote must now say more than the word, and the docstring states what the guard can and cannot establish. The acceptance-test update was checked and is principled (the no-AI path still asserts the old §6 row rather than relaxing it); the surviving mutation is genuinely equivalent by case analysis. Full suite after review: 9098 passed, 1 failed (named sonnet); frontend 2182/2182 |
| [LP-955](../tickets/LP-955.md) "I'll do it" actions (item 8) | REVIEWED | `227faaf5` | the commit titled `LP-955 review: …` | reviewer: `mortgageboss-ai-cf`; 3 findings, all fixed in the review commit. (1) `chosen_route` skipped every route whose step is `None`, so "Our vendor" could never read as chosen — she picked it and both buttons stayed unpressed, which the ticket and the docstring both said would not happen; fixed by removing the clause, so the panel presses the route the condition is ON, with a control that a step no route sets still reads as neither. (2) LP-955 made `EMAIL_PLACEHOLDERS` the union of two DISJOINT filler sets, so an item `email` could name `{code}` and a type `question` could name `{amount}`; `fill` answers `None`, which silently drops a request line from the borrower's email or falls back to the generic question — and the allow-list had no test at all. Split per filler, each half pinned. (3) "Ask someone for it" offered 4 of the 7 recipients an ask reaches; insurance, HOA and employer were unreachable, and an insurance item delegated as "Someone else" lost the mortgagee clause `party_lines` gates on `performer is INSURANCE` (S3-05). Their un-re-run gap closed: 9105/1 measured after their post-run assertion. Full suite after review: 9111 passed, 1 failed (named sonnet); frontend 2187/2187 in 182 files |
| [LP-956](../tickets/LP-956.md) Small items (items 10a, 12) | REVIEWED | `3d862cca` | the commit titled `LP-956 review: …` | reviewer: `mortgageboss-ai-cf`; 1 finding, fixed in the review commit: the new `readonly.conditions` carried `plan_reason`, which `condition_plan.py:605` assigns `f"Found: {found.document_name …}"` — so a found document's FILE NAME reached a staging query result, and `("documents","document_name")` is in `NEVER_EXPOSED` precisely because the scrub cannot match a person's name. `NEVER_EXPOSED` keys on (table, column), so the same string under another name was invisible to it. Measured from `pg_get_viewdef` on the view built from the migration's own DDL, not from the migration text. NOT this ticket's error: `git log -S` puts LP-920's "built by code and names no borrower" comment and that writer in the same commit `106de9af`, so the note it trusted was wrong when written — a comment recording a safety property, with nothing enforcing it. Dropped from the view, in `EXCLUDED` with the writer's line, and in `NEVER_EXPOSED` so re-adding it fails. Item 10a was fixed at a better layer than the spec asked (there are no waiting-on pickers; a move to Waiting sends the OWNER, so the refusal is server-side at the one door and bulk refuses just that row). Their disclosed gap closed: 9117/1 at the build SHA, the two censuses passing. Also corrected: my own mid-build note that nothing tested the view re-grant — `test_every_migration_that_recreates_a_readonly_view_regrants_it` does, and pre-dates this ticket. Full suite after review: 9118 passed, 1 failed (named sonnet); frontend untouched by the review, so 2190/2190 in 183 files stands |

**Batch 4 open items (for the owner):**
- **The lender's internal notes reach the borrower word for word** (LP-950 review). A generic item quotes
  the lender's whole condition, so 7086's "**8/28 Not in Upload. Provide the follo…" goes into the borrower
  email as written. That is what "the lender's own words" asks, but an underwriter's note to the broker may
  not be meant for the borrower. Owner to decide.
- **The draft dialog still labels a generic condition "What the lender asks for"** in its side column and
  "Other drafts" summary (LP-950 review). LP-950's rule covers emails; this is a screen. Not built.
- **Is a MISMO `LenderLoan` identifier ever the wholesale lender's loan number?** (LP-951 review, for the
  domain expert.) If so, a file's FIRST sheet could be checked against it. The one real MISMO file's number
  is 8 digits where the UWM sheets print 10, so it is not wired in.
- **Older bug, not built:** after attaching a PDF to a round, the success toast says "No new conditions"
  even when the PDF added some (found in the LP-951 review).
- **Should attaching or forwarding a PDF onto an imported round read the conditions it adds?** (LP-952
  review.) Import reads automatically; attach does not. The reading panel now shows them as unread, with
  Read conditions. Owner to decide.

**Batch 4 closed (2026-10-02).** All eight tickets REVIEWED and pushed. Reviewers: a fresh subagent for LP-949
to LP-952 (the peer session's user had not sanctioned the role yet), `mortgageboss-ai-cf` for LP-953 to LP-956
once its user did. Findings fixed in review: LP-949 6, LP-950 7, LP-951 8, LP-952 6, LP-953 1, LP-954 1, LP-955 3,
LP-956 1.

What the trial's items became: the file's lender detected from the sheet and confirmed by her, with untyped
conditions typed and AI-proposed types reviewed per lender (LP-949, ADR-417); outbound emails in the lender's
own words with account numbers masked, and a lender email that asks (LP-950); a wrong-file warning at every door
that turns a sheet into conditions (LP-951); the reading's state on screen with Read conditions / Read again
(LP-952); one matching rule, and her own links, changes, unlinks and upload-here, with her choices stored
(LP-953, ADR-418); every clause of the lender's text covered or flagged, 1228's re-disclosure for the LO
(LP-954); "Ask someone for it" and the UWM credit-invoice routes (LP-955); no "Waiting on Processor", and
readonly views that answer the trial's questions (LP-956).

**Not built:** item 9, the condition drawer, waits for mockups (the owner's instruction).

**Carry into the next batch** (the reviewer's two class-level notes):
- a list hand-written as a subset of an enum drifts (LP-955's recipients, 4 of 7); derive it from the enum, as
  LP-956's waiting-on choices do;
- a comment asserting a safety property with nothing enforcing it (LP-955's placeholders, LP-956's
  `plan_reason` "names no borrower") is the cheapest defect to prevent and the hardest to see in review: pin
  the property with a test, or delete the claim.

**Last full runs** (the reviewer's, at `054ec089`): backend 9118 passed, 1 failed (the named sonnet test), 8
skipped, 1 xfailed; frontend 2190 / 2190 (183 files) at `3d862cca`, unchanged since; ruff, format, mypy, biome,
tsc and the build clean.

**The shared dev database is behind HEAD** (the reviewer saw the old event-kind CHECK on `mortgageboss_dev`):
run `alembic upgrade head` there before clicking these features through on dev; staging needs a deploy.

## Batch 4 follow-ups (the owner, 2026-10-03)

| Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|
| [LP-957](../tickets/LP-957.md) The lender-package panel follows the conditions | REVIEWED | `f1ce70d4` | the commit titled `LP-957 review: …` | reviewer: `mortgageboss-ai-cf`; **no defects**. Verified rather than accepted: all seven prefix invalidations are non-exact (no `exact: true` anywhere in the frontend); no collision (list keys end in a params object, never the string `"package"`); nothing walks the cache prefix-wide (no `getQueriesData`/`setQueriesData` at all, and both `getQueryCache` subscribers bail on `key[0]`); the panel is mounted on the same screen as the status select so the query is active and refetches at once, while staying a no-op cost on screens where it is not; and the broken reader was `ready_count` from the package response, not the list, so refreshing the list could never have fixed it. "Every door" measured as a transitive closure over all 45 mutations in `conditions.ts`: 40 reach the prefix, and the five that do not are each correct (three package-own, one draft wording, and `decline` which touches no condition — confirmed on the server). Mutation: the old key fails both tests. Frontend 2192/2192 in 184 files re-measured, tsc and biome clean; their commit touches no `backend/` file, so no pytest was needed. Recorded against myself: a first pass reported 14 doors missing the prefix, which was a broken one-level search missing `invalidateDrafts`/`invalidateWithdrawal` delegating to `invalidatePlan` — three of those would have been false findings |

| [LP-958](../tickets/LP-958.md) The drawer and list redesign (item 9, the mockup the owner approved 2026-10-03) | REVIEWED | `1b4f3762` | the commit titled `LP-958 review: …` | reviewer: `mortgageboss-ai-cf`; 2 findings, both fixed in the review commit. (1) **The came-back state was misidentified in three places.** `condition_status.py:488` moves our track to To do on a `not_cleared` verdict, so `with_underwriter` + `not_cleared` is not a came-back condition but one she FIXED AND SENT AGAIN (`_OPEN` admits `not_cleared`, and a status move never writes `lender_status`). So the refusal sentence never appeared when the lender refused, and after a re-send it told her to send again what she had just sent while withholding the Record control; the column disagreed with the drawer on the same row. Two tests asserted the misconception, both named "came back" over a re-send fixture. Fixed with ONE predicate, `openWithLender`, shared by `goesInPackage`, the column and the drawer, plus a new To do branch; and the duplication their own note flagged is now executable — `test_the_frontend_still_open_rule_matches_the_backend_set` parses the frontend rule and compares it to `_OPEN` as a set, so a frontend-only change fails a backend test. (2) **`ActionMenu` dropped the keyboard a native `<select>` had**: it declares `role="menu"` but had no arrow keys, Home/End or focus return — opening left focus on `<body>`. Fixed and pinned. Checked and not findings: the link dialog does NOT reverse LP-953's "a mismatch is allowed and flagged, by design" (it sorts, never filters, reuses `document_answers`, and warns with LP-953's own consequence); `name → original_filename` is not the LP-956 class (readonly views vs an authenticated processor-facing API); "becomes Sent to lender" traced to `submit` and the summary bar's label; the `#lender-package` anchor resolves whenever that step is offered, which depends on LP-957's key nesting; `condition_links.py` is purely additive, so LP-953's doors are untouched. Open item: `ASKS`/`QUESTIONS` are still declared in both next-step.ts and next-action.ts. Their disclosed gap closed both halves: 9123/1 at the SHA, and tsc+biome clean (the surface the vitest suite cannot see). Frontend after review 2232/2232 in 187 files |
| [LP-959](../tickets/LP-959.md) The upload card names no lender (the owner, 2026-10-03) | DONE | | | not peer-reviewed: a one-sentence copy change the owner worded and asked to commit and push directly |
| [LP-961](../tickets/LP-961.md) The import review shows what she must act on, not how the sheet was read (the owner, 2026-10-04) | DONE | | | not yet peer-reviewed |
| [LP-962](../tickets/LP-962.md) Would the AI type conditions as well as the lender code maps? Measurement (the owner, 2026-10-04) | DONE | | | measurement only: UWM 16 of 21 agree, 4 untyped, 1 wrong (the list right); the Champions fixture's codes do not match its list, so that half is invalid; found the reading's 8192-token cap truncating a 21-condition round in one call; decision waits on real sheets |
| [LP-963](../tickets/LP-963.md) The import bar sits above the rows, not at the bottom of the window (the owner, 2026-10-06) | DONE | | | not peer-reviewed; placement asserted by DOM order + 3 layout mutations; not checked by eye in a browser |
| [LP-964](../tickets/LP-964.md) After Import, one step at a time: the reading, then the plan, then the list (the owner, 2026-10-06) | DONE | | | not peer-reviewed; list held back to one line with "Show them now", fails open; 12 mutations, 12 caught after adding one test; not watched in a browser |
| [LP-965](../tickets/LP-965.md) No code map: every condition is typed by a fresh AI reading (the owner, 2026-10-07; ADR-419) | DONE | | | not peer-reviewed; read_v4 + batches of 8, owner from the reading (migration 0915cdf12565), codes-to-review and seed removed; no mutation pass yet; real model not run |

The drawer and list redesign (the owner's screenshot of 2026-10-03: the cramped link/upload controls, no "what
next" after Ready, the unexplained "Open" column) is mocked up for the owner before anything is built (item 9).
