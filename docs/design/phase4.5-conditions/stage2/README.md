# Phase 4.5 Conditions: Stage 2 reference screens

These are the target screens for **Stage 2** (`docs/phases/phase4.5-stage2-tickets.md`): the
conditions list, statuses, the lender's answers, round comparison and the lender's dates.
Stage 1's screens are one folder up. The same rules and the same way of checking apply.

**How to use them.** Build a screen, run the app, open the same state with the same fixture data,
take a screenshot 1600 px wide in the light theme, and compare it with the PNG. Go through that
screen's **Must match** list. If a difference is not on its **May differ** list, fix it or **STOP AND
ASK**. Record the result in the ticket under "Visual check".

```
docs/design/phase4.5-conditions/stage2/
├── README.md        you are here
├── screens/*.png    what each screen should look like (1600 px wide, light theme)
└── html/*.html      the same screens as static HTML: exact wording, structure, tokens
```

The HTML is a mockup. Don't copy its markup: build with the real components (`StatusToken`,
`Sheet`, `Dialog`, `Button`, `EmptyState`, `Card`) and the Ledger tokens. All data is fictional
(the `uwm_round1` / `uwm_round2` fixtures and the new `uwm_round3`), and "today" in these screens is
**09/26/2026**.

---

## Rules every Stage 2 screen follows

1. **Stage 1's rules still hold.** It's the same shell, the lender's words are in serif, codes are
   mono, underwriter notes are dated chips, and AI is violet (Stage 2 has none).
2. **Statuses use `StatusToken`:** colour + glyph + word, never colour alone and never a filled
   background (`status-token.tsx`). A 2px left rail on the row carries the lender's state: amber
   for *Came back*, green for *Cleared*.

   | Track | Value | Word | Tone · glyph |
   |---|---|---|---|
   | Ours | `to_do` | To do | neutral · circle-dashed |
   | Ours | `waiting` | Waiting on *Owner* | progress · loader-circle |
   | Ours | `ready` | Ready to send | verified · circle-check-big |
   | Ours | `with_underwriter` | Sent to lender | progress · send |
   | Lender | `open` | Open | neutral · circle-dashed |
   | Lender | `not_cleared` | Came back | attention · triangle-alert |
   | Lender | `cleared` | Cleared | verified · circle-check-big |
   | Lender | `waived` | Waived | verified · circle-check-big |
   | Lender | `superseded` | Replaced | muted · corner-down-right |

   `review` and `pending_review` never appear (default A4).
3. **"Cleared" appears only next to a recorded verdict,** and the verdict always says where it came
   from ("Round 2 comparison · 09/10", "Portal · 09/12").
4. **"Probably cleared" is always a question with a button,** never a status.
5. **Nothing disappears.** Cleared conditions move to a collapsed "Cleared" section, with their codes
   listed on the section line.
6. **Refusals use the server's sentence** (LP-912), shown as-is.
7. **No Stage 3 buttons.** No "Email borrower", no "Request document", and no disabled placeholders
   for them.

---

## Screens

| # | File | Ticket | State |
|---|---|---|---|
| S2-01 | `S2-01-list-round1.png` | LP-913 | Round 1 imported, nothing touched: 11 × To do / Open |
| S2-02 | `S2-02-list-midwork-bulk.png` | LP-913, LP-912 | After round 2 is confirmed (acceptance step 5), 3 rows selected, bulk bar |
| S2-03 | `S2-03-condition-detail.png` | LP-916 | Detail sheet for `6637`, cleared by the round-2 comparison |
| S2-04 | `S2-04-record-lender-answer.png` | LP-912 | "Record the lender's answer" for 3 selected |
| S2-05 | `S2-05-move-back-reason.png` | LP-912 | Moving `0006` from Ready to send back to To do |
| S2-06 | `S2-06-what-changed-round2.png` | LP-915 | Round 2 (full, PDF) just imported: 5 probably cleared, letter changes |
| S2-07 | `S2-07-confirm-probably-cleared.png` | LP-915 | Same, with `0132` unticked → "Confirm 4 as cleared" |
| S2-08 | `S2-08-round3-reworded-cameback.png` | LP-915, LP-912 | Round 3 imported: came back, reworded pair, new |
| S2-09 | `S2-09-filtered-empty.png` | LP-913 | Filters match nothing |
| S2-10 | `S2-10-partial-round-no-suggestions.png` | LP-915 | Round 2 pasted as *Just some*: nothing suggested |
| S2-11 | `S2-11-lender-dates.png` | LP-917-lite | Lender dates in the file rail and on the round card |

