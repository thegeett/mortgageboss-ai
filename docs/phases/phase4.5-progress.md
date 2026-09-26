# Phase 4.5 progress — Stages 0 and 1 (conditions)

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
| [LP-905](../tickets/LP-905.md) | upload and email-forward doors, the parse task, migration `e5a2c7f31b84` | done; ⚠️ its table lists a §2 that has no body in the file |
| [LP-906](../tickets/LP-906.md) | rule readers: line model, UWM, Champions, generic; UWM from PDF | done |
| [LP-907](../tickets/LP-907.md) | the paste door and reader, fingerprint, `attach-pdf` enrich | done |
| [LP-908](../tickets/LP-908.md) | the AI splitter (`split_v1`) and its enqueue wiring | done; ⚠️ its table still reads §2 "next" though §2 is written |
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
- **Visual-check misses handed back to their author** — the list is in LP-909 §5, screen by screen.
  The largest: S1-13's action lives behind the `receiving` switch, which v1 turns off, and it neither
  asks attach-or-new nor links to the round.

## CI

**Not known to have run.** The branch is pushed through `050d5db0`, but both workflows trigger only
on `push` and `pull_request` to `main` — a push of this branch runs nothing, so CI needs a PR against
`main`. Local results and their limits are in LP-909 §5.
