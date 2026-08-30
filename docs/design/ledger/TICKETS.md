# LP-UI — frontend redesign tickets

> **Amendments:** `AMENDMENTS.md` records changes made after implementation
> started — currently affecting **LP-UI-002**, **LP-UI-004** and **LP-UI-011**.
> Where it disagrees with this file, it wins.
>
> **A7 is binding on every ticket:** the acceptance greps were insufficient —
> `white`/`black` neutrals are invisible to them. Every ticket now also needs
> `rg -- "-(white|black)\\b"` and a per-element contrast sweep in both themes.

Forty tickets, seven epics. Each names the mockup screen it must match, the files
it touches, and what "done" means. Ticket records go in `docs/tickets/LP-UI-XXX.md`
per the convention in `CLAUDE.md`; ADRs go in `decisions.md`.

Read `SPEC.md` before starting any ticket. Sizes: **S** ≤ half a day, **M** 1–2 days,
**L** 3–5 days, **XL** more than a week.

| Epic | Theme | Tickets | Rough total |
|---|---|---|---|
| A | Foundation — tokens, fonts, codemod, status vocabulary | 001–005 | ~3 days |
| B | Primitives and shell | 006–011 | ~4 days |
| C | Core screens | 012–024 | ~3 weeks |
| D | Admin | 025–028 | ~3 days |
| E | Document reviewer | 029–033 | ~2 weeks |
| F | States, accessibility, polish | 034–037 | ~4 days |
| G | Later phases — build when the phase lands | 038–040 | ~1 week |

**Epic A must land in order and must land first.** Everything after it assumes
tokens exist and no `gray-*` remains.

---

## Epic A — Foundation

### LP-UI-001 — Land the Ledger design tokens
**Size** M · **Depends on** — · **Blocks** everything
**Files** `app/globals.css`, `tailwind.config.ts`
**Assets** `assets/globals.css`, `assets/tailwind.config.ts` — drop in as-is
**Mockup** Foundations

Replace both files with the versions in `assets/`. They are drop-in, not a starting
point: the palette is already converted to space-separated HSL triples so that
existing opacity modifiers (`bg-warning/10`, `border-primary/30`) keep working, and
every text tone has been contrast-checked in both themes.

What changes beyond colour: `--radius` drops from `0.5rem` to `0.3125rem` (5px)
with an `8px` container radius; a `fontSize` scale lands with **13px as `sm`, the
workhorse**; `fontWeight` is capped at 600 so `font-bold` no longer resolves;
`--input` becomes the ≥3:1 control border while `--border` stays the decorative
hairline; and a full `.dark` block appears for the first time.

- [ ] Both files replaced; `pnpm build` clean
- [ ] `.dark` on `<html>` produces a complete, legible dark theme
- [ ] `bg-warning/10` and friends still render tinted (proves the HSL form survived)
- [ ] No hardcoded hex anywhere in either file's consumers

> The app will look **worse** at the end of this ticket than it did at the start —
> 784 hardcoded greys are still fighting the new tokens. That is expected and is
> fixed by LP-UI-004. Do not tune the palette to compensate.

### LP-UI-002 — Define the missing `danger` colour
**Size** S · **Depends on** 001
**Files** `tailwind.config.ts` (already in the asset), optionally 20 call sites

Twenty class names across four files reference a `danger` colour that has never
existed — the config defines `destructive`. So `border-danger/40 bg-danger/5
text-danger` compiles to nothing. The component it silently disarms is
`FailedRunBanner` (`verification-panel.tsx:553`): the banner that tells a processor
a six-minute verification run died on the worker. It renders as plain grey text.

The asset config defines `danger` as an alias of `destructive`, so the bug is fixed
with zero call-site churn. Normalising the twenty usages to `destructive` is
optional and can be a follow-up.

- [ ] `FailedRunBanner` renders red — force a failed run and look at it
- [ ] `calculator-card.tsx` `over` / `insufficient` states render red
- [ ] `admin/lenders/[id]` required-field asterisk renders red
- [ ] A regression test asserts the banner has a destructive class

