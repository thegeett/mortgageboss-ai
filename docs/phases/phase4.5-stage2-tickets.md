# Phase 4.5 Stage 2 ("See and track"): ticket details

**Status:** draft for review · 2026-09-26
**Parent plan:** `docs/phases/phase4.5-build-plan.md` (v3) §4. This file replaces that section for
Stage 2.
**Builds on:** Stage 1 (LP-903 … LP-910) on branch `phase4.5-conditions`.
**Tickets:** LP-911 · LP-912 · LP-916 · LP-913 · LP-915 · LP-917 (lite). **LP-914 (board) is deferred.**
**ADR:** ADR-408 (next free number at the time of writing; verify before use).

> **Kick-off prompt** (paste into Claude Code at the repo root):
> *"Read `docs/phases/phase4.5-stage2-tickets.md` end to end, then follow it. Start with §10
> (before starting) and a short survey written to `docs/tickets/phase4.5-stage2-survey.md`. Build
> one ticket at a time in the order in §3, and stop at every point marked **STOP AND ASK**."*

### How to use this document (for Claude Code)

- **This file is the spec for Stage 2.** Where it conflicts with `phase4.5-build-plan.md` §4, this
  file wins.
- **STOP AND ASK first about defaults A1 to A7 (§1).** Show them to the product owner in the survey
  and record the answers there before writing ADR-408.
- **Verify the facts in §2 against the code** before relying on them. They were read at `e5a481bf`,
  and Stage 1 part 5 may have changed things since. Record any difference in the survey.
- **Screens:** the Stage 2 reference screens are in `docs/design/phase4.5-conditions/stage2/`: 11
  PNGs, the same screens as HTML, and a README with a *Must match* list per screen. Build LP-916,
  LP-913, LP-915 and LP-917 to them, and record a "Visual check" in each ticket. LP-911 and LP-912
  have no UI of their own, but their refusal sentences and event wording must match what the
  screens show.
- **Same working rules as Stage 1:** a `docs/tickets/LP-9xx.md` per ticket, one section per commit,
  review between sections, CI green, never `--no-verify`, no real borrower data in the repo, and a
  "Visual check" section in every UI ticket.
- **When Stage 2 is done:** add a Stage 2 part to `docs/phases/phase4.5-progress.md` (shipped,
  deferred, STOP AND ASK answers).

---

## 1. What Stage 2 is, in one screen

After Stage 1 the lender's conditions are saved in the file, word for word, round by round, but
nothing can be *tracked*. Every condition sits at *To do / Open* and there is no way to say
"waiting on the borrower", "sent", or "the lender cleared it".

After Stage 2 the processor can:

1. See every condition on the file in one **list**: the lender's headings, who each one is waiting
   on, our status, the lender's status, and which rounds it appeared on.
2. **Move** a condition through our four steps and **record what the lender said** (cleared, waived,
   not cleared), one at a time or in bulk, with every change kept in history.
3. When a new **full** sheet arrives, see **what changed**: which conditions probably cleared (she
   confirms them in one click), which came back with a new underwriter note, which were reworded,
   which are new, and how the loan figures and dates on the letter changed.
4. Open any condition and read its **whole story**: the lender's words, notes, rounds and every change.
5. See the **lender's dates** from the latest sheet (must not close before, lock expiry, document
   expiry) on the round card and the file rail.

**Stage 2 does not take actions.** It sends no emails, creates no needs, checks no documents and
changes no loan figures. That is Stage 3. It uses **no AI at all**: everything in Stage 2 is rules and
the processor's own clicks.

### Decisions already made (product owner, 2026-09-26)

| # | Decision |
|---|---|
| D1 | **List first.** The drag-and-drop board (LP-914) moves to after Stage 3. |
| D2 | **Our status has four steps:** To do → Waiting on someone → Ready to send → Sent to lender. |
| D3 | **Missing from a full round = "probably cleared".** The processor confirms them all in one click, or unticks some first. Nothing changes until she confirms. A partial round never suggests anything. |
| D4 | **Dates: only the lender's.** Show the dates printed on the sheet. Typing in closing and funding dates, and warnings about them, move to Stage 4. |

### Defaults this document assumes (confirm or change before building)

