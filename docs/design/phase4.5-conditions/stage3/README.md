# Phase 4.5 Conditions: Stage 3 reference screens

These are the target screens for **Stage 3, "Work the conditions"**
(`docs/phases/phase4.5-stage3-plan.md`): reading each condition into items, the plan for a round,
the drafts to the borrower, third parties and the underwriter, checking evidence when it comes back,
the figures check, the package and the lender settings. Stage 1's screens are in
`docs/design/phase4.5-conditions/` and Stage 2's in `stage2/`. The same rules and the same way of
checking apply.

**How to use them.** Build a screen, run the app, open the same state with the same fixture data,
take a screenshot 1600 px wide in the light theme, and compare it with the PNG. Go through that
screen's **Must match** list. If a difference is not on its **May differ** list, fix it or **STOP AND
ASK**. Record the result in the ticket under "Visual check".

```
docs/design/phase4.5-conditions/stage3/
├── README.md        you are here
├── screens/*.png    what each screen should look like (1600 px wide, light theme)
└── html/*.html      the same screens as static HTML: exact wording, structure, tokens
```

The HTML is a mockup. Don't copy its markup: build with the real components (`StatusToken`,
`Sheet`, `Dialog`, `Button`, `Card`, `EmptyState`) and the Ledger tokens. The email dialogs reuse
the Phase 4 draft dialog (LP-809/LP-820) as it is. All data is fictional: the `uwm_round1` fixture,
the fictional borrower Alex Rivera, `example.com` / `.example` addresses, and fictional bank
statements. Real borrower data never goes into fixtures or screens (ADR-405).

**"Today" in these screens** follows the file's story:

| Screens | Moment |
|---|---|
| S3-01 to S3-06 | 08/28/2026, round 1 just imported and planned (S3-02 at 4:21 PM, before confirming) |
| S3-07, S3-08, S3-12 | 09/02/2026, the borrower's statements arrived through the upload link at 9:14 AM |
| S3-09 | 09/08/2026, evidence for 7086 and 6178 accepted |
| S3-10 | 09/09/2026, 5:46 PM, package for round 1 (2 h 14 m before UWM's 8 PM ET cutoff) |
| S3-11 | Any day (admin settings) |

---

## Rules every Stage 3 screen follows

1. **Stage 1 and 2 rules still hold.** Same shell, the lender's words in serif, codes in mono,
   underwriter notes as dated chips, statuses as `StatusToken` (colour + glyph + word, never a fill).
2. **AI is violet, and always labelled.** Anything the AI read or wrote carries a violet "Read by AI ·
   0.93" or "drafted" mark. Numbers are never the AI's: they carry "computed by code" or "numbers
   checked by code".
3. **Below the confidence bar, nothing is drafted.** A reading under the bar shows an amber
   "0.64 · confirm" mark and the confirm dialog (S3-03). The plan's confirm button stays disabled until
   it's answered.
4. **Nothing is sent by the app.** Every email is a draft with **Copy & open Gmail**, **Copy message**,
   **Mark as sent** and **Delete draft**. The dialog's subtitle says so.
5. **The lender's track never moves by itself.** Our status moves automatically (email marked sent →
   *Waiting on …*; evidence passes → *Ready to send*; Mark submitted → *Sent to lender*), each move
   an event. The lender's column stays *Open* until a verdict is recorded (Stage 2).