### LP-UI-003 — IBM Plex via next/font
**Size** S · **Depends on** 001
**Files** `lib/fonts.ts` (new), `app/layout.tsx`
**Assets** `assets/fonts.ts`

The current stack is `-apple-system, BlinkMacSystemFont, "Segoe UI"` — no decision.
Plex Sans is built for product UI at 13px; Plex Mono carries money, ratios, loan
ids and citations; Plex Serif italic appears in exactly **one** place, text quoted
verbatim from a document, so "this is the document speaking" reads without a label.
The UPRIGHT serif is a separate register — the product speaking about itself, in
pre-authentication chrome only, never on a working surface (A18).

Self-hosted through `next/font` — no runtime network request, no layout shift.

- [ ] Three variables on `<html>`; `font-sans` / `font-mono` / `font-serif` resolve
- [ ] No CLS on first paint
- [ ] Weights load 400/500/600 only

### LP-UI-004 — Codemod: `gray-*` to design tokens
**Size** M · **Depends on** 001 · **Blocks** every screen ticket
**Files** ~70 files across `app/`, `components/`, `lib/`
**Assets** `assets/codemod-gray-to-token.mjs`

784 hardcoded `gray-*` classes across 67 of 95 components bypass the token layer
entirely. This is why `darkMode: ["class"]` has never been switchable, and why
LP-UI-001 alone only half-works.

It also fixes a live accessibility failure: `text-gray-400` — **180 uses, the most
common text colour in the app** — is 2.54:1 on white. It fails AA for text and
fails even the 3:1 bar for icons. `text-gray-300` (19 uses) is 1.47:1. Everything
in the 300–500 band lands on `muted-foreground` at 4.56:1.

Dry-run verified against the repo on 2026-08-29: **803 replacements, 70 files, 3
left over.** Those three are inverted surfaces (a dark tooltip on a light page) and
are named in the script's footer with their fix.

```bash
cd frontend
node ../docs/design/ledger/assets/codemod-gray-to-token.mjs --dry   # read the report
node ../docs/design/ledger/assets/codemod-gray-to-token.mjs         # write
pnpm biome check --write . && pnpm tsc --noEmit && pnpm test
```

- [ ] Dry-run report matches the numbers above (a drift means the repo moved — read why)
- [ ] The three manual fixes applied
- [ ] `rg "gray-[0-9]" app components lib` returns nothing
- [ ] Dark mode is now genuinely usable end to end
- [ ] Committed as **one** mechanical commit, reviewed as one diff

### LP-UI-005 — One status vocabulary
**Size** M · **Depends on** 001
**Files** `lib/status.ts` (new), `components/status-token.tsx` (new), then the
call sites in `lib/loan-files/status.ts`, `lib/loan-files/documents.ts`,
`lib/loan-files/needs.ts`, `lib/verification/rule-findings.ts`,
`components/file/calculators/calculators-section.tsx`, `calculator-card.tsx`
**Assets** `assets/lib/status.ts`, `assets/components/status-token.tsx`
**Mockup** Foundations — "Status: three channels, always"

Six independent status maps each invented their own colour language. A processor
learns amber six times and it means something different each time. Collapse them
onto six **tones** (blocking, attention, verified, progress, neutral, ai) rendered
one way: colour + glyph shape + word.

Labels stay domain-specific — "Must fix" and "Blocked" are the same tone and
different words, and the words are what processors quote in escalations. The
LP-583 and LP-581 wording is preserved verbatim.

- [ ] `StatusBadge`, `DocumentStatusBadge`, needs pills, outcome badges and the
      calculator dots all render through `StatusToken`
- [ ] The six old maps are deleted, not left orphaned
- [ ] Every status reads correctly with colour removed (test in greyscale)
- [ ] An unknown enum value from the backend renders visibly, never crashes
      (keep the `FALLBACK_META` behaviour from `rule-findings.ts`)

---

## Epic B — Primitives and shell

### LP-UI-006 — Density retune of the `ui/` primitives
**Size** M · **Depends on** 001, 003
**Files** `components/ui/` — button, input, select, badge, card, dialog, sheet,
skeleton, tooltip, dropdown-menu

