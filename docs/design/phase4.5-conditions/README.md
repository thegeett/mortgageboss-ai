# Phase 4.5 Conditions: Stage 1 reference screens

These are the target screens for **Stage 1** of the build spec
(`docs/phases/phase4.5-stage0-1-build-spec.md`): upload, forward, paste, review, import, add by hand.
Stage 0 (LP-903) has no UI.

**How to use them.** Build a screen, run the app, open the same state with the same fixture data,
take a screenshot 1600 px wide, and compare it with the PNG here. Check it against the
**Must match** list for that screen. If your screen is different and the difference is not on the
**May differ** list, fix it or **STOP AND ASK**.

```
docs/design/phase4.5-conditions/
├── README.md        you are here
├── screens/*.png    what the screen should look like (1600 px wide, light theme)
└── html/*.html      the same screens as HTML, so you can read exact wording, spacing and colour tokens
```

The HTML is a static mockup. It is **not** code to copy. Build with the real components
(`components/ui/*`, `EmptyState`, `StatusToken`, `Dialog`, `Sheet`, `Button`, `Badge`) and the Ledger
tokens. The HTML loads IBM Plex from a local `fonts/` folder that isn't committed, so it shows a
fallback font when opened from the repo. The PNGs show the real fonts.

All data is fictional and comes from the synthetic fixtures in the spec, §7:
`uwm_round1` / `uwm_round2` (file *Alex Rivera*, LF-R7QK) and `uwm_master_pagebreak`
(file *Jordan Ellis*, LF-E2WM). Real condition sheets never enter the repo (ADR-405).

---

## Rules every screen follows

1. **The shell is the existing app's.** Icon rail, the *File* context column with **Conditions** selected,
   top bar with breadcrumb, `FileHeader`, and the right file context rail. The Conditions tab only
   changes the work surface. Don't add a second navigation or a tab strip.
2. **The lender's wording is shown in IBM Plex Serif** (`font-serif`, the Ledger rule for text quoted
   from a document). Codes are mono. Everything else is Plex Sans.
3. **Stage 1 has no status controls.** Nothing says "cleared", "done", "satisfied", "open" or
   "to do". No checkboxes on conditions, no board, no drag. The only checkbox is "I checked the
   flagged rows" on the review screen.
4. **AI is always marked** in the `--ai` violet, with the sparkles icon and a 2 px left stripe on the
   row. Rows read by rules get no AI marking.
5. **Underwriter notes are dated chips** (warning left border, mono date, then the note). They are
   never merged into the lender's wording.
6. **Wording people can trust:** "Nothing is saved to the file until you import." and "Import never
   removes or clears a condition." sit next to the Import button.
7. **Colours come from tokens only.** Primary is petrol and warning is amber. `--ai` is used only for AI.
   No raw hex values and no new colours.
8. **Dark mode** comes from the tokens. It isn't drawn here, but check that it isn't broken.

---

## Screens

| # | File | Ticket | State |
|---|---|---|---|
| S1-01 | `S1-01-empty-state.png` | LP-909 (UI 1), LP-905 | Conditions tab, no rounds |
| S1-02 | `S1-02-reading.png` | LP-905, LP-909 (UI 3) | Round `PARSING` after upload |
| S1-03 | `S1-03-read-failed.png` | LP-905, LP-909 (UI 3) | Round `PARSE_FAILED` |
| S1-04 | `S1-04-review-round1-pdf.png` | LP-906, LP-909 (UI 4) | Round 1 `DRAFT` from `uwm_round1` PDF |
| S1-05 | `S1-05-imported-round1.png` | LP-909 (UI 5) | Just after importing round 1 |
| S1-06 | `S1-06-paste-dialog.png` | LP-907, LP-909 (UI 2) | Paste dialog, round-2 text |
| S1-07 | `S1-07-review-round2-paste.png` | LP-907, LP-909 (UI 4) | Round 2 `DRAFT` from paste, *just some* |
| S1-08 | `S1-08-imported-round2.png` | LP-909 (UI 5) | After importing round 2 |
| S1-09 | `S1-09-round-details-enriched.png` | LP-907 (attach PDF), LP-909 | Round-details sheet after attaching the round-2 PDF |
| S1-10 | `S1-10-review-ai-split-flagged.png` | LP-908, LP-909 (UI 4) | AI split of an unstructured paste, one row being edited |
| S1-11 | `S1-11-review-pagebreak-warnings.png` | LP-906, LP-909 (UI 4) | Review of `uwm_master_pagebreak` with warnings |
| S1-12 | `S1-12-add-by-hand.png` | LP-909 (`POST …/conditions`) | Add-a-condition dialog |
| S1-13 | `S1-13-inbox-use-as-condition-sheet.png` | LP-905 (forward) | Communication tab, "Use as condition sheet" |