### S2-01 List after round 1
**Must match:**
- The round strip from Stage 1.
- A **summary bar** with seven numbers: Open 11 · Came back 0 · Cleared 0 · Waived 0 ·
  Information 0 · Prior to docs open 6 · Prior to funding open 5. Each number is a filter. A zero is
  never coloured.
- A **filter row**: search, then Our status · Lender · Owner · Heading · Round, and "Group by:
  Lender's heading" on the right.
- **Groups** use the lender's heading in sheet order, with a kind chip and a count.
- **Columns:** select · code (with `R1` chips under it) · the lender's words (serif, clamped to two
  lines) · owner · our status (an inline select) · lender status.
- Underwriter notes show as chips under the wording (`6132`, `6637`).
- An unknown owner reads "Not known".

**May differ:** column widths, the exact clamp, and icons of the same meaning.

### S2-02 List mid-work, bulk
**Must match:**
- Summary: Open 6 · Came back 0 · Cleared 5 (green) · Prior to docs open 1 · Prior to funding open 5.
- Round 2's card shows "6 on sheet · 0 new · 5 cleared".
- Only open conditions are in the groups. The heading with none left open
  (Compliance) isn't shown.
- Mixed statuses: Waiting on Title (`1947`, `6378`), Ready to send (`0006`), To do.
- A **collapsed "Cleared" section** lists `7086, 6132, 6637, 6178, 0132`.
- **Selected rows** have a tinted background and a ticked box.
- A **bulk bar** is pinned at the bottom: "3 selected · 1582 · 0006 · 0007", then Set status ▾ ·
  Owner ▾ · **Record lender's answer ▾** (the emphasised one), and a close ×.

**May differ:** the bulk bar's colours, as long as it contrasts in both themes. Its position may be
the top of the list instead.

### S2-03 Condition detail (sheet)
**Must match:**
- A right-hand `Sheet` about 480 px wide. The header has the code, category and heading, plus
  **Previous / Next** buttons (↑ ↓) and a close ×.
- The **lender's words** are larger and in serif, with a **Copy text** button.
- Chips for the kind and the owner, with its source ("Borrower · from code map").
- A **status block** with Our status (a select), Owner (a select marked "suggested" when it isn't
  overridden), and Lender: Cleared with **Reopen**.
- A **verdict callout**: "Cleared · round 2 comparison · 09/10/2026 · Not on the lender's full list
  printed 09/10. Confirmed by Priya Raman on 09/10 at 4:31 PM."
- **Underwriter notes** show the round they arrived in.
- **Rounds** as pills: "R1 08/28 · on the sheet ✓", "R2 09/10 · full list · not on it —".
- **History** in plain words, newest first, one line per event. The five lines shown are the
  expected sentences for those event kinds.

**May differ:** the sheet width, and date formatting within the app's convention.

### S2-04 Record the lender's answer
**Must match:**
- The title "Record the lender's answer" and the count ("For 3 conditions"), with the one-line
  warning to record only what the lender said.