Bring the vendored shadcn primitives to Ledger's geometry: control height 28px
(`sm` 24px), 5px radius, 13px text, hairline borders, `border-input` on anything
that takes input. `Card` loses its shadow by default and gains a `floating` variant
for the few places that genuinely float.

- [ ] Buttons 28px; `sm` 24px; icon buttons at least 24×24
- [ ] Inputs use `border-input`; focus ring 2px at 2px offset
- [ ] `Card` has no shadow by default
- [ ] `Skeleton` uses `bg-skeleton` (`bg-muted` is invisible on dark cards)

### LP-UI-007 — Table: 28px rows, sticky header, grid semantics
**Size** M · **Depends on** 006
**Files** `components/ui/table.tsx`, `components/dashboard/file-table.tsx`
**Mockup** Pipeline

`TableHead` is `h-12` and `TableCell` is `p-4` — 53px rows. A processor scanning
forty files sees fifteen of them; at 28px they see twenty-four. Drive height from
`--row-h` / `--row-px` so LP-UI-010 can switch it.

Sticky header. Sticky first column on horizontal scroll, with its shadow appearing
only once `scrollLeft > 0` so it does not look bolted on at rest.

Then the accessibility half: `file-table.tsx` currently puts `tabIndex={0}` on
every row, so a 40-row table is 40+ tab stops before the page's actual controls.
Move to the ARIA **grid** pattern with a roving tabindex — arrow keys between
rows, `Home`/`End`, `Enter` to open.

- [ ] Rows 28px; header sticky; no layout shift when data arrives
- [ ] One tab stop for the whole table; arrows move within it
- [ ] Skeleton rows are exactly `--row-h` tall
- [ ] Screen-reader announces row and column position

### LP-UI-008 — App shell: full-bleed, icon rail, ⌘B
**Size** L · **Depends on** 006
**Files** `components/layout/app-shell.tsx`, `sidebar.tsx`, `header.tsx`
**Mockup** every screen — the left two columns

Drop `max-w-6xl` (`app-shell.tsx:21`), which caps the densest screen in the product
at 1152px. Replace the fixed sidebar with a 52px icon rail plus a context column
whose contents depend on the route: saved views on the pipeline, file sections
inside a file, admin sections in admin.

`⌘B` collapses the context column. **Persist the state in a cookie**, so it is
correct on the server render — a sidebar that re-expands on every navigation is
infuriating in an all-day tool.

- [ ] Content is full-bleed
- [ ] `⌘B` toggles; state survives navigation and a hard refresh with no flash
- [ ] Rail items have accessible names and visible focus
- [ ] Below `md`, the rail becomes the existing mobile menu

### LP-UI-009 — File context rail
**Size** M · **Depends on** 008
**Files** `components/layout/file-context-rail.tsx` (new),
`app/(protected)/loan-files/[id]/layout.tsx`
**Mockup** Overview, Verification, Documents, Needs — right-hand column

A 288px rail on file routes carrying submission state, the key ratios (DTI, LTV,
reserves), loan terms and recent activity. These four numbers are the reason a
processor switches tabs today; pin them and the tab switching mostly stops.

Contents vary by tab (coverage and freshness on Documents, run stats and
thoroughness on Verification) but the rail itself is one component.

- [ ] Present on every file route, scrolls independently
- [ ] Adds no DUPLICATE requests — the rail's queries dedupe by key against the
      tab's own (AMENDMENTS A17). It *will* add requests on tabs that do not
      already fetch DTI/LTV/reserves; that is the feature, not a regression.
- [ ] Collapses below `xl` rather than squeezing the work surface

### LP-UI-010 — Density preference, persisted
**Size** S · **Depends on** 007
**Files** `lib/api/preferences.ts`, shell, `components/ui/table.tsx`

`[data-density]` on `<html>`; compact / comfortable / relaxed. Persisted **per
user**, not per view — it is an ergonomic preference, not view state. Extend the
existing preferences endpoint that already stores the verification thoroughness
default.