| # | Default | Why |
|---|---|---|
| A1 | **A new dated underwriter note sets the lender status to *Not cleared* automatically,** and our status goes back to *To do*. | The note *is* the lender's answer ("9/10 Not in Upload"). Nothing is being cleared; it is being reopened on the lender's own word. The screen says so clearly. |
| A2 | **The processor can change "who it's waiting on" by hand.** | The code map and prefixes are a good first guess, not the truth. The manual choice wins and is kept in history. |
| A3 | **"Draft email to borrower" is not in Stage 2.** | It is an action, so it belongs to Stage 3 (LP-921/922). |
| A4 | **`REVIEW` (ours) and `PENDING_REVIEW` (lender's) stay in the database but are never offered in Stage 2.** | Removing enum members needs a migration for no gain. Stage 3 may use `REVIEW` for "document arrived, checking it". |
| A5 | **Conditions added by hand are never proposed as "probably cleared".** | A hand-typed condition never appears on a sheet, so it would be proposed on every round. |
| A6 | **"Probably cleared" compares against every open condition on the file,** not only the previous round. | This handles round 1 full → round 2 partial → round 3 full correctly. |
| A7 | **An imported round can be switched from *Just some* to *Full list*** (for example after attaching its PDF), which runs the comparison. | Otherwise Stage 1's own acceptance path (round 2 pasted as "just some", then the PDF attached) could never produce a suggestion. |

---

## 2. What Stage 1 already gives Stage 2

Read from the code on `phase4.5-conditions` (last checked at `e5a481bf`):

| Exists | Where |
|---|---|
| `Condition.prep_status`: `to_do · waiting · review · ready · with_underwriter` (all rows `to_do`) | `models/condition.py` `ConditionPrepStatus` |
| `Condition.lender_status`: `open · pending_review · cleared · not_cleared · waived · superseded` (all rows `open`) | `ConditionLenderStatus` |
| `owner_hint` + `owner_hint_source` (`prefix · bucket · code_map · none`) | `OwnerHint`, `OwnerHintSource` |
| `bucket_heading` (lender's words), `bucket_kind` (when it is due), `info_only`, `origin` (`sheet · manual`) | `Condition` |
| `first_round_id`, `last_seen_round_id`, `underwriter_notes` (dated), `text_fingerprint` | `Condition` |
| `round_numbers` per condition, from its events | `GET /loan-files/{id}/conditions` |
| `condition_events` append-only; kinds up to `condition_edited` | `models/condition_event.py` |
| `possible_match` in the `CONDITION_CREATED` event when the code matched but the wording didn't | LP-909 import |
| Round `completeness` (`full · partial`), `header` (`lender_team`, `loan_facts`, mortgagee clause), `expiry_dates`, `date_printed` | `models/condition_round.py` |
| Round strip, imported list, round-details sheet, `R1 R2` chips | `frontend/components/file/conditions/*` |
| `NeedsItemOrigin.CONDITION`, reserved for Stage 3 | `models/needs_item.py` |

**Nothing in Stage 2 re-reads a sheet.** Everything works from the saved rounds and conditions.

---

## 3. Order of work

```
LP-911 (read API)  →  LP-912 (statuses + verdicts, ADR-408)  →  LP-916 (detail sheet)
       →  LP-913 (list view, replaces the imported list)  →  LP-915 (round comparison)
       →  LP-917-lite (lender's dates)
```

LP-912 comes before any screen because every screen shows statuses. LP-916 comes before LP-913 because
the list opens the detail sheet from every row. LP-915 comes last because its confirm step *uses*
LP-912's verdicts.

Same working rules as Stage 1: one ticket at a time, a `docs/tickets/LP-9xx.md` per ticket, review
between sections, **STOP AND ASK** where marked, and reference screens checked by a person.

---

## 4. The tickets

### LP-911 · Conditions read API: filter, summary, detail · size M

**Goal:** everything the list, the detail sheet and the file rail need, in three reads.

**Endpoints**

1. `GET /api/loan-files/{id}/conditions` (extends Stage 1's endpoint; the old behaviour stays the
   default)
   - **Filters** (query params, all optional, combined with AND):
     `round` (on the sheet of round N) · `lender_status` (multi) · `prep_status` (multi) ·
     `owner` (multi, using the effective owner, see LP-912) · `bucket_kind` (multi) ·
     `lender_code` · `category` · `info_only` (bool) · `origin` · `q` (text search in wording and code).
   - **Sort:** `sheet` (default: latest round's sequence, then first-seen order) · `code` ·
     `status` · `owner` · `updated`.
   - **Each row adds:** `round_numbers` (Stage 1), `effective_owner` and its source,
     `latest_note` (the newest dated underwriter note), `came_back` (bool: lender status is `not_cleared` because of an underwriter note), `is_open` (lender status is `open` or `not_cleared`), `days_open` (since first
     seen), `verdict` (LP-912), `pending_suggestion` (LP-915: e.g. "probably cleared in round 2", or
     null), `superseded_by_id`.
2. `GET /api/loan-files/{id}/conditions/summary`
   `{total, open, cleared, waived, not_cleared, superseded, info_only,
     by_prep_status: {...}, by_owner: {...}, by_bucket_kind: {...},
     open_prior_to_docs, open_prior_to_funding, pending_suggestions, latest_round: {...}}`.
   It feeds the list's summary bar and the file rail. Info-only and superseded conditions are not
   counted as open.
3. `GET /api/conditions/{condition_id}` gives one condition with its rounds (number, date,
   completeness, whether it was on that sheet, the note added in that round) and
   `GET /api/conditions/{condition_id}/events` gives its history.

**Rules**
- Company-scoped **inside the query** (the `ScopedRound` pattern from LP-909), soft-deleted rows
  excluded, 404 for another company's condition, never 403.
- `q` searches `verbatim_text` in the database. It must never be logged (ADR-405). Log only the
  filter names and counts.
- No pagination: a file has about 5 to 60 conditions. Cap at 500 and say so in the response if hit.
- Add `prep_status`, `lender_status`, `effective_owner` and the verdict's `source_kind`/`source_date`
  to `readonly.conditions` (not NPI). The wording and notes stay out.

**Done when**
- Filters, sorts and the summary are covered by tests on the §7 fixtures (for example "open + waiting
  on borrower" after round 1 returns exactly `7086 6132 6637`).
- A second company gets 404 on every route.
- The Stage 1 imported list still works unchanged, since its default response shape is kept.

**Screens it feeds** (no UI of its own): the summary numbers in `S2-01` / `S2-02` come from
`…/summary`, and the row fields from the list endpoint. Check the numbers on those two screens
against the §7 fixtures.

**Out of scope:** anything that writes.

---

### LP-912 · Statuses, moves and lender verdicts · size L · **ADR-408**

**Goal:** the two status tracks become usable, and every change is safe, explained and kept.

#### ADR-408: the status model (write first; the rest of the ticket depends on it)

**Our track (preparation): what *we* are doing**

| Value | Label on screen | Meaning | Extra data |
|---|---|---|---|
| `to_do` | To do | Nobody has started it | none |
| `waiting` | Waiting on *someone* | We asked; waiting for a person or document | `waiting_on` (owner) required, optional note |
| `ready` | Ready to send | We have what the lender needs | none |
| `with_underwriter` | Sent to lender | Uploaded / submitted to the lender | `sent_at` (default now), optional note |
| `review` | *(not offered in Stage 2, A4)* | reserved | none |

- **Forward moves** (to_do → waiting → ready → with_underwriter, or skipping steps) need no reason.
- **Backward moves** need a reason, one short line. A condition that came back (A1) moves back
  automatically, and its reason is the lender's note.
- **Info-only conditions** have no preparation track. The list shows "Information only" and the API
  refuses moves, with a sentence saying why.
- **Lender-to-clear conditions** (`bucket_kind = lender_to_clear`) default to showing "Lender is doing
  it". Moves are allowed, since sometimes the processor has to chase it, but they are never counted
  in "your to-do".

**The lender's track: what *the lender* said**

| Value | Label | Who sets it |
|---|---|---|
| `open` | Open | Default on import |
| `not_cleared` | Came back | **Automatic** when a new dated underwriter note arrives (A1), or recorded by hand |
| `cleared` | Cleared | **Only by a recorded verdict** (by hand, or by confirming "probably cleared") |
| `waived` | Waived | Only by a recorded verdict |
| `superseded` | Replaced | When the processor confirms a "reworded" pair (LP-915); links to the new condition |
| `pending_review` | *(not offered in Stage 2, A4)* | reserved |

**A verdict** is the record of *who said so and where*. It is required for `cleared`, `waived` and a
manual `not_cleared`.

```
verdict = {
  status:       cleared | waived | not_cleared,
  source_kind:  portal | email | phone | round_comparison | underwriter_note,
  source_date:  date (required; the date the lender said it, not today by default),
  round_id:     the round that showed it (required for round_comparison / underwriter_note),
  note:         optional, ≤ 500 chars,
  recorded_by:  user id, recorded_at: timestamp
}
```

- **Reopen:** `cleared` or `waived` can go back to `open` only with a reason. That writes an event,
  and the old verdict stays in history. This covers "I clicked the wrong one" and "the lender
  re-issued it".
- **Our track after a verdict:** `cleared` or `waived` leaves our status alone (the history shows what
  was done). Reopening sets our status back to `to_do`.
- **Nothing in Stage 2 sets `cleared` or `waived` without a person's click.** This is ADR-404 made
  concrete: the round comparison *proposes*, and the processor confirms.

#### Data (one migration)

- `conditions`: `waiting_on` (OwnerHint, nullable) · `prep_note` (short text, nullable, NPI) ·
  `sent_at` (timestamptz, nullable) · `prep_status_changed_at` · `lender_status_changed_at` ·
  `verdict` (JSONB, nullable; the current one, with history in events) · `owner_override` (OwnerHint,
  nullable) · `superseded_by_id` (FK conditions, nullable).
- `OwnerHintSource` gains `manual`. The **effective owner** is `owner_override` if set, otherwise
  `owner_hint`.
- `ConditionEventKind` gains `condition_prep_moved`, `condition_verdict_recorded`,
  `condition_reopened`, `condition_came_back`, `condition_owner_changed`, `condition_superseded` (and
  `round_compared`, `round_completeness_changed` for LP-915). These are VARCHAR + CHECK, so the
  migration swaps the constraint (ADR-037; the guard from LP-909 §3 must see it).
- `readonly.conditions`: add the non-NPI columns above; `prep_note` and `verdict.note` stay out.

#### Endpoints

- `POST /api/conditions/{id}/prep-status` `{to, waiting_on?, reason?, note?, updated_at}`
- `POST /api/conditions/{id}/verdict` `{status, source_kind, source_date, round_id?, note?, updated_at}`
- `POST /api/conditions/{id}/reopen` `{reason, updated_at}`
- `PUT  /api/conditions/{id}/owner` `{owner | null (back to the hint), updated_at}`
- `POST /api/loan-files/{id}/conditions/bulk` `{condition_ids[], action: prep_status | verdict | owner, …same fields}`
  → `{applied: [...], refused: [{id, code, message}]}`. It applies the rows that are allowed and
  refuses the rest, each with a reason. The UI shows "4 marked cleared · 1 skipped: information only".

**Every refusal has a typed code and one plain sentence** the UI shows as-is, for example:
`backward_move_needs_reason` → "Moving back to *To do* needs a short reason." ·
`info_only_has_no_status` → "This line is information from the lender — there is nothing to track." ·
`verdict_needs_source` → "Say where the lender cleared it (portal, email, phone) and on what date." ·
`stale` → "Someone else changed this condition — reload to see their change."

**Concurrency:** optimistic, on `updated_at`, the same pattern LP-909 fixed for drafts.
**Locking:** bulk runs inside `loan_file_needs_lock`, like import does.

#### Came back (A1), wired into Stage 1's import

In `condition_import`, when a seen-again condition gains an underwriter note **it did not have
before this import** (compared with its saved notes by date and text, the same way Stage 1's
`CONDITION_NOTE_ADDED` already decides a note is new). Do **not** compare the note's date with the
time of the last move: a processor may move a condition on the 26th and then import a sheet printed on
the 18th.

1. Set `lender_status = not_cleared` with verdict `{source_kind: underwriter_note, source_date: the
   note's date, round_id}`.
2. If our status was `ready` or `with_underwriter`, move it to `to_do` with the reason
   "Came back {date}: {note}".
3. Write `condition_came_back`.

This happens on **full and partial** rounds, because a note is a statement by the lender whichever way
the sheet arrived. **STOP AND ASK** if Stage 1's import cannot tell a new note from an old one
reliably (for example, the same note pasted twice).

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage2/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage2/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage2/screens/S2-04-record-lender-answer.png` (the lender's answer, single and bulk)
- `docs/design/phase4.5-conditions/stage2/screens/S2-05-move-back-reason.png` (the reason for a backward move, reused for Reopen)
- `docs/design/phase4.5-conditions/stage2/screens/S2-08-round3-reworded-cameback.png` (how *Came back* reads once LP-915 shows it)
The refusal sentences and the verdict wording in these screens are the strings the API returns.
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

**Done when**
- Every allowed and refused move is tested, with its sentence.
- `cleared` is impossible without a verdict at the API level.
- Bulk returns per-row refusals.
- Came-back works on a synthetic round 3 (§7.3).
- Every change writes exactly one event.
- A second company gets 404.
- ADR-408 is Accepted and the glossary is updated.

**Out of scope:** automatic moves from documents arriving or emails sent (Stage 3); due dates and
clocks (Stage 4).

---

### LP-916 · Condition detail sheet · size M

**Goal:** everything about one condition in one place, opened from any row.

**Shape:** a right-hand `Sheet` (the same component as S1-09's round details) that opens from the
list. It has **Previous / Next** (and the ↑ ↓ keys) so she can go through the list without closing it.

**Content, top to bottom**
1. **The lender's words** in serif, exactly as saved, with a **Copy text** button. She pastes it
   into emails and portals every day, so copying is a safe convenience rather than an action.
2. **Code · category · heading** (the lender's), then the kind chip ("Prior to docs") and "Information
   only" / "Lender is doing it" when they apply.
3. **Status block:** our status (select), who it's waiting on (select, with "suggested: Borrower, from
   code map" when no override is set), and the lender's status with the current verdict
   ("Cleared · portal · 09/12/2026 · by Priya") and a **Record lender's answer** button. Reopen
   appears when cleared or waived.
4. **Underwriter notes:** dated chips, newest first, each showing the round it arrived in.
5. **Rounds:** one line per imported round — on this sheet ✓ / not on it — / not comparable
   (partial). For example "R1 08/28 ✓ · R2 09/10 ✓ (full)".
6. **Pending suggestion,** if any (from LP-915): "Round 2 suggests this probably cleared" with
   **Confirm** and **Keep open**.
7. **History** in plain words from the events: "Imported from round 1 (PDF)", "Seen again in round
   2", "Moved to Waiting on Borrower — Priya, 09/11", "Came back 9/18: Inspection shows incomplete
   items", "Marked cleared (portal, 09/12) — Priya".
8. **Replaced by / replaces** link when superseded.

**No action buttons for Stage 3 work** (no "email borrower", no "request document"). Leave the space
empty rather than showing disabled buttons that promise work the app can't do yet.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage2/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage2/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage2/screens/S2-03-condition-detail.png` (the detail sheet)
- `docs/design/phase4.5-conditions/stage2/screens/S2-04-record-lender-answer.png` (opened from the sheet's *Record lender's answer*)
- `docs/design/phase4.5-conditions/stage2/screens/S2-05-move-back-reason.png` (opened from a backward move or *Reopen*)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

**Done when**
- Every event kind has a plain sentence (with a test that fails if a new kind has none).
- Previous and Next follow the list's current filter and sort.
- Copy text copies the saved wording exactly.

---

### LP-913 · Conditions list view · size L

**Goal:** the processor's main screen for conditions, replacing Stage 1's read-only imported list.

**Layout, top to bottom**
1. **Round strip** (Stage 1). Round cards gain "3 probably cleared — review" when a suggestion is
   pending (LP-915).
2. **Summary bar** from `…/summary`: **Open 11 · Came back 1 · Cleared 5 · Waived 0 ·
   Information 1**, then **Prior to docs open 6 · Prior to funding open 5**. Each number is a filter.
3. **Filter row:** our status · lender status · waiting on · heading kind · round · search. Filters
   live in the URL (like the pipeline's saved views), so a refresh or a shared link keeps them.
   **Group by:** lender's heading (default, sheet order) · waiting on · our status.
4. **The list,** grouped. Each row shows:
   select box · code (mono) · the lender's words (serif, two lines, full on hover or in the detail
   sheet) · latest underwriter note chip · rounds (`R1 R2`) · **waiting on** · **our status**
   (inline select) · **lender status** (chip; "Came back" in amber, "Cleared" in green, "Replaced"
   struck through).
5. **Sections at the bottom,** collapsed by default: "Information only (1)", "Lender is doing it
   (4)", "Cleared (5)", "Replaced (1)". Cleared conditions don't disappear, since she often needs to
   say "that was cleared on the 12th", but they move out of the way.
6. **Bulk bar** when any rows are selected: **Set status ▾ · Waiting on ▾ · Record lender's answer
   ▾ (Cleared / Waived / Came back)**. It opens the S2-04 dialog once for all selected rows and
   reports "4 updated · 1 skipped: information only".

**Behaviour**
- Clicking a row opens the LP-916 detail sheet. The list stays in place and the row is highlighted.
- Changing a row's status inline updates it straight away and rolls back with the refusal sentence
  if the server says no.
- **Empty filtered state** uses `EmptyState kind="filtered"` and names the filter ("No condition is
  *Waiting on Title*").
- Keyboard: ↑ ↓ to move, Enter to open, `x` to select.
- **Words:** the Stage 1 rule stays for things the app itself decides. It never says "cleared" on
  its own, only for a condition with a recorded verdict, and the chip shows where the verdict came
  from on hover.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage2/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage2/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage2/screens/S2-01-list-round1.png` (the list after round 1)
- `docs/design/phase4.5-conditions/stage2/screens/S2-02-list-midwork-bulk.png` (mid-work: statuses, the collapsed Cleared section, the bulk bar)
- `docs/design/phase4.5-conditions/stage2/screens/S2-09-filtered-empty.png` (filters that match nothing)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

**Done when**
- The list replaces `ImportedView` for imported rounds (Stage 1's review and empty states stay).
- Filters round-trip through the URL.
- Bulk verdict on 5 rows writes 5 verdicts and 5 events.
- The imported-list Must-match items from S1-05 and S1-08 still hold (`R1 R2`, nothing marked
  missing).
- The page stays usable at 1280 px (ADR-394).

---

### LP-915 · Round comparison: "What changed in round N" · size L

**Goal:** when a new sheet is imported, show exactly what changed, and let her confirm what cleared
in one click.

#### When it runs
- On every import of round N ≥ 2, **and** when an imported round is switched from *Just some* to
  *Full list* (A7).
- It is computed **once** and **saved** (`condition_rounds.comparison` JSONB, or a small table if the
  survey prefers). Opening the panel later shows the same result, and an event `round_compared` is
  written. It is recomputed only when the completeness changes.

#### What it compares
The **new round's conditions** against **every condition on the file that was open before this
round** (lender status `open` or `not_cleared`, origin `sheet`, not superseded) (A6). It does not
compare against the previous round alone.

| Result | Rule | What happens |
|---|---|---|
| **New** | Created by this import | Shown only |
| **Still open** | Seen again, no new note, same wording | Shown only (collapsed) |
| **Came back** | Seen again **with a new dated note** | Already set to *Came back* by LP-912's import hook; shown here with the note |
| **Reworded?** | A new condition whose `CONDITION_CREATED` event carries `possible_match` (same code, different wording) | Shown as a pair, old wording above new, with **Same condition** and **Different conditions**. "Same" marks the old one *Replaced* (`superseded_by_id` = new) and moves its history link. "Different" leaves both. Nothing happens until she chooses. |
| **Probably cleared** | Open before, **not on this sheet**, and this round is **Full list**, not older than the latest imported round, the condition is not manual (A5), and it is **not the old half of a Reworded? pair** in this round | Suggested, see below |

**Partial rounds** ("Just some") produce only New, Still open, Came back and Reworded. The panel says:
"This round was *just some* conditions, so nothing is suggested as cleared."

**An older sheet imported late** (its date printed is before the latest imported round's) produces
no Probably cleared, with the warning "This sheet is older than round N, so missing conditions
aren't treated as cleared."

#### Confirming "probably cleared"
- The panel lists them all, **all ticked**, each with its code, wording and the round it was last
  on.
- **Confirm N as cleared** records a verdict for each ticked one: `{cleared, source_kind:
  round_comparison, source_date: the round's date printed (or round date), round_id}`. Unticked ones
  stay open and lose the suggestion.
- **Not now** keeps the suggestions pending. The round card and the summary bar show "5 probably
  cleared — review" until she decides.
- The suggestion is per condition, so she can also confirm one from the detail sheet.

#### Letter changes (from the round headers)
When both rounds have a header, show **only the values that changed, old → new**: note rate, housing /
debt ratios, verified income, verified assets, max funds to close, rate lock expiry, must not close
before, must fund by, the UW team names, and each document-expiry date. Values missing on either
side show as "—" and are never guessed.

*(The plan's "the lender's verified assets against the file's own" needs the file's asset figures,
which belong to Stage 3's work on numbers. Leave it out here, with a note.)*

#### Switching completeness after import (A7)
`PUT /api/condition-rounds/{id}/completeness` `{completeness, updated_at}`, for imported rounds only.
- *Just some → Full list* runs the comparison.
- *Full list → Just some* withdraws **unconfirmed** suggestions from that round. Confirmed verdicts
  stay, because they are the processor's recorded decision; the panel says so.
- Writes `round_completeness_changed`.

#### Screens
**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage2/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage2/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage2/screens/S2-06-what-changed-round2.png` (the panel after importing a full round 2, with letter changes)
- `docs/design/phase4.5-conditions/stage2/screens/S2-07-confirm-probably-cleared.png` (the confirm step with one unticked)
- `docs/design/phase4.5-conditions/stage2/screens/S2-08-round3-reworded-cameback.png` (came back, the reworded pair, new)
- `docs/design/phase4.5-conditions/stage2/screens/S2-10-partial-round-no-suggestions.png` (a *Just some* round: nothing suggested, *Switch to Full list*)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

**Done when (the Stage 2 acceptance core, on the §7 fixtures)**
- Round 1 (full, PDF) then round 2 (full, PDF): **Probably cleared = exactly `7086 6132 6637 6178
  0132`**, still open = `1228 1947 1582 0006 0007 6378`, new = 0, came back = 0. Letter changes
  include note rate **6.374% → 6.490%**, ratios **32.51% / 40.36% → 32.83% / 40.69%**, verified assets
  **$11,062.18 → $41,914.42**, max funds to close **$11,062.18 → $41,914.42**, rate lock expiry
  **— → 09/30/2026**, UW team **Tigers → Lightning**, close-by **10/30/2026 → 11/03/2026**, asset
  expiry **10/30/2026 → 11/30/2026**.
- Confirming all 5 writes 5 verdicts sourced to round 2, and the summary becomes Open 6 · Cleared 5.
- The same pair with round 2 **pasted as just some** gives no suggestions. Attaching the round-2 PDF
  and switching to Full list then gives the same 5.
- Round 3 (§7.3) gives came back `1228`, one reworded pair (`6378`), new `7383`, and probably
  cleared `0006 0007`. The old `6378` is **not** suggested as cleared: it appears only in the pair.

---

### LP-917 (lite) · The lender's dates on the file · size S

**Goal:** the dates the lender printed, where the processor looks, without asking her to type
anything.

- **Source:** the newest imported round that has a header or expiry table (full, or partial with its
  PDF attached).
- **Shown on the round card and the round-details sheet** (they already exist): must not close
  before · must fund by · rate lock expiry · the expiry table.
- **Shown in the file context rail,** in a new "Lender dates" section: the same three dates, plus
  **the soonest document expiry** ("Asset docs expire 11/30/2026 · 65 days"). Days are counted from
  today, and the section says which round it comes from ("from round 2, printed 09/10").
- **Plain display only.** No colours for "soon", no alerts, no attention-queue items (Stage 4).
- If no round has dates: "No dates from the lender yet." It is never blank and never guessed.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage2/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage2/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage2/screens/S2-11-lender-dates.png` (the Lender dates section in the file rail, and the dates on the round card)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

**Done when**
- After round 2 the rail shows rate lock expiry 09/30/2026, must not close before 09/30/2026, and the
  soonest expiry is income / close-by 11/03/2026, all taken from round 2 and not round 1.
- A file with only a pasted round shows "No dates from the lender yet".

**Deferred to Stage 4:** contract closing, signing and funding dates the processor enters; warnings
such as "lock expires on the first allowed closing day"; the Today queue.

---

### LP-914 · Board view: **deferred** (D1)

Kept in the plan and moved after Stage 3, when cards carry real actions. When built, it reuses LP-912's
moves and refusal sentences as-is, so nothing here needs to change for it.

---

## 5. Stage 2 acceptance scenario

On a synthetic copy of the test file (fixtures in §7), through the API and once by hand in the UI:

1. Import round 1 (UWM PDF, full). The list shows 11 conditions, all *To do / Open*. Summary: Open 11.
2. Move `6637`, `6132` and `7086` to *Waiting on Borrower*, `1947` and `6378` to *Waiting on Title*,
   and `0006` to *Ready to send*. Moving `0006` back to *To do* without a reason is refused with the
   sentence, and works with one.
3. Import round 2 (UWM PDF, full). *What changed* shows 5 probably cleared (the exact list above),
   6 still open, 0 new, and the letter changes listed in LP-915.
4. Untick `0132`, then confirm 4. Summary: Open 7 · Cleared 4. `0132` stays open with no suggestion.
5. Record `0132` cleared by hand (portal, 09/12/2026). Summary: Open 6 · Cleared 5.
6. Move `1228` to *Sent to lender*, then import round 3 (§7.3, full). `1228` shows *Came back*
   with the 9/18 note and our status is back to *To do*. The reworded `6378` pair is shown; choose
   "Same condition" and the old one shows *Replaced*. `7383` appears as new. `0006` and `0007` are
   suggested as probably cleared; confirm both. Nothing already cleared is touched.
7. Reopen `0006` with a reason. It goes back to *Open / To do*, and its history shows every step in
   plain words.
8. The file rail shows the lender dates from round 3, or round 2 if round 3 has no header.
9. A second company can't read, move, verdict, compare or switch completeness on any of it.
10. **All 11 reference screens** (`docs/design/phase4.5-conditions/stage2/`) are checked against the
    built UI at 1600 px, and each result is recorded under "Visual check" in LP-913, LP-915, LP-916 and
    LP-917. Stage 2 is not done until a person has looked at them, the same rule as Stage 1.

---

## 6. Rules that apply to every Stage 2 ticket

1. **Only the lender clears.** `cleared` and `waived` need a recorded verdict with a source and a
   date. The app proposes, and the processor confirms.
2. **No AI in Stage 2.** Every result comes from saved data and rules.
3. **Nothing disappears.** Cleared, waived and replaced conditions stay visible (collapsed) with
   their history.
4. **Every change writes exactly one `condition_event`.** History is built from events, never from
   current values.
5. **Refusals are typed and worded.** The UI shows the server's sentence and never makes up its own.
6. **Company scoping inside the query; 404 for other companies.**
7. **NPI:** condition wording, notes, `prep_note` and `verdict.note` are never logged and stay out of
   `readonly.*`. Statuses, codes, counts and dates may appear.
8. **Stage 1's safety rules still hold:** exact wording, and a partial round never removes or
   clears anything.
9. **Words on screen:** "cleared" only next to a recorded verdict. "Probably cleared" is always a
   question with a button, never a status.

## 7. Fixtures

Reuse Stage 1's `uwm_round1_2026-08-28` and `uwm_round2_2026-09-10` **as full PDFs**. Add:

### 7.1 Round 2 as a full PDF
Stage 1 imported round 2 as a paste (just some). Stage 2 needs both paths, so the round-2 fixture is
also imported as an uploaded PDF (full). No new text is needed.

### 7.2 Expected comparison, round 1 → round 2
As in LP-915's Done-when. It is the core of the acceptance test and must be an exact assertion, not a
count.

### 7.3 `uwm_round3_2026-09-18.txt` (new, synthetic, same layout as the round fixtures)
- Header: date printed **09/18/2026**, UW team **Lightning**, note rate **6.490%**, verified assets
  **$41,914.42**, rate lock exp **09/30/2026**.
- Conditions:
  - `1228` Appraisal, **same wording**, with the new note `**9/18 Inspection shows incomplete
    items` → **came back**.
  - `6378` TC, **reworded:** "TC: Title company to include the lender loan number on all checks and
    wires sent to lender." → **reworded pair** with round 1/2's `6378`.
  - `1947`, `1582` same as round 2 → still open.
  - `0006` and `0007` **absent** → probably cleared.
  - **New** `7383` Assets, a new wording about a deduction on the bank statement, with fictional
    amounts → **new**.
- Expected (full round): came back `1228` · reworded pair `6378` (old → new) · still open
  `1947 1582` · new `7383` · probably cleared `0006 0007`. The old `6378` is in the pair only, never
  in probably cleared.

All fixture data is fictional. Real sheets never enter the repo (ADR-405).

## 8. Reference screens

**Drawn.** They're in `docs/design/phase4.5-conditions/stage2/` (PNG + HTML + README with a
Must-match list per screen), in the same format as Stage 1.

| # | Screen | Ticket |
|---|---|---|
| S2-01 | List after round 1: all To do / Open, summary bar, grouped by heading | LP-913 |
| S2-02 | List mid-work: filters, statuses, bulk bar with 3 selected, collapsed sections | LP-913 |
| S2-03 | Condition detail sheet | LP-916 |
| S2-04 | "Record the lender's answer" dialog (single and bulk) | LP-912/916 |
| S2-05 | Reason for a backward move or reopen | LP-912 |
| S2-06 | "What changed in round 2", with letter changes | LP-915 |
| S2-07 | Confirm probably cleared (one unticked) | LP-915 |
| S2-08 | Reworded pair: Same / Different | LP-915 |
| S2-09 | Filtered to nothing | LP-913 |
| S2-10 | Partial round: nothing suggested, with "switch to Full list" | LP-915 |
| S2-11 | Lender dates in the file rail and on the round card | LP-917 |

## 9. Out of scope for Stage 2

The board (LP-914) · drafting emails, creating needs or asking anyone (Stage 3) · checking arriving
documents against a condition (Stage 3) · proposing changes to loan figures (Stage 3) · the file's own
verified assets beside the lender's · processor-entered closing and funding dates, clocks, alerts,
the Today queue (Stage 4) · a Sun West reader · any AI.

## 10. Before starting

- Stage 1's part 5 (§8 acceptance, the 13 visual checks, `phase4.5-progress.md`, CI on a PR to
  `main`) should be finished first, so Stage 2 builds on a checked base.
- Confirm or change defaults **A1 to A7** in §1.
- The Stage 2 screens (§8) are drawn. Read their README before the first UI ticket.

---

### How this compares with how processors work today

- Lenders sort conditions into prior to docs and prior to funding; the doc-level ones must clear
  before the lender will prepare closing documents. Underwriters re-issue conditions that weren't
  fully met, sometimes with new ones added ([Gustan Cho, clearing conditions](https://gustancho.com/underwriters-conditions/)).
  That is exactly the *came back* and *new* results in LP-915.
- Lender-side LOS tools such as Encompass keep underwriting conditions as tracked records with their
  own status workflow, and can add conditions automatically from loan data
  ([Lender Toolkit, conditions with fields](https://lendertoolkit.com/powertools/conditions-with-fields/);
  [ICE loan conditions API](https://developer.icemortgagetechnology.com/developer-connect/reference/loan-conditions)).
  Our two-track model keeps *our* progress separate from *the lender's* answer. For a processing
  company that doesn't control the lender's system, that separation is the point.
