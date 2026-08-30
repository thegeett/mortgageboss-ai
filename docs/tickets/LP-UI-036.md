# LP-UI-036 — Accessibility pass

Epic F. Contrast at 13px against every surface, focus that never hides, 24×24
targets, keyboard alternatives for resize, and a colour-vision pass.

## What was already done, verified rather than assumed

Three of the ACs were largely met before this ticket, and saying so is worth more
than re-implementing them:

- **`:focus-visible` at 2px/2px** was already in `globals.css`, with
  `scroll-margin-block: var(--topbar-h)` for WCAG 2.4.11.
- **Pane resize is keyboard-operable** — LP-UI-030 built the dividers as
  `role="separator"` with `aria-valuenow` and Arrow-key nudging (2.5.7).
- **Target size**: I enumerated every interactive element on the main routes. The
  dashboard has 25 and none under 24×24. The documents tab reported three, and
  all three are legitimate exemptions — two inline text links in a sentence,
  which 2.5.8 exempts explicitly, and the 1×1 visually-hidden file input behind
  the dropzone, where the dropzone is the real target.

## Contrast, measured in a browser

A static scan cannot answer this: a token's real ratio depends on what is behind
it, including a zebra row's tint and any opacity in between. So the audit
composites the actual computed colours up the ancestor chain and applies the WCAG
formula, run over eight route/theme combinations.

**One real failure, in both themes.** `text-muted-foreground/80` at 11.5px in the
reconciliation ledger's snippet line: **3.45:1** in light, 4.36 in dark, against
4.5 required. The token itself passes everywhere it is used; the `/80` is what
broke it. There is no third level of quiet below muted that is still readable —
wanting one is a sign the row has too many levels.

`lib/a11y-contrast.test.ts` now fails on any `text-*` token with an opacity
modifier. That is the cheap guard for the one mistake the expensive scan found.

**The probe carries a positive control.** It plants a known-failing element and
fails loudly if it does not detect it, because "0 below AA" from a broken probe
and "0 below AA" from a clean page are the same output.

## Colour-vision pass

Desaturated every status on the pipeline to full greyscale and read it back. Each
one is still unambiguous: `circle-x` for blocking, `triangle-alert` for attention,
`circle-dashed` for draft, `circle-check-big` for verified, `loader-circle` for in
progress — five distinct silhouettes, each beside its word. LP-UI-005's rule
(colour AND glyph AND word, never colour alone) is what makes this hold, and it
holds by measurement as well as by argument.

## What this ticket actually changed

**One `h1` per route, naming where you are.** Measured across every route: the
dashboard had **two** — the topbar's and the page's own greeting — and
`/loan-files/new` had **none**, because its breadcrumb branch rendered the
location as a plain span. Both are answers to "where am I", and a screen reader
should get exactly one. The greeting is now an `h2` under the page's heading; the
trail's location is an `h1` like every other route's.

**The admin routes announced themselves as the product.** They are not nav items,
so the breadcrumb fell through to a literal `"mortgageboss·ai"` fallback — a
screen reader answered "where am I" with the product name. The fallback is now a
humanised path segment: `/admin/lenders` → "Lenders".

**The pane divider is a 4px line with a 24px grab area.** The line stays a
hairline because a thick divider is visual noise, but a 4px *pointer target* is a
test of mouse accuracy. A pseudo-element extends the grabbable region without
drawing anything; measured live at 24px, and Arrow-key nudging still works.

**`scroll-margin-block` now applies to every focusable element**, not only
`[data-row]`. A row was the case we thought of; a button, link or input scrolled
into view lands under the sticky header just as completely.

## Where the ACs are not literally met

**"Keyboard alternatives for column and pane resize"** — pane resize is done;
**there is no column resize in this app**, so half of that AC has nothing to apply
to. I have not built one to satisfy the sentence.

**"Automated audit clean on every route"** — the contrast and accessible-name
audits ran over the main processor routes and the two admin ones, not literally
every route. The later-phase tabs (Communication, Conditions, Package) are
placeholders.

