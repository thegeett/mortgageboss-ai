# Google Stitch prompts — mortgageboss-ai

Derived from the real frontend: `app/globals.css`, `tailwind.config.ts`,
`components/ui/*`, `components/layout/*`, `lib/loan-files/status.ts`,
`lib/loan-files/needs.ts`, and the built screens (dashboard, file workspace,
documents, verification, calculators, intake, login).

## How to use

1. Stitch works best **one screen per generation**. Paste **BLOCK A (style)** +
   **one screen block** into a single prompt.
2. Generate, then iterate with short follow-ups ("make the sidebar 240px and
   white, not dark", "remove the gradient", "tighten row height to 44px").
3. If the input gets truncated, cut BLOCK A down to the "Non-negotiables" list —
   those eight lines carry most of the identity.
4. Stitch defaults to consumer/marketing aesthetics. The lines telling it what
   **not** to do are doing real work — keep them.

---

## BLOCK A — style system (prepend to every screen prompt)

```
DESIGN SYSTEM — read this before drawing anything.

Product: "mortgageboss·ai", an internal web app for mortgage loan processors at
a processing company. A processor uses it 8 hours a day to assemble a complete,
accurate loan file — documents, extracted data, verification findings, and
required conditions — before it goes to underwriting. It is a dense professional
work tool, closer to Linear / Stripe Dashboard / Google Cloud Console than to a
consumer app or a landing page.

Non-negotiables:
- Light theme only. Page canvas #F9FAFB, all surfaces/cards pure white #FFFFFF.
- Primary blue #3B82F6, used sparingly: primary buttons, active nav, active tab,
  links, and 10%-tint accents. Never a blue hero, never a blue header bar.
- Text: #0F172A for primary text, #6B7280 secondary, #9CA3AF tertiary/micro
  labels. Borders #E5E7EB, 1px, everywhere.
- Semantic colors, only ever as a 10% tint background + full-strength text +
  20% border: danger/blocking #EF4444, warning #D97706, success #22C55E,
  info #0EA5E9.
- System UI font stack (-apple-system, Segoe UI, Roboto). No Google Fonts, no
  display/serif type. Numbers use tabular figures; IDs use a monospace face.
- Corner radius 8px for cards/tiles, 6px for buttons/inputs, full round for
  pills. Shadow: a single very soft shadow-sm on cards. Nothing heavier.
- Icons: Lucide, 16px, stroke 1.5–2, colored #9CA3AF unless they carry meaning.
- Absolutely NO: gradients, glassmorphism, dark sections, rounded blobs, hero
  imagery, stock photos, emoji, illustration, colored drop shadows, purple/teal
  accents, marketing copy, or oversized headings.

Component grammar:
- App shell: 240px fixed white left sidebar (1px right border, wordmark block at
  top, 64px tall), 64px white top header (1px bottom border, section title left,
  user avatar-initials + name + chevron right), scrollable content area on a
  #F9FAFB canvas with content centered at max 1150px, 32px vertical padding.
- Card: white, 1px #E5E7EB border, 8px radius, shadow-sm. Header row = a 16px
  gray icon + a 14px semibold #0F172A title, with an optional small action
  button right-aligned. Body separated by 12–16px, not by a divider.
- Status pill: rounded-full, 1px border, 10px–11px, 500 weight, e.g.
  "In processing" (info tint), "In conditions" (warning tint), "Clear to close"
  (success tint), "Draft" (gray #F3F4F6 / #4B5563 / #E5E7EB).
- Filter pills: a horizontal row; the active pill is solid blue with white text,
  the rest are white with a gray border and gray text.
- Stat tile: white card, 14px gray label left + a 16px meaning-colored icon
  right, then a 30px semibold tabular number below.
- Key/value row: label in #6B7280 on the left, value in #0F172A 500 weight,
  right-aligned, with a hairline #F3F4F6 top border between rows. This is how
  every detail card lists its data — not a two-column form grid.
- Inset note: a #F9FAFB block with a 1px #F3F4F6 border and 6px radius, opened
  by a 10px UPPERCASE letter-spaced gray label ("SOURCE", "WHY", "FORMULA").
  This is the app's signature element — it is how the product shows its
  reasoning and evidence.
- Table: 48px header row, 11px UPPERCASE letter-spaced #9CA3AF column labels,
  56px body rows separated by 1px #E5E7EB, entire row clickable with a light
  gray hover, a "…" icon-button in the last column.
- Tabs: text links along a 1px bottom border; the active one has a 2px blue
  underline and blue text; inactive are gray.
- Buttons: 40px tall, 6px radius, 14px medium. Primary = solid #3B82F6/white.
  Secondary = white with gray border. Tertiary = borderless gray text. Inline
  actions inside cards are 28px tall with 12px text.
- Empty state: centered in the card — a 48px pale circle holding a gray icon, a
  14px semibold line, a 14px gray sentence, then one primary button.

Voice: plain, calm, specific. Real mortgage vocabulary (borrower, DTI, LTV,
appraisal, pay stub, condition, underwriting). Never exclamation marks, never
"Awesome!", never generic lorem ipsum — write realistic sample data.
```

---

## SCREEN 1 — Dashboard (processor worklist)

```
SCREEN: Dashboard — the processor's worklist. Desktop, 1440px wide.

Left sidebar: the wordmark "mortgageboss·ai" (an 8px-radius blue square with a
layers icon, then the name in 16px semibold with "·ai" in blue) in a 64px block
above a 1px divider. Below it three nav rows (16px icon + 14px medium label):
Dashboard (active — pale blue 10% background, blue text and icon), Loan Files,
Administration. At the very bottom, a tiny gray "Phase 1 — Foundation" line.

Header: section title "Dashboard" at 16px semibold, and on the right a 32px
circle with the initials "PP" on a 10%-blue background, the name "Pat Processor"
in 14px, and a small chevron.

Content, stacked with 24px gaps:
1. A title row: "Welcome back, Pat." at 24px bold with "Your loan file worklist."
   in 14px gray beneath, and a primary "+ New file" button on the right.
2. Four stat tiles in one row: "Total files" 128 (gray files icon), "Active" 74
   (blue folder icon), "Action needed" 12 (amber alert-circle icon), "Completed"
   42 (green check-circle icon).
3. One wide white card containing:
   - A toolbar row on a hairline bottom border: filter pills All / Active /
     Action needed / Completed on the left (All is active and solid blue), and a
     288px search input on the right with a leading magnifier icon and the
     placeholder "Search by borrower or file ID…".
   - A table with columns FILE ID, BORROWER, PROPERTY, STATUS, LENDER, LAST
     ACTIVITY, and a trailing "…" column. Eight rows of realistic data: file IDs
     like LF-4821 in monospace, borrower names, full street addresses that
     truncate, a status pill per row (mix of In processing, Ready to submit,
     In conditions, Clear to close, Draft), lender names like "Rocket Mortgage"
     and "UWM", relative times like "2 hours ago" in gray.
   - A footer row on a hairline top border: "Showing 1–8 of 128" on the left, and
     on the right small outline Prev / Next buttons around "Page 1 / 16".
```

---

## SCREEN 2 — Loan file workspace, Overview tab

```
SCREEN: A single loan file — Overview tab. Same shell as the dashboard.

Above the tabs: a small gray "← Back to dashboard" link, then the borrower name
"Akash Patel" at 24px bold, and under it one gray 14px metadata line separated by
middots: "LF-4821" (monospace) · Conventional · Purchase · UWM. Beneath that, a
12px lighter line: "Created Jul 14, 2026 · Updated 2 hours ago". On the far right
of that block, an "In processing" status pill and a small "…" icon button.

A tab bar on a 1px bottom border: Overview (active, blue with a 2px blue
underline), Documents, Verification, Communication, Conditions, Lender Package.

Content, 24px gaps:
1. Three equal cards in a row — "Borrowers" (users icon), "Subject property"
   (building icon), "Loan" (bank icon). Each has a small outline "Edit" button
   with a pencil icon in its header. Each body is a list of key/value rows:
   - Borrowers: the name in semibold with a small gray "Primary" chip, then SSN
     ***-**-4821, Marital status, Email, Phone.
   - Subject property: Address, Type, Occupancy, Estimated value $520,000,
     Purchase price, Valuation amount.
   - Loan: Status (renders as the status pill), Program, Purpose, Amount
     $416,000, Target lender, Loan officer, LO email.
2. A full-width "Needs list" card — the self-maintaining checklist. Its header
   has a clipboard icon, the title, and a gray sub-line "7 needs action · 2 to
   review", with a small outline "+ Add need" button on the right. The body is
   grouped into sections, each opened by an 11px UPPERCASE gray heading with a
   count ("OUTSTANDING 5", "PROPOSED — REVIEW 2", "SATISFIED 4"). Each need is a
   white bordered row: a small colored status dot, a 14px semibold title like
   "Two most recent pay stubs covering 30 consecutive days", a 12px gray
   description, then a row of small pills (state pill, a blue "Proposed —
   review" pill on proposed ones, priority pill). Proposed rows carry a 3px blue
   left border. One row is expanded to show the signature inset note: a
   #F9FAFB block labelled "SOURCE" in 10px uppercase gray with a small blue
   "AI-identified" chip, listing the triggering fact, the document filename with
   a small file icon, and a 10px gray caveat line "AI-identified — verify this is
   the right triggering fact."
3. A two-column bottom row: an "Activity" feed card (a vertical list of small
   icon + text + relative timestamp entries) on the left; on the right two
   dashed-border placeholder cards, each centred with a pale circle icon, a
   title ("AI summary", "Key metrics (DTI / LTV)"), a gray "Coming in Phase 6"
   chip, and one gray explanatory sentence.
```

---

## SCREEN 3 — Verification tab (the flagship screen)

```
SCREEN: A loan file — Verification tab. Same shell, header block and tab bar as
the Overview screen, but the Verification tab is active. This is the densest
screen in the product: it shows the checks the system ran on the file and what
the processor must do about each one.

Content, 24px gaps:
1. A "Calculators" card using progressive disclosure. Its body is a strip of six
   small clickable tiles in one row — Back-end DTI, LTV, Mortgage insurance,
   Self-employed income, Reserves, Max loan. Each tile: a 6px colored status dot
   + a 12px gray title on the first line, and a 14px semibold tabular value below
   ("34.39%", "80.00%", "Required", "$18,240", "Pass", "$462,000"), with a
   chevron on the right. The first tile is expanded — it is blue-outlined on a
   5%-blue background and, beneath the strip, opens the full DTI calculator:
   - Two hero tiles side by side. Left: a gray-50 bordered tile labelled
     "FRONT-END DTI" in 11px uppercase, "28.14%" at 30px semibold tabular, and
     "housing ÷ income" in 12px gray. Right: a blue-outlined tile on a 5%-blue
     background labelled "BACK-END DTI", a green "Within limit" pill top-right,
     "34.39%" at 30px semibold next to a gray "/ 45.00% limit", and a thin
     progress bar underneath filled to roughly three-quarters.
   - Three collapsible breakdown sections — "Gross monthly income", "Housing
     payment (PITI + MI + HOA)", "Monthly debts". Each is a list of line-item
     rows: the label on the left with a tiny gray source tag, the amount on the
     right in tabular figures, and a small pencil icon that appears on the row;
     each section closes with a bolder subtotal row on a top border.
   - A closing inset note labelled "FORMULA" in 10px uppercase gray, spelling out
     the arithmetic in monospace: "($1,970.79 + $640.00) ÷ $7,592.00 = 34.39%".
2. The verification panel card:
   - Header: a 28px blue-tinted rounded square holding a shield icon, the title
     "Verification", a gray "Last run 12 minutes ago" line, and on the right a
     primary "Run verification" button plus a small run-history dropdown showing
     "Run #7".
   - A row of five small stat tiles: Findings 23 (dark), Blocking 3 (red),
     Warnings 8 (amber), Resolved 12 (green), Needs 7 (blue) — each a tiny white
     bordered tile with a centred 18px tabular number over a 10px uppercase gray
     label.
   - An "aggression" control: a 12px gray label "Sensitivity" and a three-stop
     segmented control — Conservative / Balanced / Aggressive — with Balanced
     selected in blue.
   - Filter pills: All, Blocking, Warnings, Income, Assets, Property, Credit.
   - A list of finding cards. Each finding card is white, bordered, and carries:
     a colored left status dot, a 14px semibold headline written like a real
     underwriting exception ("Stated monthly income is $640 higher than the pay
     stubs support"), a row of small chips — a severity pill ("Blocking" red
     tint / "Warning" amber tint), a category chip, a confidence chip "92%", and
     a small "Rule" chip in blue tint (or "AI cross-source" in info tint with a
     sparkles icon) — then a 13px gray explanatory paragraph.
     Underneath, the signature inset note labelled "SOURCE" listing the two
     conflicting values side by side with the document each came from
     ("Pay stub — 06/15/2026" with a file icon, linked in blue).
     A footer row of small 28px actions: primary "Apply fix", then outline
     "Override", "Add note", "Accept risk", "Request docs".
     Show three findings — one blocking, one warning, and one already resolved
     (dimmed, with a green check, "Overridden — LO confirmed bonus income is
     documented in the offer letter" in a gray inset).
```

---

## SCREEN 4 — Documents tab

```
SCREEN: A loan file — Documents tab. Same shell, header block and tab bar, with
Documents active.

Content, 24px gaps:
1. A drag-and-drop upload zone: a full-width dashed-border area, 8px radius,
   white, about 140px tall, centred — a pale circle with an upload-cloud icon, a
   14px semibold "Drop documents here or click to browse", and a 12px gray
   "PDF, JPG or PNG · up to 25 MB each".
2. Documents grouped by category. Each group is opened by an 11px UPPERCASE gray
   heading with a count — "INCOME 4", "ASSETS 3", "PROPERTY 2", "PROCESSING /
   UNCATEGORIZED 1". Under each, rows as white bordered clickable cards, 68px
   tall: a 36px gray-100 rounded square with a file icon; then the derived
   document name in 14px medium ("Pay stub — Akash Patel") with a small gray
   round "v2" chip beside it and a green package-check icon; a 12px medium line
   under it, "Pay period: Jun 16 – Jun 30"; then a 12px gray meta line
   "Pay stub · 248 KB · 3 hours ago"; and a 12px lighter one-line AI gist. On the
   right of the row, a live status badge — a spinner with "Processing" on one
   row, a green "Completed" pill on most, an amber "Needs review" pill on one, a
   red "Failed" pill on one. Add a small amber "Superseded" chip on one row.
3. Show a right-hand slide-over drawer open over the page, 480px wide, white,
   with a 1px left border: the document name as its title, a close X, a metadata
   key/value block, an "EXTRACTION" inset note listing extracted fields as
   key/value rows (Employer, Pay period, Gross pay, YTD gross), and at the bottom
   an outline "Download" button and a red-text "Delete" button.
```

---

## SCREEN 5 — Login

```
SCREEN: Sign in. No sidebar, no header — a plain #F9FAFB page with a single
white card centred at 400px wide, 8px radius, 1px gray border, soft shadow,
32px padding.

Top of the card: the wordmark — an 8px-radius blue square with a layers icon
above "mortgageboss·ai" in 18px semibold with "·ai" in blue — then a 14px gray
line "Sign in to your loan processing workspace."

An amber notice band above the fields: a 6px-radius block with a 10%-amber
background, a 30%-amber border, an alert-circle icon and 14px amber text
"Your session expired. Please sign in again to continue."

Then the form, 20px between fields: a 14px medium "Email" label over a 40px
input with the placeholder "you@company.com"; a "Password" label over a 40px
input showing dots with an eye icon button inset on the right. A full-width 44px
primary blue button reading "Sign in" with a small login icon.

Nothing else — no social login, no "create account", no illustration, no
split-screen marketing panel.
```

---

## SCREEN 6 — New loan file (intake form)

```
SCREEN: New loan file. Same shell; the content column is narrower, about 800px.

Title row: "New loan file" at 24px bold with "Start a file by entering what you
know — you can fill in the rest later." in 14px gray beneath.

First, an import card at the top: a white card whose body is a dashed-border
drop zone with an upload icon, "Import a MISMO 3.4 file", and a 12px gray
"We'll create the file, borrowers, property and loan terms automatically." with
a small "or enter manually below" divider line under the card.

Then three stacked white cards, each with an icon + 14px semibold title and a
12px gray description in its header, and a two-column 16px-gap field grid in its
body. Labels are 14px medium above 40px inputs; required labels carry a small
red asterisk; a select shows a chevron.
- "Borrower" (users icon): First name*, Last name*, Email, Phone, SSN, Marital
  status (select).
- "Subject property" (building icon): Street address, City, State (select), ZIP,
  Property type (select), Occupancy (select).
- "Loan" (bank icon): Loan program (select: Conventional / FHA / VA / USDA),
  Loan purpose (select: Purchase / Refinance), Loan amount (with a $ prefix
  inside the input), Target lender (select), Loan officer, LO email.

A sticky footer row inside the content column: a borderless gray "Cancel" on the
left and a primary "Create loan file" button on the right.
```

---

## OPTIONAL SCREEN 7 — Style sheet (useful to generate first)

```
SCREEN: A design-system reference sheet for this product, on the #F9FAFB canvas,
1440px wide, laid out as labelled sections in white cards.

1. "Color" — swatch rows: Primary #3B82F6, Text #0F172A, Secondary text #6B7280,
   Muted text #9CA3AF, Border #E5E7EB, Surface #FFFFFF, Canvas #F9FAFB, then the
   semantics Danger #EF4444, Warning #D97706, Success #22C55E, Info #0EA5E9 —
   each semantic shown three ways: solid, 10% tint background, and as a pill.
2. "Type" — 24px bold page title, 16px semibold section title, 14px semibold
   card title, 14px body, 12px secondary, 11px uppercase letter-spaced micro
   label, and a 30px semibold tabular number.
3. "Buttons" — primary, secondary outline, ghost, destructive; each at 40px,
   36px and 28px; plus a loading state with a spinner and a disabled state.
4. "Pills & badges" — the eight loan statuses (Draft, In processing, Ready to
   submit, Submitted, In conditions, Clear to close, Closed, Withdrawn) and the
   severity pills Blocking / Warning / Resolved.
5. "Cards & rows" — an empty card, a card with a key/value list, an inset note
   labelled "SOURCE", and a clickable list row.
6. "States" — the four states side by side: skeleton loading (gray rounded bars
   matching content shape), empty (circle icon + title + sentence + button),
   error (a red triangle icon + message + a blue "Retry" text link), and loaded.
```

---

## Reference — the real token values

| Token | HSL in `globals.css` | Hex |
|---|---|---|
| background / card | `0 0% 100%` | `#FFFFFF` |
| app canvas | `bg-gray-50` | `#F9FAFB` |
| foreground | `222 47% 11%` | `#0F172A` |
| primary / ring | `217 91% 60%` | `#3B82F6` |
| secondary / muted / accent | `220 14% 96%` | `#F3F4F6` |
| muted-foreground | `220 9% 46%` | `#6B7280` |
| border / input | `220 13% 91%` | `#E5E7EB` |
| destructive | `0 84% 60%` | `#EF4444` |
| success | `142 71% 45%` | `#22C55E` |
| warning | `32 95% 44%` | `#D97706` |
| info | `199 89% 48%` | `#0EA5E9` |
| radius | `0.5rem` | 8 / 6 / 4px |

Note: `CLAUDE.md` says the primary blue is `#2563EB` (blue-600), but the token
actually shipped in `app/globals.css` is `217 91% 60%`, which is blue-500
`#3B82F6`. The prompts use the shipped value.

## Bringing a Stitch result back into the repo

Stitch emits standalone HTML + Tailwind-ish classes. To land it here:
- Map its literal colors back onto the tokens — `bg-primary`, `text-muted-
  foreground`, `border-border`, `bg-success/10 text-success border-success/20`.
  Never merge ad-hoc hex values; `app/globals.css` is the single source.
- Rebuild the primitives from `components/ui/*` (Button/Card/Badge/Table/Input)
  rather than keeping Stitch's inline markup — variants live in `cva` configs.
- Keep the four-state discipline (loading skeleton / empty / error+retry /
  content); Stitch only ever draws the loaded state.
- Status → pill classes must come from `STATUS_META` in
  `lib/loan-files/status.ts`, not be re-hardcoded per screen.
