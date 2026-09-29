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
| LP-918 Condition library v1 (data) | PENDING | | | none of its own | owner's top-20 sign-off tracked separately (decision 6) |
| LP-919 Reading each condition | PENDING | | | S3-01, S3-03 | |
| LP-920 The action plan | PENDING | | | S3-01, S3-02 | |
| LP-921 Next-step options | PENDING | | | S3-01, S3-02, S3-12 | |
| LP-922 Asking people (drafts only) | PENDING | | | S3-04, S3-05, S3-06 | then the Stage 3A acceptance test |
| LP-923 Evidence arrives and is checked | PENDING | | | S3-07, S3-08 | |
| LP-924 The figures check | PENDING | | | S3-09 | |
| LP-925 Package, submit, lender settings | PENDING | | | S3-10, S3-11 | then the Stage 3B acceptance test |
| LP-935 Stage 3 close | PENDING | | | every screen | |

## Stage 3 — decisions pre-made (plan §8), so nothing blocks

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

## Stage 3 — tests that already failed before Stage 3

Named so a later ticket is not blamed for them (baseline at `840df131`):

- `backend/tests/ai/test_provider_selection_b1.py::test_a_sonnet_reasoning_id_cannot_survive_boot` —
  this machine's `backend/.env` sets its own `ANTHROPIC_MODEL_*` values, so the test's premise fails here.
- `frontend/components/file/conditions/conditions-screens.test.tsx` › "offers a way out once the round
  is stranded" — fixture on the threshold (Stage 2 follow-ups).

## Stage 3 — STOP AND ASK

None yet.

## Stage 3 — open items (not blocking)

- **The product owner's sign-off on the library's top 20 types** (decision 6), once LP-918 has written
  `phase4.5-library-review.md`.
- **Screen deviations for the product owner to redraw:** D1 to D4 in [LP-934](../tickets/LP-934.md).