**The screen-reader pass is an inspection, not a session with a screen reader.** I
checked the machine-checkable parts: no unnamed control, no image without `alt`,
one `main` landmark, one `h1`, and the pipeline grid's roles. Whether the
reviewer's three-pane flow is *usable* with NVDA or VoiceOver is a question only
using one answers, and I have not.

## Tests

`lib/a11y-contrast.test.ts` (3), `components/layout/breadcrumb.test.tsx` (4), and
two added to `reviewer-shell.test.tsx`.

Mutation-checked, 5 mutations, all caught: the trail's location back to a span,
the way back swallowed into the heading, the divider's hit area shrinking to the
hairline, a faded text token slipping back in, and the faded-token scan reading no
files.

The `globals.css` change is mirrored into `docs/design/ledger/assets/globals.css`
— the asset-drift guard caught the omission, which is what it is for.

CI green by exit code: biome, tsc, 932 vitest. No backend changes.

---

## Review (LP-UI-036 review commit)

Reviewed on request from the session running the epic. Three findings.

### 1. Two h1s on every crashed screen

The h1 work is right for every route that can be visited. `AppShell` renders
`<Header/>` — whose breadcrumb is the page's h1 — **above**
`<ErrorBoundary>{children}</ErrorBoundary>`, so when a screen crashes the
fallback's own h1 is ADDED to the trail's rather than replacing it.

This could not be found by visiting routes, because the crashed state is not a
route. It is precisely the asymmetry the ticket named — it just is not in a page
component.

`ErrorBoundary` takes a `headingLevel` now: `2` inside the shell, where the trail
has already named the page and stays on screen behind the failure; `1` at the app
root, where `providers.tsx` mounts a boundary above the shell and the fallback is
the only heading on the page. A page whose first heading is an h2 is its own
violation, so both directions are tested.

**The test that would have caught it has to render the composition.** A test on
the fallback alone passes with the shell still asking for an h1 — verified by
removing `headingLevel={2}` from `AppShell`, which left all 934 other tests green.
`app-shell-headings.test.tsx` renders the shell around a throwing child.

### 2. The faded-token guard missed every variant

Independent of the token list, and the larger of the two gaps: the lookbehind was
`(?<![\w:-])`, which bars a preceding colon — and a colon is exactly how a variant
attaches. `hover:text-muted-foreground/80`, `dark:text-foreground/50` and
`md:text-foreground-2/60` were all invisible to a guard that named the right
tokens. Fixed to `(?<![\w-])`, which still bars a mid-token match.

### 3. The token list named three, and the tree held five

`text-primary/80` and `text-background/75` were both in use and neither was
looked at. **Both measure fine** — 5.10:1 on card and 10.30:1 on the dark tooltip
— which is the point rather than a reprieve: nothing was checking, and
`text-primary/80` sits 0.6 above the line.

The pattern matches any `text-*/opacity` now, with exceptions recorded as measured
pairings carrying their ratio and surface, and a test that an exemption still
names something in the tree. Same posture as the backend's `reviewed_not_critical`:
ban the shape, and make the exception a written decision with a number in it.

### Confirmed, not changed

- **`sectionFromPath`** is correct across every route in the app, not just the two
  checked: evaluated over all thirteen, including a uuid tail and a display-id
  tail. `/loan-files/new` returns "New", which is weak but not wrong, and only
  applies when no nav item matches.
- **No route has two h1s.** Only `login` carries its own, and it is outside the
  protected layout. `FileCrumb` renders spans throughout, so file routes take
  theirs from `FileHeader` and `file-error` — one each.
- **Item 4's scope call is right.** A border's 3:1 is against adjacent colours,
  which a static scan cannot know, and extending the ban there without measuring
  would be the guess this test exists to prevent.

### On the contrast probe

I did not re-run it — it is a browser measurement and the same shape as
LP-UI-034's. The honest limit is the one already named: it answers for the
elements it polled, on the routes it visited, at the moment it ran. What survives
is the ban, which is why the two gaps above matter more than a re-measurement
would.

### Verification

biome 0, tsc 0, **940 vitest**, build clean. No backend change, so no pytest run.
Six mutations, all caught.
