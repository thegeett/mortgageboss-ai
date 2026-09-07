# LP-UI-012 — Login

- **Ticket:** LP-UI-012 — the login screen
- **Epic:** Ledger redesign → Epic C (Core screens) — first of thirteen
- **Status:** Completed
- **Date:** 2026-08-30
- **Mockup:** Login

## Summary

Split layout: the ledger motif and the thesis on the left, the form on the
right. The ticket calls this "the smallest real test of the token set — if login
looks right, the tokens are right", and it is: the screen uses `primary`,
`success`, `warning`, `destructive`, `muted`, `foreground-2`, the mono and serif
faces, the 13px scale and the rail idiom, with no new value anywhere.

## What Changed

- **`components/auth/ledger-figure.tsx`** (new) — the motif. Two columns,
  *Stated* and *Found in documents*, with a coloured mark in the margin wherever
  they disagree. Six rows: three agree, two differ, one is missing.
- **`app/(auth)/login/page.tsx`** — rewritten as the split layout. The centred
  card, the radial gradient and the blurred primary blob are gone.
- **`components/auth/login-form.tsx`** — the expired-session notice and the
  error both become **rails**.

## The two notices are rails now

This is SPEC rule 5 — state goes on the left rail and the glyph, never a
background fill — and it is the acceptance criterion this ticket names.

| | before | after |
|---|---|---|
| expired session | `border-warning/30 bg-warning/10 text-warning` | `border-l-2 border-l-warning` on `bg-muted/60`, `text-foreground-2` |
| login error | `border-destructive/30 bg-destructive/5 text-destructive` | `border-l-2 border-l-destructive` on `bg-muted/60` |

Measured in the browser: `border-left: 2px rgb(143, 93, 8)` in light,
`rgb(217, 160, 62)` in dark — the warning token in each theme, against a neutral
surface rather than a coloured one. An expired session is an explanation, not an
alarm, and a filled amber box makes it read as the latter.

The glyphs also moved onto the status vocabulary: `TriangleAlert` for attention,
`CircleX` for blocking, the same shapes `StatusToken` uses.

## Verification

Both themes, driven in a browser signed out:

- **Expired notice** renders as a rail in both themes (values above).
- **Thesis line** computes to `"IBM Plex Serif"` — the upright face the LP-UI-003
  review added when it found the italic-only load left `font-serif` falling back
  to Georgia silently.
- **Autofocus** lands on the email field; `autocomplete` is `email` and
  `current-password`; the password reveal button is present. All three
  behaviours the ticket asks to preserve, checked rather than assumed.
- **The non-enumerating error message is untouched** — `getLoginErrorMessage`
  was not edited; 401 still returns "Invalid email or password." for both a bad
  address and a bad password.
- **Below `lg`** (700px): the left panel is `display: none` and the form is
  visible.

**CI.** biome, tsc, 577 tests, build — green.

## Deviations from the mockup, and why

Three, all because the mockup shows data this screen cannot have:

1. **"Loan processing for Cascade Processing Group."** The mockup names the
   company under the heading. Login is pre-auth — the app does not know which
   company is signing in until it has. Kept "Enter your credentials to access
   your loan files."
2. **"Trouble signing in? Contact your admin."** The mockup makes that a link.
   There is no such route, and a link to nowhere is worse than the sentence
   alone. Kept "Accounts are provisioned by your administrator."
3. **The email is pre-filled in the mockup.** Illustrative only.

## Findings raised

1. **The thesis is a second use of the serif, and the SPEC says there is one.**
   SPEC rule: *"Plex Serif italic appears in exactly one place, text quoted
   verbatim from a document."* The mockup renders this line in upright serif,
   and the LP-UI-003 review already loaded the upright face for LP-UI-029's
   verbatim-snippet state. So the font is available and the mockup is explicit —
   I followed the mockup, since the brief wins where it is specific. But the
   SPEC sentence is now false as written, and should either say "two places" and
   name them, or the login thesis should drop to sans. A design call, not mine.

2. **Every signed-out visit to `/login` logs a console error.** The silent
   refresh fires on load and gets a 401 because there is no refresh cookie —
   the correct outcome, reported as `API error: Request failed with status code
   401`. Pre-existing and not this ticket's, but it means the console is never
   clean on the app's first screen, which is where a developer looks first when
   something else is wrong.

## Assumptions and decisions

- **Decided** the left panel is `hidden` below `lg` rather than stacked above
  the form. Someone signing in on a narrow screen wants the form, not the
  argument for a product they have already bought.
- **Decided** the figure is `aria-hidden`. Its numbers are invented and the
  sentence beneath states the same idea in words; reading six fake money values
  aloud is noise.
- **Decided** the wordmark repeats inside the form column only below `lg`, where
  the left panel that carries it is gone.
- **Assumed** the figure's exact values are illustrative. They are transcribed
  from the mockup, including the two amber rows and the one red.

## Files

- new: `components/auth/ledger-figure.tsx`
- changed: `app/(auth)/login/page.tsx`, `components/auth/login-form.tsx`

## Review pass — the criterion the ticket was named for, unasserted

