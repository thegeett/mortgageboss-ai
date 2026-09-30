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
| LP-938 Library fixes (AS-04, the review table) | REVIEWED | `37f5aa9f` | the review section in [LP-938](../tickets/LP-938.md) (written, not yet committed) | none (no screen) | review found 1 (pre-existing, not a regression): AS-04's receipt item's only check, `amount_matches`, reads bank-statement transactions and so returns not_run for an earnest money receipt — the item can never pass without a manual accept. Table verified independently of its generator: 20 rows x 5 columns re-derived from the raw YAML and seed files, 0 mismatches. The owner's top-20 sign-off still open, on the regenerated table. **Follow-up `8239ea91` reviewed: 1 finding** — the receipt is fixed and the purchase-agreement census is clean (only AS-11 lists it, with no amount check), but the same dead end is open on AS-06's `gift_letter` item, whose only document type carries `gift_amount` that `amount_matches` never reads; latent, since AS-05/AS-06 are on no mapped sheet. **Second follow-up `c9425f67` reviewed: 1 finding** — the typed `OWN_AMOUNT` allow-list is the right guard (better than the tripwire the reviewer suggested: it makes the unsafe pairing unrepresentable and takes `_takes` off the correctness path), but `reask_name` now names a receipt, gift letter or deposit slip "A corrected the statement", which is both false and ungrammatical, on a re-ask path this commit opens. **Third follow-up `71ca84a8` reviewed: 1 finding + 2 recorded** — copying the failed item's performer is right (a wrong receipt is title's, and it used to re-ask the borrower), but `reask_to` falls back to "borrower" both when the item is not an ask and when its performer has no `_RECIPIENT` entry, and in the second case the ask is created for someone else and reaches no draft; the grammar fix is universal, the document name is fixed for 3 types of 32 |
| LP-939 Real-model trial | SKIPPED | | | none | skipped for now by the owner, 2026-09-29 |
| LP-940 Withdraw a hand-added condition | PENDING | | | detail sheet | amends ADR-404 |

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
- `backend/tests/conditions/test_condition_evidence.py::test_the_reask_goes_into_a_new_borrower_email` —
  **intermittent, seen once in three full runs** by the LP-937 review. It passes alone, passes with its
  module (22/22), and passes right after the sonnet test; a third identical fixed-order run was clean.
  Not caused by LP-937 and not the inbox-token flake below. Recorded so the next ticket is not blamed.
- `backend/tests/services/test_loan_file_ids.py::test_inbox_token_is_independent_of_display_id` —
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

## Stage 3 — open items (not blocking)

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

- **A re-ask can be created for someone with no email, while the button says "borrower"** — found by the
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

- **Three performers can be asked but have no email to be asked in** — same review, open, pre-existing and
  the root of the item above. `_RECIPIENT` covers 8 of the 11 `Performer` members: `processor`, `lender`
  and `appraiser` are absent, while `_THIRD_PARTIES` *includes* `appraiser` (the lender-processing switch
  flips appraiser items between `ask_third_party` and `lender_doing_it`) and the frontend's `EMAIL_WORD`
  has words for all three. So an appraiser ask lands in no draft today, silently.

- **The re-ask still calls 21 live items' documents "a statement"** — same review, open. `Statement.source`
  is only populated for `OWN_AMOUNT`'s three types, so `reask_name` names every other non-statement
  document a statement: censused at 29 items, 21 on mapped sheets, including IN-01 `declarations` (UWM
  6178, homeowners insurance — the insurance agent is asked for "a corrected statement"), ID-01 `id`
  (Champions 286, a driver's licence), DI-01 `disclosure` (UWM 0132) and TI-02 `report` (Champions 285).
  Not a regression: before the third follow-up all 32 said "A corrected *the* statement". Fix: both call
  sites hold the `Document`, so use `document.document_name` (what the card already prints) or
  `app/documents/naming.py`'s per-type stem, which cover all ~80 types.
- **Screen deviations for the product owner to redraw: D1 to D12**, gathered in one list below
  ("Stage 3 — screen deviations").
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

## Stage 3 — screen deviations (for the product owner to redraw)

Every Must-match line the build made untrue, and why. The reference PNGs are in
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
- **Owner sign-offs:** the library's top 20 (`phase4.5-library-review.md`) and the deviations above.
  (STOP AND ASK 2 was answered on 2026-09-29: LP-936.)