- [ ] Switching re-renders with no layout thrash
- [ ] Survives reload and applies on the server render
- [ ] Default is compact

### LP-UI-011 — Delete the `/loan-files` stub
**Size** S · **Depends on** 008
**Files** delete `app/(protected)/loan-files/page.tsx`, update `lib/navigation.ts`

A nav item that leads to "this arrives in Epic 4" is worse than no nav item. The
dashboard is the list. Redirect `/loan-files` → `/dashboard` so any bookmark holds.

- [ ] Route redirects; nav item gone; no dead links
- [ ] `lib/navigation.test.ts` updated

---

## Epic C — Core screens

### LP-UI-012 — Login
**Size** S · **Depends on** 003, 006
**Files** `app/(auth)/login/page.tsx`, `components/auth/login-form.tsx`
**Mockup** Login

Split layout: the ledger figure and the thesis line on the left, the form on the
right. The expired-session notice becomes a left rail, not a filled yellow box.
The smallest real test of the token set — if login looks right, the tokens are right.

- [ ] Matches the mockup in both themes
- [ ] Error and expired-session states render as rails
- [ ] Autofocus, autocomplete and password reveal all still work
- [ ] The generic non-enumerating error message is unchanged

### LP-UI-013 — Pipeline: table and attention column
**Size** L · **Depends on** 007, 008
**Files** `app/(protected)/dashboard/page.tsx`, `components/dashboard/*`
**Mockup** Pipeline

Delete `StatsCards` — four `useLoanFiles` queries at `pageSize: 1`, fired to render
four numbers you cannot click. The filter pills below them already do that job and
work.