Reviewed on request from the session running the epic. The hand-off named its own
biggest gap correctly, and both judgement calls resolved differently than
expected.

### There were no LoginForm tests at all

Worth correcting the hand-off on a detail, because it changes what "add one"
means: `login-form` had **no existing coverage**. There is no `login-form.test.tsx`
in the tree and no test file anywhere references `LoginForm`. So the position was
not "the notices are unasserted" but "the form is", on the app's only
unauthenticated screen and its only credential path.

Six tests added, on the rendered form rather than on a class-name constant, per
LP-UI-011's lesson:

- each notice is a RAIL — a 2px left border, and **no** tinted fill, which is the
  ticket's named criterion and the thing a later "let's make the error stand
  out" would quietly undo;
- the live-region semantics the paint change did not touch (`output` for the
  expired notice, `role="alert"` for the failure) are still there;
- the two notices carry different GLYPH SHAPES;
- a valid submission reaches `login()` with the entered credentials — the flow
  the rewrite never exercised;
- a 401 does not enumerate accounts.

### The ticket fixed a SPEC rule 4 violation without noticing

Before this change both notices used `AlertCircle` and were told apart by colour
alone — which rule 4 forbids and which roughly 1 in 12 men cannot use. The
rewrite made them `TriangleAlert` and `CircleX`. That is a real improvement the
write-up does not claim, and it is now pinned, because "unify the icons" is
exactly the tidy-up that would undo it.

### The rail does not change what a screen reader hears

Raised in the hand-off as unverified. It cannot change it: `<output>` (an
implicit polite status) and `role="alert"` are what the accessibility tree
carries, and the diff touches only `className` and the icon component. The
concern was the right one to have — the visual channel did change — but the
answer is structural rather than empirical, and the test now holds it.

### The figure's `display: contents` is genuinely moot, for a checkable reason

`aria-hidden="true"` removes an element **and its whole subtree** from the
accessibility tree, so `display: contents` cannot leak semantics past it. The
engine quirk it is famous for — an element losing its own role, e.g. a `<ul>`
that stops being a list — needs a role to lose, and these wrappers are plain
`<div>`s.

The failure mode actually worth checking on an `aria-hidden` subtree is the
LP-UI-008 one: a focusable descendant becomes reachable by keyboard while
invisible to assistive tech. `LedgerFigure` contains zero focusable elements
(counted: no `a`, `button`, `input`, `select`, `textarea`, `summary` or
`tabIndex`), so the subtree is inert in both senses.

### `/login` no longer logs an error on every signed-out visit

Raised as pre-existing and correct-but-noisy, and it is worth fixing rather than
recording. The response interceptor logged every error in development, including
the 401 the silent refresh gets when there is no session — which is not a
failure, it is the answer. A console with a permanent red line on the app's first
screen is one developers stop reading, and that is where a real error most needs
to be seen.

Narrowed rather than silenced: only a 401 **from the refresh endpoint** is
skipped. A 401 from `/login` is a wrong password, which is a real event, and
every other status still logs.

### The serif rule was not false — it was silent

The hand-off read a contradiction between LP-UI-012's upright serif thesis line
and the brief's *"Plex Serif italic appears in exactly one place, text quoted
verbatim from a document"*, and offered to reword the rule or drop the line to
sans. Neither, because the rule governs a face this page does not use.

Checked in the tree: the only `font-serif` today is `login/page.tsx:44`, with no
`italic`; LP-UI-029's verbatim snippet — the reserved use — is specified as serif
*italic* and has not shipped. Two faces, two registers, and the sentence names
one of them.

Recorded as **A18**, giving the rule a second clause rather than a rewrite:
italic stays reserved and exceptionless for quotation; upright is the product
speaking about itself, in pre-authentication chrome only, and never on a working
surface — where a serif that is not a quotation would teach against the rule
above. Deleting the thesis line would have cost the page its one moment of voice
to protect a rule it was not breaking.

Worth recording the dependency: upright serif renders at all only because the
LP-UI-003 review corrected `plexSerif` from `style: ["italic"]` to
`["normal", "italic"]`. Before that this line would have silently fallen back to
Georgia and the mockup would have looked "close enough".

### Verification

`tsc` clean, `biome` clean over 220 files, 583 tests (from 577), build compiles.
Every fix mutation-checked:

| mutation | result |
| --- | --- |
| restore the filled tinted error box | 1 test fails |
| give both notices the same glyph | 1 test fails |
| leak account existence in the 401 message | 1 test fails |
| break the submit wiring | 1 test fails |

The glyph one passed at first. It compared the two icons' whole `class`
attributes — which include the colour, so two notices wearing the SAME glyph in
different tones have different strings and the assertion passed on precisely the
state it exists to forbid. It now compares the lucide icon name.

### Also worth knowing

The hand-off's note about `document.cookie` not clearing an httpOnly refresh
cookie is correct and cost it a verification pass; `Network.clearBrowserCookies`
over CDP is the working form. That belongs in the workflow docs — it presents as
a missing feature, not as a broken probe, which is the expensive kind of wrong.