- The affected conditions listed: code plus a clamped serif line each.
- **Three choices,** each shown with its StatusToken and a one-line meaning: Cleared ("Lender signed
  it off"), Waived ("Lender dropped it"), Came back ("Lender says not satisfied").
- **Where:** Portal / Email / Phone. **Date the lender said it:** a date that must be filled in, and
  is not assumed to be today by the server.
- An optional note.
- The button text includes the count: **Record for 3 conditions**.

**May differ:** the radio style (cards or a list).

### S2-05 Move back needs a reason
**Must match:**
- The title names the code and the target: "Move 0006 back to To do?".
- The *from → to* tokens, and the condition's wording.
- **A required reason,** with the hint "Moving back keeps the history. Moving forward never needs a
  reason."
- Buttons: **Move back** / Cancel.
- The same dialog, retitled, serves **Reopen** ("Reopen 0006?").

### S2-06 What changed in round 2
**Must match:**
- The round card shows "5 probably cleared — review".
- The panel sits above the summary bar, titled "What changed in round 2", then "Round 2 · printed
  09/10/2026 · Full list", then "Compared with the 11 conditions that were open before it."
- **Count pills:** Probably cleared 5 · Came back 0 · Reworded 0 · New 0 · Still open 6.
- The **probably cleared** list has all five ticked (`7086 6132 6637 6178 0132`). Each shows the
  code, a clamped line of wording, and "last on round 1 · 08/28".
- The line "Nothing changes until you confirm. Each one is recorded as Cleared · round 2
  comparison · 09/10/2026."
- **Confirm 5 as cleared** (primary) and **Not now**, with its explanation.
- **Letter changes since round 1**, showing only the changed values, old struck through → new: note
  rate, ratios, verified assets, max funds to close, rate lock, UW team, close-by expiry, asset
  expiry. There's also a line naming what didn't change.
- **Still open**, collapsed, with its codes.
- In the list below, the suggested rows carry "Probably cleared in round 2 — review", and their
  statuses are still Open.

**May differ:** whether the panel sits above the list or in a sheet, as long as it opens
automatically after an import that has something to confirm.

### S2-07 Confirm with one unticked
**Must match:**
- `0132` unticked.
- The note "0132 stays Open and loses the suggestion. You can still record the lender's answer on
  it by hand."
- The button reads **Confirm 4 as cleared**. The number is live.

### S2-08 Round 3: came back, reworded, new
**Must match:**
- Round 3's card: "5 on sheet · 2 new · 3 seen again". The reworded one counts as new at import.
  "All rounds" shows 13.
- **Count pills:** Came back 1 · Reworded 1 · New 1 · Probably cleared 2 · Still open 2.
- **Came back:** `1228` with an amber rail, its `R1 R2 R3` chips, the new chip "9/18 Inspection
  shows incomplete items", Lender "Came back", and the sentence "set by the lender's 9/18 note ·
  our status moved from Sent to lender back to To do".
- **Reworded?:** `6378` with "Same code, different wording", then *Was · R1–R2* (muted) above
  *Now · R3*. Buttons: **Same condition — replace the old one** and **Different conditions — keep
  both**, with the line "Nothing happens until you choose."
- **New:** `7383`, with `R3` only, Open, and its category, kind and owner.
- **Probably cleared (2: 0006, 0007)**, collapsed with **Review**.
- **Still open (2: 1947, 1582)**, collapsed.
- "No changes on the letter since round 2."
- The old `6378` is **not** in Probably cleared.

### S2-09 Filtered to nothing
**Must match:**
- The active filters are highlighted in the filter row ("Owner: Insurance", "Our status: Waiting")
  and **Clear filters** appears.
- `EmptyState kind="filtered"` names the filter: "No open condition is waiting on Insurance".
- One line explains *why*, from the data: 6178 was cleared in round 2.
- **Clear filters** button.
- The Cleared section is still shown below.

**May differ:** the explanation line may be left out if it can't be derived cheaply. The named
filter must stay.

### S2-10 Partial round: nothing suggested
**Must match:**
- The round card shows "Pasted · Just some", with **no** "probably cleared" mark.
- The panel has Came back / Reworded / New / Still open, and **no Probably cleared pill**.
- An info callout: "This round was just some conditions, so nothing is suggested as cleared. The 5
  conditions that weren't in the paste stay exactly as they are…", with **Switch to Full list**
  (primary) and **Attach the lender's PDF**.
- "A paste has no letter details, so there are no letter changes to show."
- In the list, the five round-1-only conditions are Open with **no** suggestion line.

### S2-11 Lender dates
**Must match:**
- The file rail has a new **Lender dates** section between Ratios and Recent activity, headed "From
  round 2, printed 09/10".
- The dates: Must not close before 09/30/2026 · Must fund by — · Rate lock expires 09/30/2026 ·
  Soonest doc expiry 11/03/2026, with "Close by and income docs · 38 days" under it (today is
  09/26/2026).
- **Plain text only:** no colours for "soon", no alert icons.
- Round 2's card adds "Lock 09/30/2026 · Not before 09/30/2026" and a "Letter details →" link to
  S1-09.
- With no dated round, the section reads "No dates from the lender yet." (not drawn).

---

## Checking your work against a screen

The same as Stage 1. Seed the file with the fixtures using the Stage 2 acceptance steps (§5 of the
tickets file), open the state at 1600 px, put your screenshot beside the PNG, go through the Must
match list, and write the result under "Visual check" in the ticket file.