### S1-01 Empty state
**Must match:** title "No conditions yet" with the explanation under it. **Four ways in**, laid out 2 × 2:
*Upload the approval letter* comes first, has the petrol border and a "Recommended" badge, and holds a
drop zone with a "Choose PDF" button and "PDF only · up to 20 MB". *Paste conditions*. *Forward the
lender's email* shows the file's inbox address (`lf-{inbox_token}@{domain}`, the same one the
backend builds) with a Copy button. *Add one by hand*.
**May differ:** the icons (any lucide icon with the same meaning) and the exact width of the cards.

### S1-02 Reading
**Must match:** a quiet progress card with the filename (mono), page count and "usually under 30
seconds". Four steps: Stored → Finding conditions → Reading the letter details → Ready to review.
Skeleton rows under it. The line "You can leave this page…". The file rail's Recent activity shows
"Condition sheet received". Poll until `DRAFT` or `PARSE_FAILED`. No spinner over the whole page.
**May differ:** whether the steps come from the server or are timed on the client. Showing only the
current step is fine.

### S1-03 Read failed
**Must match:** the headline says what happened in plain words. A red callout shows the human reason,
then the **typed reason code and the readers that were tried** in mono (from `parse_report`). Actions:
Try again (primary), Upload a different PDF, Paste instead, Discard. A non-PDF or too-large upload is
refused **before** a round exists and appears as a message using the exact sentences on this screen.
**May differ:** where the refusal message shows (a toast or inline).

### S1-04 Review: round 1 from the PDF, the main screen
**Must match:**
- Top card: "Review · not imported yet" (amber label); the format name; chips for the source and
  "Date printed 08/28/2026"; which reader was used ("Read by rules (uwm v1) — no AI"); a *Full list /
  Just some* toggle (**Full list** is the default for a PDF); the round date; a count line: 11
  conditions · 3 headings · 2 with underwriter notes · 0 warnings / 0 lines left over / 0 duplicates.
- Rows are **grouped by the lender's own heading, in sheet order**. Each group header shows the heading
  word for word, a chip with its kind ("Prior to docs", "Prior to funding", "Lender clears"; no chip
  when the kind equals the heading, as with "Master") and a count.