6. **Figures change only when she applies them** (S3-09), through the stated-financials edits.
7. **Privacy in email bodies:** last four only for account numbers, no SSNs, documents come back
   through the borrower upload link (scoped to the round's items), not by email.
8. **No new colours.** Waiting uses the progress tone, failures use the blocking tone, findings use
   the attention tone, and "Lender is doing it" / "Information only" are neutral (Stage 2's display).
9. **The Lender package tab stays as it is** (Phase 6). The Stage 3 package is on the Conditions tab.

---

## Screens

| # | File | Ticket | State |
|---|---|---|---|
| S3-01 | `S3-01-condition-items.png` | LP-919, LP-920, LP-921 | Detail sheet for `6637`: reading, 3 items, who acts, next step |
| S3-02 | `S3-02-round-plan.png` | LP-920, LP-921 | "Plan for round 1", before confirming, `0132` needs confirming |
| S3-03 | `S3-03-confirm-reading.png` | LP-919 | "Please confirm how we read 0132" (0.64) |
| S3-04 | `S3-04-borrower-email.png` | LP-922 | The borrower email for round 1 (7086, 6132, 6637) |
| S3-05 | `S3-05-title-email.png` | LP-922 | The title/attorney email (6637, 0132, 1947, 6378) with the insurance note |
| S3-06 | `S3-06-underwriter-question.png` | LP-921, LP-922 | Push-back on `6178` to the underwriter |
| S3-07 | `S3-07-evidence-checked.png` | LP-923 | `6132`: August statement arrived, page 6 missing |
| S3-08 | `S3-08-evidence-new-finding.png` | LP-923 | `7086`: statements arrived, $4,000 deposit needs sourcing |
| S3-09 | `S3-09-figures-check.png` | LP-924 | 2 changes from accepted evidence, no DU re-run |
| S3-10 | `S3-10-package.png` | LP-925 | Package for UWM round 1: 6 conditions, 26 pages |
| S3-11 | `S3-11-lender-settings.png` | LP-925 (codes table: LP-918) | Admin → Lenders → United Wholesale Mortgage |
| S3-12 | `S3-12-list-next-steps.png` | LP-921 | The Stage 2 list with a **Next step** column, on 09/02 |

### S3-01 Condition detail with items
**Must match:**
- Stage 2's detail sheet (header with code, category, heading, ↑ ↓ and ×; the lender's words in
  serif with **Copy text**; the `8/28 Not in Upload` note chip).
- A violet **"How we read it"** box: one plain sentence, the chips **Read by AI · 0.93** and
  **Library: AS-04 Earnest money**, and the rule line citing Fannie Mae B3-4.3-09.
- **Items · 3**, with **Add an item**. Each item has a number, a bold name, what's acceptable, the
  account (`··9912`) and month, **who acts** (Borrower / Title / escrow / Borrower) with the option
  under it, and where it is (**In borrower email · draft**, **In title email · draft**).
- **Shared items are shown:** item 1 "Same statement as 7086 and 6132, asked for once", item 3 "Same
  Aug statement answers 6132".
- **Next step** chips with the chosen ones selected (Ask the borrower, Ask a third party), plus
  Already in the file and Ask the underwriter.
- Our status select (To do), lender Open, and the line "Becomes **Waiting on Borrower** when the
  borrower email is marked sent."

**May differ:** item card layout (grid or stacked), chip order, icons of the same meaning.

### S3-02 Plan for round 1
**Must match:**
- A panel under the round strip: **"Plan for round 1"**, "11 conditions · 08/28/2026 · nothing has
  been sent", and the line saying every step is a proposal.
- **Summary pills:** 3 emails to draft (Borrower · Title/attorney · LO) · Your tasks 2 · Already in the
  file 1 · Push back 1 · Lender is doing it 1 · **Please confirm 1** (amber).
- **One row per condition, sheet order:** code · a short plain summary plus "items → who" · the next
  step as a select (two for 6637) with a reason under it · the reading's confidence.
- The reasons shown: "Ordered through the lender — confirm on your files" (1228), "Shortfall
  computed by code" (7086), "Reason from the letter" (6178), "Found: Credit invoice 07/15, page 1"
  (0006), "Waits on 1228" (0007), "Added to the title email" (6378).
- **0132** is tinted, with **0.64 · confirm** and "Please confirm how we read this".
- **Confirm plan and draft 3 emails** is disabled, with "Confirm 0132's reading first — one condition
  still needs you." and **Review one by one** beside it. **Hide** at the top right.

**May differ:** pill wrapping, whether the confidence shows as a number or a small bar (the number
must be available on hover).

### S3-03 Confirm the reading
**Must match:**
- A `Dialog` "Please confirm how we read 0132" with the line "The reading is below our confidence
  bar, so nothing is drafted for this condition until you confirm it."
- The lender's words in full (serif), then **"What we think it asks · 3 items"** with **Read by AI ·
  0.64**.
- Each item is editable text with a **who** select (Borrower + LO, LO, Attorney) and a remove ×.
- An amber callout: why it's unsure, and "Your answer is saved for this lender code (0132) so the next
  file reads it the same way."
- Buttons: **Use the library default** (text), **Add an item**, **This is right** (primary).

**May differ:** the width of the dialog, the select style.

### S3-04 Borrower email
**Must match:**
- The Phase 4 draft dialog: title "Email to the borrower · round 1", subtitle saying nothing is sent
  from the app.
- Left column **In this email** with ticked conditions (7086, 6132, 6637), **Asked once** ("The July
  and August statements answer 7086, 6132 and 6637…"), and **Privacy**.
- To: Alex Rivera; Subject "Documents needed for your loan — 2 items".
- Body: a due date (**Thursday, September 3**), a numbered list where each item says **what**
  (bold), the acceptable form (all pages, PDFs from the bank's website, not screenshots) and a grey
  **Why:** line, then "Upload them here: Secure upload link for your loan", and the signature.
- Account shown as **ending 9912** only.
- Buttons: **Copy & open Gmail** (primary), **Copy message**, **Mark as sent**, **Delete draft**.

**May differ:** the wording of the greeting and sign-off, the due-date rule's result if the rule
changes, the left column's width.

### S3-05 Title/attorney email
**Must match:**
- Title "Email to the title company / attorney · round 1". Ticked: 6637 Earnest money receipt,
  0132 Matching wire instructions, 1947 Final seller CD (prior to funding), 6378 Loan number on
  checks.
- **Other drafts this round**: Borrower · 3 conditions, LO · 0132 disclosure.
- **Insurance emails** note with the mortgagee clause shown in mono exactly as the letter prints it.
- Body names the file as "RIVERA · UWM loan 1226500417" with the property address, then 4 numbered
  items: the earnest money receipt ($2,850.00, statement or canceled check), wire instructions, the
  final seller CD "(needed before funding)", and the loan number on every check.

**May differ:** as S3-04.

### S3-06 Question to the underwriter
**Must match:**
- Title "Question to the underwriter · 6178", To "Lena Brennan (UW II)" from the lender contacts.
- **Why we think so**: two ticked facts, "Letter, round 1: Must Not Close Before 09/30/2026" and
  "Condition text: policy not effective until 09/30/2026", and the note that both dates were read by
  code, not AI, and that our status becomes **Waiting on Lender** when marked sent.
- The body states the two dates and asks "Could you clear 6178, or let me know what else you need?"

**May differ:** as S3-04.

### S3-07 Evidence checked: a check failed
**Must match:**
- The detail sheet for 6132, subtitle "Assets · evidence arrived".
- The document card: "Capital One statement ··9912 · August 2026 · 5 pages", "Arrived through the
  borrower upload link · Sep 2, 9:14 AM · linked to this condition automatically", **Open**.
- **Checks**, each with a pass (green) or fail (red) glyph and a plain reason: Right account · Right
  period ("the month right after July, already in the file") · Right borrower · Inside the lender's
  dates (statement 08/31/2026, expiry 10/30/2026) · **All pages** failed ("pages 1–5 of 6 — page 6 is
  missing").
- A blocking callout: "Not ready: 1 check failed. The condition stays Waiting on Borrower.", with
  **Add "please send page 6" to the borrower email** (primary) and **Accept anyway…**.
- The note that Accept anyway needs a reason and is kept in the history.

**May differ:** the order of the checks, the document card's layout.

### S3-08 Evidence: a new finding
**Must match:**
- The sheet for 7086 with the document "Capital One statements ··9912 · July and August 2026 · 12
  pages".
- Checks: Right account and period · Inside the lender's dates · **Enough for closing** (verified
  $41,914.42 against $38,210.40) · **No unexplained large deposit** failed (08/21/2026 mobile deposit
  $4,000.00).
- An attention box **"New finding: a large deposit needs sourcing"** with the chip **Fannie Mae
  B3-4.2-02** and the four figures: deposit $4,000.00 · threshold $2,870.66 (50% of $5,741.32 monthly
  income) · assets without it $37,914.42 · required $38,210.40.
- The reason in plain words (needed to close, so it must be sourced; payroll deposits need nothing),
  **Ask the borrower to explain it** (primary) and **It's already explained…**.
- "7086 stays **Waiting on Borrower** until this is answered. All figures above are computed by code."

**May differ:** table styling inside the box.

### S3-09 Figures check
**Must match:**
- A panel under the round strip: **Figures check**, "2 changes from accepted evidence", "Computed by
  code… Nothing changes in the file until you apply it."
- A table: Figure · In the file (struck through) · → · From evidence (bold) · Source.
  Verified assets $11,062.18 → $41,914.42 (7086) · Monthly homeowners insurance $120.00 → $155.00
  (6178) · Housing ratio 32.51% → 33.12% · DTI 40.36% → 40.97% ("+0.61 points").
- Two green callouts: "Assets now cover closing" and "**DU re-run not needed**… (Fannie Mae B3-2-10)".
- The line explaining when it would say **"Re-run DU before submitting"**.
- **Apply 2 changes to the file's figures** (primary), **Not now**, and "Applies through the file's
  stated assets and expenses, with the evidence linked."
- The file rail still shows the old ratios (40.4%, 32.5%): nothing is applied yet.

**May differ:** where the panel opens (inline or a sheet), number alignment.

### S3-10 Package
**Must match:**
- **"Package for UWM · round 1"**, "6 conditions ready · 26 pages", and the cutoff chip "UWM upload
  cutoff 8:00 PM ET · 2 h 14 m left".
- An attention warning: "**1228 (prior to docs) is still open** — … Docs cannot be drawn until it
  clears."
- An info line: prior-to-funding items (1947, 1582, 0007, 6378) are not included.
- One row per condition: tick · code · file name `7086 - Assets.pdf` (mono) · pages · an editable
  **note for the underwriter** with the violet "drafted · numbers checked by code" mark. 6178 has no
  file and its note explains why.
- **Download package (5 PDFs + notes)** (primary), **Copy all notes**, **Mark submitted**, and "Mark
  submitted after you upload in EASE — it moves these 6 to **Sent to lender**."

**May differ:** the file-name font, note box height, the order of the two warnings.

### S3-11 Lender settings
**Must match:**
- The admin shell (Administration → Lenders), title "United Wholesale Mortgage", **Save changes**.
- Rows: **Mortgagee clause** (mono, filled from the approval letter) · **Condition upload cutoff**
  (8:00 PM, Eastern) · **What the upload asks per condition** (A note ticked; Name of source and Date
  verified unticked; "Sun West asks for all three.") · **Who does what at this lender** (final
  inspection ordered by the lender ticked; Processor Assist and Underwriting+ defaults unticked) ·
  **Lender codes to review** (7812 mapped to CR-05, 6521 "Choose a type").

**May differ:** field widths, whether the codes table is its own tab.

### S3-12 List with next steps
**Must match:**
- Stage 2's list with a **Next step** column between the lender's words and our status. Each cell is
  a token with a glyph: mail (email sent, with the date), a red circle-x "Evidence failed a check —
  page 6" (6132), "Deposit explanation asked · 09/02" (7086), "Question to UW · sent 08/28" (6178),
  "Your task · upload the invoice" (1582), "Already in the file · p.1" (0006), "Waits on 1228" (0007),
  "Lender is doing it" (1228).
- **Summary bar:** Open 11 · Waiting on others 7 · Your tasks 2 · Ready to send 1 · **Failed a check
  1** (red) · Prior to docs open 6 · Prior to funding open 5. The numbers overlap (6132 is both
  waiting and failed); each number is a filter.
- **1228**'s status is "Lender is doing it" (neutral, no select), Stage 2's display rule.
- Our statuses: Waiting on Borrower (7086, 6132, 6637), Waiting on Lender (6178), Waiting on LO
  (0132), Waiting on Title (1947, 6378), To do (1582, 0007), Ready to send (0006). Lender: all Open.

**May differ:** column widths, whether the next step is one line or wraps.

---

## Checking your work against a screen

The same as Stages 1 and 2. Seed the file with `uwm_round1`, run the Stage 3A acceptance steps
(§6 of the plan) for S3-01 to S3-06 and S3-12, and the Stage 3B steps for S3-07 to S3-11. Open the
state at 1600 px, put your screenshot beside the PNG, go through the Must match list, and write the
result under "Visual check" in the ticket file.