Add an **Attention** column that says what is actually wrong ("3 findings block
submission", "Pay stub failed extraction", "Bank statement is 46 days old") plus a
left stripe encoding it without colour alone, and a needs-progress bar. Sort by
attention by default.

The attention string is derived, so decide where: a `attention` field on
`LoanFileSummary` is cleaner than five client-side queries. Raise it on the ticket.

- [ ] Stats cards gone; four fewer requests per dashboard load
- [ ] Attention column populated for every row, including a calm state
- [ ] 28px rows; ~24 visible at 1080p
- [ ] Row click and keyboard `Enter` both open the file

### LP-UI-014 — Saved views (frontend)
**Size** M · **Depends on** 013
**Files** `components/dashboard/saved-views.tsx` (new), shell context column

Saved views replace the four hard-coded pills. Flat filters by default with a
"convert to advanced condition" escape hatch — 90% of filters are flat ANDs; do not
make everyone pay for a query builder.

~~Support "current user" as a filter value.~~ **Cut — see AMENDMENTS A19.** A loan
file has no owner in the schema (no `assigned_to_user_id`, no association table;
`loan_officer_name` is an external contact). File assignment is its own feature and
its own ticket; the "My files" and "Unassigned" pills in the mockup go with it.

Serialise view state to the URL as well as persisting it, so a processor can paste
a filtered view into Slack for a colleague.

- [ ] Views listed in the context column with live counts
- [ ] URL round-trips the full filter state
- [ ] Filters are limited to what `SavedViewFilters` accepts (statuses, search) — no field the schema cannot resolve

### LP-UI-015 — Saved views (backend)
**Size** M · **Depends on** — · **Blocks** 014
**Files** `backend/app/models/saved_view.py`, schema, API, migration

Company-scoped saved views: name, filter payload, sort, owner, shared flag. Tenant
isolation per the existing `company_id` discipline. Filters that persist per user
and per company.

- [ ] CRUD endpoints with `company_id` scoping and tests
- [ ] Alembic migration
- [ ] A soft-deleted view never reappears

### LP-UI-016 — File overview: identity strip
**Size** S · **Depends on** 008, 009
**Files** `components/file/file-header.tsx`, `file-tabs.tsx`
**Mockup** Overview — top strip

Borrower, display id, program, purpose, lender and status in one strip, with the
loan amount and property set right. Tabs move into the shell's context column, so
the header stops competing with them.

- [ ] Skeleton has the same height as the loaded strip
- [ ] `Back to dashboard` becomes the breadcrumb in the topbar

### LP-UI-017 — Reconciliation read model (backend)
**Size** L · **Depends on** — · **Blocks** 018
**Files** `backend/app/api/loan_files.py`, a new service, schema

**The one new read model this redesign needs.** For a loan file, return the fields
that have both a *stated* value (1003/MISMO) and a *found* value (extraction), with
per-row agreement and provenance:

```
field_key, label, stated_value, found_value, agreement,
source: { document_id, filename, page, snippet }
```

`agreement` is one of `match | differs | missing | not_stated`. All of this data
exists — stated financials, extractions with `SourceLocation`, and the rule
findings — but nothing joins it. Deterministic join only; no AI in this path.

- [ ] Covers income, employer, assets, valuation, and the insurance gap at minimum
- [ ] Every row carries provenance or an explicit reason it has none
- [ ] Tenant-scoped; tested against the MISMO seed file
- [ ] An ADR records what counts as agreement (tolerances, rounding, name matching)

### LP-UI-018 — The reconciliation ledger
**Size** M · **Depends on** 017
**Files** `components/file/overview/reconciliation-ledger.tsx` (new),
`app/(protected)/loan-files/[id]/page.tsx`
**Mockup** Overview — "Reconciliation — stated against documents"

**The centrepiece.** Stated against found, side by side, rail-coded per row, each
value linked to the page it came from. The product's whole job is this comparison
and it has never appeared on screen as a comparison.

Also on this ticket: remove the two "coming in Phase 6" placeholder cards from the
overview. The context rail now carries the ratios they were promising.

- [ ] Matches the mockup; rails encode agreement without colour alone
- [ ] Source link opens the document at the right page
- [ ] Degrades honestly on a sparse DRAFT file with nothing to reconcile

### LP-UI-019 — Documents: list, upload, freshness
**Size** M · **Depends on** 007, 009
**Files** `app/(protected)/loan-files/[id]/documents/page.tsx`,
`components/file/documents/*`
**Mockup** Documents

Processing rows sit **above** the list rather than inside it, so watching three
uploads land does not disturb the nine documents already there. Documents become
table rows grouped by category. Freshness, duplicates and package coverage move to
the context rail, where each is answerable in one action instead of noticed one row
at a time.

Nothing new from the backend: `staleness`, `package_qualification`, `version_count`
and `period` are already on `DocumentResponse`.

- [ ] Upload progress is legible and never reorders the settled list
- [ ] Live polling still stops once everything settles
- [ ] `?doc=<id>` deep-link still opens the right document

### LP-UI-020 — Verification: outcome tabs and findings as rows
**Size** L · **Depends on** 005, 009
**Files** `components/file/verification/*`
**Mockup** Verification

Today: `Card` → `CardContent` → tabs → per-finding card → nested tag panel. Four
rounded borders and four shadows to reach one sentence. Lift the outcome tabs to
the top level of the page and make findings rail-coded rows: outcome, reason,
guideline citation, source, then the actions.

Two deliberate departures from the current IA, both agreed in the direction doc:
`couldnt_check` gets its **own tab** rather than sitting inside Needs attention,
paired with a batched "request all missing documents" action in the context rail —
group the six by the document they are missing so it is one action, not six.

No backend change. `missing_documents` is already on `RuleFinding`.

- [ ] Nesting depth at most two
- [ ] Governed and legacy lists still never merge or sum (LP-375 stays structural)
- [ ] Every action from `FindingCard` survives: Apply, Override, Note, Accept risk,
      Request docs, Undo
- [ ] The staleness and failed-run banners are rails and are **visible** (they
      depend on LP-UI-002)

### LP-UI-021 — Verification: calculator strip
**Size** M · **Depends on** 020
**Files** `components/file/calculators/*`, `dti/`, `ltv/`
**Mockup** Verification — the strip and the expanded DTI

Six tiles in one strip, one expanded at a time, with the arithmetic shown rather
than hidden: inputs with their source, the derivation steps, the result against the
limit, and any override called out with who set it and how to revert.

- [ ] Expanding does not refetch (the summary hooks already share the cache)
- [ ] Overrides visibly attributed; revert works
- [ ] A gated DTI still shows "Gated", never a fabricated 0 (LP-375)

### LP-UI-022 — Needs as its own route
**Size** M · **Depends on** 005, 009
**Files** new `app/(protected)/loan-files/[id]/needs/page.tsx`,
`components/file/needs/*`, `lib/loan-files/tabs.ts`
**Mockup** Needs

Promote the needs list out of the middle of the Overview. Every need says where it
came from and how much to trust it — a deterministic baseline requirement reads
differently from the AI's reading — and an AI proposal is never acted on until a
processor confirms it. That honesty already exists in `SOURCE_ATTRIBUTION_META`;
this gives it room.

- [ ] New tab in `FILE_TABS`; the Overview keeps a compact summary that links here
- [ ] Grouping (needs action / in review / complete / set aside) preserved
- [ ] Proposed needs show confirm and dismiss, never a silent apply
- [ ] Batch "request all outstanding" composes one message

### LP-UI-023 — New file: MISMO-first intake
**Size** M · **Depends on** 006
**Files** `app/(protected)/loan-files/new/page.tsx`, `components/intake/*`
**Mockup** New file

Two ways in, honestly ranked: the MISMO drop is the primary action because it fills
in everything the form asks for; the form sits below it for files that arrive
without one. Keep the light DRAFT-friendly validation — only first and last name
are required, which matches the model.

- [ ] Dropzone is the visual primary; the form is secondary but complete
- [ ] Field errors inline, in Ledger's error style
- [ ] Import still navigates straight to the created file

### LP-UI-024 — MISMO import warnings
**Size** S · **Depends on** 023
**Files** new route or panel on the created file

"Imported with 6 fields to review" is currently a toast that vanishes. Give the
warnings a surface: which fields, what the parser saw, and a jump to each.

- [ ] Warnings reachable after the toast is gone
- [ ] Each links to the field it concerns
- [ ] Zero warnings shows nothing, not an empty panel

---

## Epic D — Admin

### LP-UI-025 — Admin: lenders list
**Size** S · **Depends on** 007, 008
**Files** `app/(protected)/admin/lenders/page.tsx`, `admin/page.tsx`
**Mockup** Lenders

Overlays are the highest-leverage thing an admin touches — one change moves every
file at that lender. So the list leads with the override count and the most recent
change, not contact details. A lender with zero overrides is **not** a gap: it means
the agency guideline applies unchanged. Say so.

- [ ] Matches the mockup; zero-override state reads as correct, not empty
- [ ] Replaces the `/admin` placeholder with something real

### LP-UI-026 — Admin: lender overlay editor
**Size** M · **Depends on** 025
**Files** `app/(protected)/admin/lenders/[id]/page.tsx`
**Mockup** Overlay

The agency base value sits beside the overridden one on every row, so the effect of
a change is legible without opening the audit trail. Reason stays required and is
shown on every finding the overlay adjusts.

- [ ] Base and effective side by side
- [ ] Change history readable as prose, not a diff dump
- [ ] Reason required; audit entries unchanged in shape

### LP-UI-027 — Overlay blast radius (backend)
**Size** M · **Depends on** — · **Blocks** the rail in 026
**Files** `backend/app/api/overlay_admin.py`, service

Given a proposed override, which open files at that lender would newly block or
newly clear? Estimated against each file's last completed run — it does **not**
re-run verification, and the UI must say so.

- [ ] Endpoint returns counts plus the affected file ids
- [ ] Read-only; no writes, no runs enqueued
- [ ] Tenant-scoped and tested

### LP-UI-028 — Admin: rule validation
**Size** M · **Depends on** 005, 007
**Files** `app/(protected)/admin/validation/page.tsx`
**Mockup** Validation

The honesty screen. A rule with a citation but no human verdict is a **grounded
starter** and the screen says so rather than letting it pass for validated. Keep the
reviewer's own words on a flagged rule — the reason a rule is wrong is worth more
than the flag.

- [ ] Five counts as a strip, not cards
- [ ] Verdict actions inline per rule
- [ ] "Grounded starter" is visually distinct from "Validated" at a glance

---

## Epic E — Document reviewer

> The differentiator, and the only epic with a hard external dependency.

### LP-UI-029 — Bounding-box coordinates in extraction
**Size** L · **Depends on** — · **BLOCKS 030–033**
**Files** `backend/app/ai/extraction/shape.py`, the extraction pipeline, migration

**Answer this before scheduling Epic E.** `SourceLocation` carries `page` and
`snippet` today. The reviewer's highlight needs a rectangle:

```python
class SourceLocation(BaseModel):
    page: int | None
    snippet: str | None
    bbox: tuple[float, float, float, float] | None  # normalised x0,y0,x1,y1
```

If the model does not return coordinates, the interim is **snippet matching**: find
the snippet in the page's text layer and derive the box. Works for text PDFs, fails
on scans — which is exactly where confidence is already lowest, so the fallback
degrades in the right direction.

- [ ] Decision recorded as an ADR either way
- [ ] If coordinates: stored normalised, page-relative, migration for existing rows
- [ ] If snippet matching: a documented accuracy measurement on real files

### LP-UI-030 — Reviewer shell: three resizable panes
**Size** L · **Depends on** 029
**Files** new `components/file/documents/reviewer/*`
**Mockup** Review

Document list, page canvas, extracted fields. Panes resizable, **split persisted**.
Use container queries on the fields panel so field rows reflow to the panel's own
width, not the window's — the same component at 320px and 720px.

- [ ] Split persists per user
- [ ] Page canvas renders a real PDF page
- [ ] The existing drawer remains the fallback for documents with no page image

### LP-UI-031 — Field ↔ box bidirectional linking
**Size** L · **Depends on** 030
**Mockup** Review — hover a field, watch the box

Hover a box → the field highlights. Click a value on the document → focus its
field. Focus a field → the viewer scrolls to and highlights its box (the direction
that actually saves time). Hold `Alt` to reveal every other candidate the model
found.

**One guardrail, implemented exactly:** if a field is already selected and the user
clicks a *different* value on the document, navigate to that other field rather
than overwriting the selected field's value. It is the single most common
destructive misclick in this entire interaction pattern.

- [ ] All three directions work
- [ ] The guardrail has a test
- [ ] Auto-scroll pre-fetches the next flagged field's page

### LP-UI-032 — Confidence and provenance
**Size** M · **Depends on** 031
**Mockup** Review — the fields panel

Three categorical tiers, never a raw decimal in the default view: **Verified**
(human-confirmed), **Confident** (grounded, passes rules — *no chrome at all*), and
**Check this**. The number belongs in a hover, beside the grounding excerpt.

Two thresholds, both already in `globals.css`: `0.85` ordinary, `0.97` critical.
**Criticality overrides confidence** — a 0.97 loan amount, note rate, SSN or income
figure still gets flagged.

An **inferred** value — carried over or derived rather than read off a page — is
badged as inferred. A figure that was never read must not look identical to one
that was; that is the difference between a defensible file and an audit finding.

- [ ] A confident field has no colour, no badge, nothing
- [ ] The critical-field list is a named constant, reviewed by the domain expert
- [ ] Inferred values badged; conflicts show both values inline

### LP-UI-033 — Keyboard review rhythm
**Size** M · **Depends on** 032

The metric is flagged fields per minute, and it is dominated by whether the viewer
scrolls to the box before the processor's eyes land on the field.

```
Tab / ↓      next field needing attention (skips confident ones)
Enter        accept the extracted value as verified
E            edit inline
Shift+Enter  accept and jump to the next flagged field
R            reject / unable to verify
Space        toggle the box overlay
[ / ]        previous / next document
⌘Enter       mark reviewed, advance the queue
```

- [ ] The whole loop is operable without a mouse
- [ ] A discoverable shortcut sheet (`?`)
- [ ] Shortcuts never fire while a text input has focus

---

## Epic F — States, accessibility, polish

### LP-UI-034 — Loading, empty and error states
**Size** M · **Depends on** 006
**Files** `components/ui/error-state.tsx`, `skeleton.tsx`, per-screen states
**Mockup** States

Skeletons match real row heights so nothing shifts on arrival. Empty states say
what goes there and offer the one action that fills it. Errors name what failed,
why, and the way out — **no apologies, and no "something went wrong"**, which tells
a processor nothing they can act on.

Three empty states are genuinely different and must read differently: nothing yet,
filtered to nothing, and structurally empty (a tab that is correct to be empty).

- [ ] Every list has all three
- [ ] No skeleton causes layout shift
- [ ] `ErrorBoundary` fallback matches the mockup's whole-page error

### LP-UI-035 — Dialogs and toasts
**Size** S · **Depends on** 006
**Mockup** States

Destructive confirmations name what goes with the thing being deleted and require
typing the id. Toasts carry an undo where an undo exists — the apply flow already
records enough to reverse itself.

- [ ] Delete dialog matches the mockup
- [ ] Success toasts state the consequence ("DTI moved from 44.7% to 43.8%")
- [ ] Sonner styled to the tokens

### LP-UI-036 — Accessibility pass
**Size** M · **Depends on** everything above

Contrast audit at 13px against every surface including zebra rows.
`:focus-visible` at 2px/2px with `scroll-margin-block` so focus never lands behind
the sticky header (WCAG 2.4.11). 24×24 minimum for icon buttons (2.5.8). Keyboard
alternatives for column and pane resize (2.5.7). A colour-vision-deficiency
simulation pass over every status state.

- [ ] Automated audit clean on every route
- [ ] Full keyboard walkthrough of the processor flow, no traps
- [ ] Every status distinguishable in greyscale
- [ ] Screen-reader pass on the pipeline table and the reviewer

### LP-UI-037 — Narrow-width pass
**Size** M · **Depends on** 036

The design is desktop-first by intent. Decide the 13-inch laptop and tablet
behaviour rather than assuming it: the context rail collapses to a drawer, the
reviewer stacks, the pipeline drops columns by priority.

- [ ] Usable at 1280px with no horizontal page scroll
- [ ] Column drop order recorded, not accidental
- [ ] Tablet decision documented in an ADR

---

## Epic G — Later phases

> Designed ahead so the phase does not start from a blank page. Build when the
> phase lands, not before.

### LP-UI-038 — Communication (Phase 4)
**Size** L · **Mockup** Communication

The thread is the request mechanism: a message carries the needs it asks for, and a
reply's attachment is classified, matched and closed against them automatically —
with the automatic step shown in the thread as its own turn, never silently.

### LP-UI-039 — Conditions (Phase 4.5)
**Size** L · **Mockup** Conditions

Underwriting conditions have a state machine the needs list does not — outstanding,
awaiting borrower, submitted, cleared — so they get a board rather than a list, with
past-due sorted to the top of the first column.

### LP-UI-040 — Lender package (Phase 6)
**Size** L · **Mockup** Package

Assembly is a checklist over what the file already holds. The submit button stays
disabled with its reasons named beside it. Only current, fresh, typed and extracted
documents are eligible — the rule `package_qualification` already computes.

---

## Suggested order

**Week 1** — 001 → 002 → 003 → 004 → 005. Epic A in order, nothing else in parallel.
The app looks worse between 001 and 004; that is the plan.

**Week 2** — 006, 007, 008, 009, 010, 011. The shell. Start 015 and 017 in the
backend in parallel, since 014 and 018 block on them.

**Weeks 3–5** — 012, 013, 014, 016, 018, 019, 020, 021, 022, 023, 024 in flow order.
A processor meets these screens in this order, so the vocabulary settles once
instead of being retrofitted.

**Week 6** — 025 → 028, plus 034 and 035.

**Weeks 7–8** — Epic E, **if and only if 029 is answered**.

**Week 9** — 036, 037.

Epic G when its phase lands.