- A row has four columns: code (mono), category, the lender's wording (serif), and then the owner hint
  chip with its source under it ("from code map" / "from “TC:” prefix" / "from bucket"; "Owner not
  known" when there is none), with edit (pencil) and remove (×) buttons.
- `6132` and `6637` show the chip `8/28 · Not in Upload`. `0132` has **no** note chip:
  `***NOTE***` is part of the lender's wording.
- Side panel "Also read from the letter": Lender team, Loan figures on the letter, Document expiry
  (all 12 keys in the lender's order, "—" where empty), and the Mortgagee clause with a Copy button.
  The values are the ones in the spec §7.1.
- A sticky bottom bar with the two trust sentences, **Discard** (destructive ghost) and
  **Import 11 conditions** (primary; the number is live).

**May differ:** column widths; whether the side panel collapses below about 1280 px (it may go under the
list); icons.

### S1-05 After importing round 1
**Must match:** the tab actions **Add a condition · Paste · Upload sheet** (the last one primary). A
**round strip**: an "All rounds" card with the total, then one card per round with its number, date,
source chips, completeness and counts ("11 on sheet · 11 new"), plus a "Letter details →" link that
opens S1-09. An info callout: "This is the lender's list exactly as issued. Only the lender clears a
condition…". The list is grouped by heading like the review screen, but read-only: no edit or remove,
and a mono chip on each row for every round it was on (`R1`). A toast: "Conditions imported · Round 1:
11 new, 0 seen again". The same summary appears in the file's Recent activity.
**May differ:** the toast component, and whether clicking a round card filters the list to that
round (nice to have, not required).

### S1-06 Paste dialog
**Must match:** a mono textarea. A line under it with the line and character count (the server limit is
100,000 characters). "What did you paste?" with two radio options, each explained in one line.
**"Just some conditions" is selected by default.** A round date that defaults to today, with its one-line
explanation. Cancel, then **Read conditions** (primary).
**May differ:** the dialog width, and a live count only (no hard limit shown) when well under the limit.

### S1-07 Review: round 2 from a paste
**Must match:** the same review layout. The source chips are "Pasted" and "Just some", with **no
"Date printed" chip** (a paste has none). The format line says the UWM layout was recognised in the
pasted text. An info callout explains what *just some* does at import. The side panel says a paste has
no letter details and points to attaching the PDF after import (it merges into this round, and no
second round is created). 6 rows in 2 groups.

### S1-08 After importing round 2
**Must match:** the round strip now has Round 2 ("Pasted", "Just some", "6 on sheet · 0 new · 6 seen
again") with an **"Attach the lender's PDF"** button, which appears only on rounds that have no PDF source.
**Still 11 conditions.** The 6 that were seen again show `R1 R2`; the other 5 show `R1` only and are
**not** marked as missing, removed or cleared. An info callout says the 5 were left as they are. A toast:
"Round 2: 0 new, 6 seen again".

### S1-09 Round details (sheet), after attaching the PDF
**Must match:** a right-hand `Sheet` titled "Round 2 · 09/10/2026". Its chips are now `Pasted` and
`PDF upload` (sources appended), plus the completeness and the format. A success callout says what the PDF
filled in, and that it added **no new conditions and no second round**. Below that: Lender team (UW
Team **Lightning**), Loan figures (6.490%, $41,914.42, rate lock 09/30/2026), Document expiry, the
Mortgagee clause, and a short history built from the round's `condition_events`.
**May differ:** the sheet width, and whether history shows times.

### S1-10 Review: AI split with flagged rows
**Must match:** "Plain text · no lender layout found" and "Split by AI (split v1) · rules found no
rows". The count line marks the AI rows in violet and the left-over line in amber. A "Check before
importing" card holds:
(a) an AI callout that says **AI only splits** and that anything not in the paste was thrown away;
(b) the line left over, quoted in serif, with **Add as a condition** and **Ignore this line**.
Every AI row has the violet stripe and a "Split by AI · 0.60" chip. Rows under 0.80 are sorted first.
One row is shown **in edit mode**: a serif textarea with a primary focus ring, **Save wording** and
Cancel, and the hint "Only fix what the reader got wrong…".
The bottom bar has an **unticked "I checked the flagged rows"** checkbox, and **Import is disabled**
until it is ticked.
**Test:** editing a row and importing sends the edited text (the spec's LP-909 frontend test).

### S1-11 Review: page break with warnings
**Must match:** a warnings card listing **each** warning. There are 2 × "Duplicate dropped" (code plus
the start of the wording, and where it happened) and 1 × "Letter header not found". 16 rows in 4 groups:
Master (1), UW PTD (8), Underwriter To Obtain And Clear (4, chip "Lender clears", owner "Lender · from
bucket"), and Closing (PTF) (3). All three `0571` rows show, each with its own different wording. The
notes on `1594` and `4235` are chips, not part of the wording. The side panel says "Not found on this
sheet." for the team and the figures, but still shows the expiry dates and the mortgagee clause. There is
no "Date printed" chip, because the header wasn't found.

### S1-12 Add a condition by hand
**Must match:** the text under the title says which round the condition goes into ("round 1
(08/28/2026), the latest imported round"). If there is no imported round, it says "Starts round 1
(typed)". The "Lender's wording" serif textarea (required) has the hint "Type it exactly as the lender
wrote it.". There are optional **Lender code** and **Category** fields and a **Heading** select (the
bucket kinds). Then Cancel and **Add condition**.

### S1-13 Communication: Use as condition sheet
**Must match:** on a PDF attachment that is waiting for a decision, **Use as condition sheet** is the
first and primary action. The existing *Accept / Correspondence / Reject* buttons stay (ghost) and
behave as they do today. Once it is used, the attachment reads "Kept as correspondence" and shows a
link: "Used as condition sheet → Round N". When the file's newest round was **pasted and has no PDF
yet**, choosing the action asks whether to **attach it to that round** (the LP-907 merge) or **start a
new round**. The second message on this screen shows the result of attaching.
**May differ:** the confirm UI for "attach or new round" (a small dialog or a popover).

---

## What these screens add to the spec

The build spec has been updated to match. These are listed so nothing surprises you:

1. **Rounds each condition was on.** The list shows `R1 R2` chips. `GET /api/loan-files/{id}/conditions`
   returns `round_numbers: int[]` for each condition, built from its `CONDITION_CREATED` and
   `CONDITION_SEEN_AGAIN` events, or from a join table if the survey finds one is simpler.
2. **The list is grouped by heading, with the round strip above it.** This replaces "grouped by round,
   then bucket" in LP-909 UI 5.
3. **A round-details sheet** (S1-09) shows the round's `header`, `expiry_dates`, mortgagee clause and
   event history after import. It uses the existing `GET /api/condition-rounds/{id}`.
4. **"Attach the lender's PDF"** on a round card with no PDF source calls the existing
   `POST /api/condition-rounds/{id}/attach-pdf`.
5. **Forward into a pasted round.** `POST /api/inbound/attachments/{id}/condition-round` accepts an
   optional `attach_to_round_id`. When it is set, it runs the LP-907 merge instead of creating a round.
6. **Draft editing on the review screen** (edit the wording, remove a row, add or ignore a left-over
   line) stays on the client and is saved with the existing `PUT …/draft`.

## Checking your work against a screen

1. Seed a file with the fixture (the spec §8 acceptance steps give you each state).
2. Open the state at a **1600 px wide** window, light theme.
3. Take a screenshot. Any tool is fine; the repo has no Playwright, so don't add one just for this.
4. Put it next to the PNG and go through that screen's **Must match** list. Write the result in the
   ticket file (`docs/tickets/LP-9xx.md`, section "Visual check"), for example
   `S1-04: matches; side panel wraps at 1366 px (allowed)`.
